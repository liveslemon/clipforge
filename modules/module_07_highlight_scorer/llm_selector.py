"""Claude-driven clip selection — how commercial clippers (OpusClip, Vizard, Klap) pick moments.

Claude reads the timestamped transcript plus a summary of the audio/chat spikes and proposes clips that are
self-contained (setup + payoff), open on a hook, and make sense to someone who never saw the stream. Each
proposal is then snapped to word boundaries and scored by the existing signal scorer; the final score blends
Claude's judgement with the measured signals so a great-sounding but dead-air moment still gets penalised.
"""
from __future__ import annotations

import uuid
from typing import List, Optional

import numpy as np
from pydantic import BaseModel, Field

from ..llm import LLMError, structured_call
from ..module_03_transcription.models import Transcript
from ..module_03_transcription.segmenter_aligner import TranscriptAligner
from ..module_04_audio_signals.models import AudioSignalsTimeline
from ..module_05_chat_analyzer.models import ChatMessage
from ..module_05_chat_analyzer.velocity_engine import ChatVelocityEngine
from .composite_scorer import HighlightScorer
from .models import CandidateComponents, HighlightCandidate, NichePreset

LLM_WEIGHT = 0.6  # final = 60% Claude judgement + 40% measured signals

NICHE_GUIDANCE = {
    NichePreset.GAMING: "gaming stream: clutch plays, fails, rage, funny reactions, chat-worthy moments",
    NichePreset.JUST_CHATTING: "just-chatting stream: hot takes, stories with a punchline, funny exchanges",
    NichePreset.IRL: "IRL stream: surprising encounters, funny situations, emotional moments",
    NichePreset.PODCAST: "podcast: strong opinions, insights, stories, quotable lines",
    NichePreset.EDUCATIONAL: "educational: clear self-contained explanations, surprising facts, practical tips",
}

SYSTEM = """You are a senior short-form video editor who cuts stream VODs into TikTok / YouTube Shorts / Reels clips.
A great clip: opens with a hook in the first 2-3 seconds, has a clear setup and payoff, makes sense to someone who
never watched the stream, and ends right after the payoff (no trailing filler).
Use the transcript timestamps exactly. Never invent events that are not in the transcript.
Rate clip_worthiness honestly (0-100) — it predicts how watchable the clip is, not guaranteed views.
Titles: punchy, under 60 characters, no clickbait that the clip does not deliver."""


class ClipProposal(BaseModel):
    start_s: float = Field(description="Clip start in total seconds from video start (e.g. 24.5 or 83.8; NOT 1:23 and NOT 123 for 1m23s)")
    end_s: float = Field(description="Clip end in total seconds from video start (e.g. 54.0 or 99.2)")
    title: str
    hook_line: str = Field(description="The opening line that hooks the viewer, quoted from the transcript")
    why: str = Field(description="One sentence: why this works as a standalone clip")
    clip_worthiness: int = Field(description="0-100")
    hashtags: List[str] = Field(description="3-5 relevant hashtags without #")


class ClipPlan(BaseModel):
    clips: List[ClipProposal]


