"""Composite multi-signal highlight scorer implementing Blueprint Section 3.4."""
from __future__ import annotations

import uuid
from typing import List, Optional, Tuple
import numpy as np

from .models import (
    NichePreset,
    NicheWeights,
    PRESET_WEIGHTS,
    CandidateComponents,
    HighlightCandidate,
)
from .hook_narrative_evaluator import HookNarrativeEvaluator
from ..module_03_transcription.models import Transcript, TimedWord
from ..module_03_transcription.segmenter_aligner import TranscriptAligner
from ..module_04_audio_signals.models import AudioSignalsTimeline
from ..module_04_audio_signals.acoustic_analyzer import AcousticAnalyzer
from ..module_05_chat_analyzer.models import ChatMessage
from ..module_05_chat_analyzer.velocity_engine import ChatVelocityEngine


class HighlightScorer:
    """Orchestrates multi-signal scoring, boundary snapping, deduplication, and ranking."""

    def __init__(
        self,
        acoustic_analyzer: Optional[AcousticAnalyzer] = None,
        chat_engine: Optional[ChatVelocityEngine] = None,
        hook_evaluator: Optional[HookNarrativeEvaluator] = None,
    ):
        self.acoustic_analyzer = acoustic_analyzer or AcousticAnalyzer()
        self.chat_engine = chat_engine or ChatVelocityEngine()
        self.hook_evaluator = hook_evaluator or HookNarrativeEvaluator()

    def score_single_window(
        self,
        start_ms: int,
        end_ms: int,
        transcript: Transcript,
        audio_timeline: AudioSignalsTimeline,
        chat_messages: Optional[List[ChatMessage]] = None,
        preset: NichePreset = NichePreset.GAMING,
    ) -> HighlightCandidate:
        """Computes C_score(w) for an exact time window."""
        start_s = start_ms / 1000.0
        end_s = end_ms / 1000.0
        duration_s = max(0.1, end_s - start_s)

        # 1. Weights
        weights = PRESET_WEIGHTS[preset]
        has_chat = bool(chat_messages)
        if not has_chat:
            weights = weights.without_chat()

        # 2. Extract words in window
        words_in_window = [
            w for w in transcript.all_words
            if start_ms <= w.start_ms <= end_ms or start_ms <= w.end_ms <= end_ms
        ]

        # 3. Signals:
        # Hook (S_hook)
        s_hook, hook_reason = self.hook_evaluator.evaluate_hook(words_in_window, start_ms)

        # Energy (S_energy) & Dead air (P_dead)
        energy_score = self.acoustic_analyzer.evaluate_window(audio_timeline, start_s, end_s)
        s_energy = energy_score.energy_score
        p_dead = energy_score.dead_air_ratio

        # Chat (S_chat)
        if has_chat and chat_messages:
            chat_score_obj = self.chat_engine.score_window(chat_messages, start_s, end_s)
            s_chat = chat_score_obj.score
            chat_reason = f"Chat velocity {chat_score_obj.peak_msg_rate:.1f} msg/s"
            if chat_score_obj.has_clip_it_trigger:
                chat_reason += " ('CLIP IT' triggered)"
        else:
            s_chat = 0.0
            chat_reason = "No chat log"

        # Narrative (S_narrative)
        s_narrative, narr_reason = self.hook_evaluator.evaluate_narrative(words_in_window, duration_s)

        # 4. Composite Formula:
        # C_score = clip[0, 100](100 * (wh*Sh + we*Se + wc*Sc + wn*Sn - wp*Pdead))
        weighted_sum = (
            weights.w_hook * s_hook
            + weights.w_energy * s_energy
            + weights.w_chat * s_chat
            + weights.w_narrative * s_narrative
            - weights.w_dead_penalty * p_dead
        )
        c_score = float(np.clip(weighted_sum * 100.0, 0.0, 100.0))

        # Title & Explanation
        title = self.hook_evaluator.generate_title(words_in_window)
        reasons = []
        if s_hook >= 0.7:
            reasons.append(hook_reason)
        if s_energy >= 0.6:
            reasons.append(f"Acoustic spike (Z_RMS: {energy_score.max_z_rms})")
        if s_chat >= 0.5:
            reasons.append(chat_reason)
        if p_dead > 0.2:
            reasons.append(f"Dead-air penalty ({p_dead*100:.0f}% silence)")

        explanation = " + ".join(reasons) if reasons else f"Consistent {preset.value} stream flow"
        snippet = " ".join(w.word for w in words_in_window[:20])

        return HighlightCandidate(
            id=f"cand_{uuid.uuid4().hex[:8]}",
            start_ms=start_ms,
            end_ms=end_ms,
            duration_s=round(duration_s, 2),
            score=round(c_score, 1),
            niche=preset,
            title=title,
            reason=explanation,
            components=CandidateComponents(
                s_hook=s_hook,
                s_energy=s_energy,
                s_chat=s_chat,
                s_narrative=s_narrative,
                p_dead=p_dead,
            ),
            transcript_snippet=snippet,
        )

    def find_candidates(
        self,
        transcript: Transcript,
        audio_timeline: AudioSignalsTimeline,
        chat_messages: Optional[List[ChatMessage]] = None,
        preset: NichePreset = NichePreset.GAMING,
        min_duration_s: float = 15.0,
        max_duration_s: float = 60.0,
        stride_s: float = 10.0,
        max_candidates: int = 10,
    ) -> List[HighlightCandidate]:
        """Scans stream in sliding candidate windows, snaps boundaries, dedups, and ranks top N."""
        aligner = TranscriptAligner(transcript)
        total_dur_s = audio_timeline.duration_s

        raw_candidates: List[HighlightCandidate] = []

        curr_t = 0.0
        while curr_t + min_duration_s <= total_dur_s:
            window_len = min(35.0, total_dur_s - curr_t)  # ~35s target
            raw_start_ms = int(curr_t * 1000)
            raw_end_ms = int((curr_t + window_len) * 1000)

            # Snap boundaries per Blueprint Section 3.4
            snapped_start_ms = aligner.snap_start_boundary(raw_start_ms, max_lookback_ms=15000)
            snapped_end_ms = aligner.snap_end_boundary(raw_end_ms, pad_ms=300)

            dur_s = (snapped_end_ms - snapped_start_ms) / 1000.0
            if min_duration_s <= dur_s <= max_duration_s:
                cand = self.score_single_window(
                    snapped_start_ms,
                    snapped_end_ms,
                    transcript,
                    audio_timeline,
                    chat_messages,
                    preset,
                )
                raw_candidates.append(cand)

            curr_t += stride_s

        # Sort descending by score
        raw_candidates.sort(key=lambda c: c.score, reverse=True)

        # Deduplication (> 40% temporal overlap filter per blueprint)
        deduped: List[HighlightCandidate] = []
        for cand in raw_candidates:
            is_dup = False
            for accepted in deduped:
                # Calculate overlap
                overlap_start = max(cand.start_ms, accepted.start_ms)
                overlap_end = min(cand.end_ms, accepted.end_ms)
                overlap_ms = max(0, overlap_end - overlap_start)

                min_dur_ms = min(cand.end_ms - cand.start_ms, accepted.end_ms - accepted.start_ms)
                if min_dur_ms > 0 and (overlap_ms / float(min_dur_ms)) > 0.40:
                    is_dup = True
                    break

            if not is_dup:
                deduped.append(cand)
                if len(deduped) >= max_candidates:
                    break

        return deduped
