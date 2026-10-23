"""Context-aware caption proofreading with Claude.

Speech models mishear words that sound alike, especially over music or game audio. Claude reads the whole
transcript (plus the user's description of the video) and may correct ONLY words the speech model itself
flagged as low-confidence. Every proposed fix is validated before it is applied, and the corrected words
inherit the original words' timing, so captions stay in sync.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from pydantic import BaseModel, Field

from ..llm import LLMError, llm_available, structured_call
from .models import TimedWord, Transcript, TranscriptSegment

LOW_CONFIDENCE = 0.6
MAX_SPAN_WORDS = 6


class Correction(BaseModel):
    segment_id: int = Field(description="Segment id the words belong to")
    start_word: int = Field(description="Index of the first word to replace (0-based, within the segment)")
    end_word: int = Field(description="Index of the last word to replace (inclusive)")
    replacement: str = Field(description="What was most likely actually said")
    reason: str = Field(description="Short justification")


class ProofreadResult(BaseModel):
    corrections: List[Correction]


SYSTEM = """You proofread automatic speech-recognition captions for short-form video clips.
Speech recognition mishears words that SOUND similar, especially over music or game audio.
You are given the full transcript for context, plus a list of words the recogniser was unsure about.

Rules:
- Only propose a correction for a span that contains at least one uncertain word.
- Only correct when the heard words clearly do not fit the context AND a similar-sounding phrase clearly does.
- Keep the speaker's own wording, slang and grammar. Never rephrase, summarise, censor or add content.
- If you are not confident, leave it alone. Returning no corrections is a good answer."""


def _format_transcript(transcript: Transcript) -> Tuple[str, str, int]:
    lines, suspects = [], []
    n_suspect = 0
    for seg in transcript.segments:
        lines.append(f"[{seg.id}] " + " ".join(w.word for w in seg.words))
        flagged = [f"{i}:{w.word}({w.confidence:.2f})" for i, w in enumerate(seg.words) if w.confidence < LOW_CONFIDENCE]
        if flagged:
            n_suspect += len(flagged)
            suspects.append(f"segment {seg.id}: " + " ".join(f"{i}:{w.word}" for i, w in enumerate(seg.words))
                            + "\n  uncertain → " + ", ".join(flagged))
    return "\n".join(lines), "\n".join(suspects), n_suspect


def validate(correction: Correction, transcript: Transcript) -> Optional[str]:
    """Returns why a correction is rejected, or None if it is safe to apply."""
    seg = next((s for s in transcript.segments if s.id == correction.segment_id), None)
    if seg is None:
        return "unknown segment"
    if not (0 <= correction.start_word <= correction.end_word < len(seg.words)):
        return "word range out of bounds"
    span = seg.words[correction.start_word:correction.end_word + 1]
    if len(span) > MAX_SPAN_WORDS:
        return "span too long"
    if not any(w.confidence < LOW_CONFIDENCE for w in span):
        return "span has no uncertain word"
    new_words = correction.replacement.split()
    if not new_words or len(new_words) > len(span) + 2:
        return "replacement length implausible"
    if " ".join(new_words).lower() == " ".join(w.word for w in span).lower():
        return "no change"
    return None


def apply_corrections(transcript: Transcript, corrections: List[Correction]) -> Tuple[Transcript, List[dict]]:
    """Applies validated corrections; replacement words share the replaced span's time range evenly."""
    applied, by_seg = [], {}
    for c in corrections:
        if validate(c, transcript) is None:
            by_seg.setdefault(c.segment_id, []).append(c)

    segments: List[TranscriptSegment] = []
    for seg in transcript.segments:
        words = list(seg.words)
        # apply right-to-left so earlier indices stay valid; skip overlapping corrections
        taken: set = set()
        for c in sorted(by_seg.get(seg.id, []), key=lambda c: c.start_word, reverse=True):
            idx = set(range(c.start_word, c.end_word + 1))
            if idx & taken:
                continue
            taken |= idx
            span = words[c.start_word:c.end_word + 1]
            start, end = span[0].start_ms, span[-1].end_ms
            new = c.replacement.split()
            step = (end - start) / len(new)
            replacement = [TimedWord(word=w, start_ms=int(start + i * step), end_ms=int(start + (i + 1) * step),
                                     confidence=0.75) for i, w in enumerate(new)]
            words[c.start_word:c.end_word + 1] = replacement
            applied.append({"segment_id": seg.id, "before": " ".join(w.word for w in span),
                            "after": c.replacement, "reason": c.reason, "start_s": start / 1000})
        segments.append(seg.model_copy(update={"words": words, "text": " ".join(w.word for w in words)}))

    new_t = transcript.model_copy(update={
        "segments": segments, "full_text": " ".join(s.text for s in segments),
        "raw_metadata": {**transcript.raw_metadata, "proofread_corrections": len(applied)},
    })
    return new_t, sorted(applied, key=lambda a: a["start_s"])


def proofread(transcript: Transcript, context: str = "") -> Tuple[Transcript, List[dict], str]:
    """Returns (transcript, applied corrections, status). Never raises: on any LLM problem it returns the input."""
    if not llm_available():
        return transcript, [], "skipped: no ANTHROPIC_API_KEY"
    full, suspects, n = _format_transcript(transcript)
    if n == 0:
        return transcript, [], "skipped: no uncertain words"
    user = (f"What the video is about (from the uploader): {context or 'not provided'}\n\n"
            f"FULL TRANSCRIPT (segment id in brackets):\n{full}\n\n"
            f"SEGMENTS WITH UNCERTAIN WORDS (index:word, confidence in brackets):\n{suspects}")
    try:
        result = structured_call(SYSTEM, user, ProofreadResult, effort="medium")
    except LLMError as e:
        return transcript, [], f"skipped: {e}"
    new_t, applied = apply_corrections(transcript, result.corrections)
    rejected = len(result.corrections) - len(applied)
    return new_t, applied, f"ok: {len(applied)} corrections applied" + (f", {rejected} rejected" if rejected else "")