def _fmt(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def _parse_llm_seconds(val: float, max_dur: float) -> float:
    """Handles LLMs occasionally confusing MM:SS with an integer, e.g. 1m23s written as 123 instead of 83."""
    if val > max_dur and val >= 100:
        mins = int(val // 100)
        secs = val % 100
        if secs < 60:
            converted = mins * 60 + secs
            if converted <= max_dur:
                return float(converted)
    return float(val)


def _signal_summary(timeline: AudioSignalsTimeline, chat: Optional[List[ChatMessage]], top_k: int = 8) -> str:
    lines = []
    pts = sorted(timeline.points, key=lambda p: p.z_rms, reverse=True)
    peaks: List[float] = []
    for p in pts:
        if all(abs(p.timestamp_s - q) > 8 for q in peaks):
            peaks.append(p.timestamp_s)
            lines.append(f"- loud moment at {_fmt(p.timestamp_s)} (loudness z={p.z_rms:.1f}"
                         + (f", shout/laugh prob {p.event_prob:.2f}" if p.event_prob > 0.3 else "") + ")")
        if len(peaks) >= top_k:
            break
    if chat:
        engine = ChatVelocityEngine()
        points, mean, std = engine.compute_timeline(chat)
        spikes = sorted(points, key=lambda p: p.msg_rate_per_sec, reverse=True)
        shown: List[float] = []
        for p in spikes:
            on_stream = max(0.0, p.timestamp_s - engine.lag_compensation_s)
            if p.msg_rate_per_sec > mean + 2 * std and all(abs(on_stream - q) > 8 for q in shown):
                shown.append(on_stream)
                lines.append(f"- chat spike reacting to ~{_fmt(on_stream)} ({p.msg_rate_per_sec:.1f} msg/s vs "
                             f"baseline {mean:.1f}" + (", viewers asked to clip it" if p.clip_keyword_count else "") + ")")
            if len(shown) >= top_k:
                break
    return "\n".join(lines) or "- no notable spikes"


class LLMClipSelector:
    def __init__(self, scorer: Optional[HighlightScorer] = None):
        self.scorer = scorer or HighlightScorer()

    def propose(self, transcript: Transcript, timeline: AudioSignalsTimeline, chat: Optional[List[ChatMessage]],
                preset: NichePreset, min_s: float, max_s: float, max_candidates: int, context: str = "") -> ClipPlan:
        transcript_lines = "\n".join(f"[{s.start_s:.1f}s ({_fmt(s.start_s)})–{s.end_s:.1f}s ({_fmt(s.end_s)})] {s.text}" for s in transcript.segments)
        user = (
            f"Content type: {NICHE_GUIDANCE[preset]}\n"
            f"About this video (from the uploader): {context or 'not provided'}\n"
            f"Video length: {_fmt(timeline.duration_s)}. Each clip must be {min_s:.0f}–{max_s:.0f} seconds.\n"
            f"Propose up to {max_candidates} non-overlapping clips, best first.\n\n"
            f"MEASURED SIGNALS (audio loudness spikes and chat reactions):\n{_signal_summary(timeline, chat)}\n\n"
            f"TIMESTAMPED TRANSCRIPT:\n{transcript_lines}"
        )
        return structured_call(SYSTEM, user, ClipPlan, effort="high")

    def to_candidates(self, plan: ClipPlan, transcript: Transcript, timeline: AudioSignalsTimeline,
                      chat: Optional[List[ChatMessage]], preset: NichePreset, min_s: float, max_s: float,
                      max_candidates: int) -> List[HighlightCandidate]:
        aligner = TranscriptAligner(transcript)
        duration_s = timeline.duration_s
        duration_ms = int(duration_s * 1000)
        out: List[HighlightCandidate] = []
        for p in plan.clips:
            raw_start = _parse_llm_seconds(p.start_s, duration_s)
            raw_end = _parse_llm_seconds(p.end_s, duration_s)
            start = max(0, aligner.snap_start_boundary(int(raw_start * 1000), max_lookback_ms=2500))
            end = min(duration_ms, aligner.snap_end_boundary(int(raw_end * 1000)))
            if (end - start) / 1000 > max_s:  # too long: cut at the last word boundary that fits
                end = min(duration_ms, aligner.snap_end_boundary(start + int(max_s * 1000) - 400))
            if (end - start) / 1000 < min_s:  # too short: extend to next boundary if possible
                extended = min(duration_ms, aligner.snap_end_boundary(start + int(min_s * 1000) + 400))
                if (extended - start) / 1000 >= min_s:
                    end = extended
            dur = (end - start) / 1000
            if dur < min_s - 0.05 or dur > max_s * 1.05 or end <= start:
                continue
            if any(min(end, c.end_ms) - max(start, c.start_ms) > 0.4 * min(end - start, c.end_ms - c.start_ms) for c in out):
                continue
            signal = self.scorer.score_single_window(start, end, transcript, timeline, chat, preset)
            s_llm = float(np.clip(p.clip_worthiness, 0, 100)) / 100
            final = LLM_WEIGHT * 100 * s_llm + (1 - LLM_WEIGHT) * signal.score
            out.append(HighlightCandidate(
                id=f"cand_{uuid.uuid4().hex[:8]}", start_ms=start, end_ms=end, duration_s=round(dur, 2),
                score=round(final, 1), niche=preset, title=p.title.strip()[:90],
                reason=f"{p.why} | signals: {signal.reason}",
                components=signal.components.model_copy(update={"s_llm": round(s_llm, 3)}),
                transcript_snippet=signal.transcript_snippet, source="llm+signals",
                hook_line=p.hook_line, hashtags=[h.lstrip("#") for h in p.hashtags][:5],
            ))
        out.sort(key=lambda c: c.score, reverse=True)
        return out[:max_candidates]

    def select(self, transcript: Transcript, timeline: AudioSignalsTimeline, chat: Optional[List[ChatMessage]],
               preset: NichePreset = NichePreset.GAMING, min_s: float = 15, max_s: float = 60,
               max_candidates: int = 8, context: str = "") -> List[HighlightCandidate]:
        """Raises LLMError (incl. LLMUnavailable) so callers can fall back to HighlightScorer.find_candidates."""
        if not transcript.all_words:
            raise LLMError("No speech in transcript — nothing for Claude to select from.")
        plan = self.propose(transcript, timeline, chat, preset, min_s, max_s, max_candidates, context)
        return self.to_candidates(plan, transcript, timeline, chat, preset, min_s, max_s, max_candidates)
