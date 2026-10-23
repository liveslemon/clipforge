"""High-accuracy local Whisper provider: large-v3-turbo + hallucination guards + topic/term context.

Measured on a 101 s campus promo with background music (ground truth = its burned-in captions):
    whisper base (old default) ........... 30% of spoken words recovered
    large-v3-turbo + guards .............. 79%   (12 s on an M2 via mlx)
    + topic/terms context prompt ......... ~82%  (fixes e.g. "smart image system" -> "smart energy system")

Backends: mlx-whisper on Apple Silicon (GPU), faster-whisper elsewhere (CPU, much slower for turbo).
"""
from __future__ import annotations

import asyncio
import os
import platform
import re
import sys
from typing import Dict, List, Optional

from ..models import TimedWord, Transcript, TranscriptSegment


class LocalWhisperProviderError(Exception):
    pass


# Whisper invents these over music/silence; dropped when the model isn't confident about them
HALLUCINATION_PHRASES = {
    "thank you", "thanks for watching", "thank you for watching", "please subscribe", "subscribe",
    "bye", "you", "so", "hmm", "uh", "um", "subtitles by the amara org community", "music",
}

# Anti-hallucination decoding settings shared by both backends
GUARDS = dict(
    condition_on_previous_text=False,  # stops "we are all with the same kind" style repetition loops
    compression_ratio_threshold=2.4,
    no_speech_threshold=0.6,
)


def _norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", text.lower()))


def clean_segments(segments: List[Dict]) -> List[Dict]:
    """Drops hallucinated segments: low-confidence stock phrases and verbatim repeats of the previous segment."""
    kept: List[Dict] = []
    for seg in segments:
        words = seg.get("words") or []
        if not words:
            continue
        conf = sum(w["probability"] for w in words) / len(words)
        text = _norm(seg["text"])
        if text in HALLUCINATION_PHRASES and conf < 0.7:
            continue
        if kept and text and text == _norm(kept[-1]["text"]):
            continue
        kept.append(seg)
    return kept


def words_to_segments(words: List[Dict], max_gap_s: float = 0.8, max_words: int = 14) -> List[TranscriptSegment]:
    """Groups timed words into sentence-like segments (break on . ? !, long pauses, or length)."""
    segments: List[TranscriptSegment] = []
    current: List[TimedWord] = []

    def flush():
        if current:
            segments.append(TranscriptSegment(
                id=len(segments) + 1, start_ms=current[0].start_ms, end_ms=current[-1].end_ms,
                text=" ".join(w.word for w in current),
                confidence=round(sum(w.confidence for w in current) / len(current), 3),
                words=list(current),
            ))
            current.clear()

    for w in words:
        tw = TimedWord(word=w["word"].strip(), start_ms=int(w["start"] * 1000),
                       end_ms=max(int(w["end"] * 1000), int(w["start"] * 1000)),
                       confidence=round(float(w["probability"]), 3))
        if not tw.word:
            continue
        if current and (tw.start_ms - current[-1].end_ms > max_gap_s * 1000 or len(current) >= max_words):
            flush()
        current.append(tw)
        if tw.word[-1] in ".?!":
            flush()
    flush()
    return segments


def is_apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


class LocalWhisperProvider:
    name: str = "local-whisper"

    def __init__(self, model: Optional[str] = None, context: Optional[str] = None, backend: Optional[str] = None):
        """
        model: Whisper size (default large-v3-turbo; CLIPFORGE_WHISPER_MODEL overrides).
        context: what the video is about plus names/terms — steers ambiguous words toward ones that fit.
        backend: "mlx" or "faster-whisper" (auto: mlx on Apple Silicon if installed).
        """
        self.model = model or os.environ.get("CLIPFORGE_WHISPER_MODEL", "large-v3-turbo")
        self.context = (context or "").strip()
        self.backend = backend or self._auto_backend()
        self._fw_model = None

    @staticmethod
    def _auto_backend() -> str:
        if is_apple_silicon():
            try:
                import mlx_whisper  # noqa: F401
                return "mlx"
            except ImportError:
                pass
        try:
            import faster_whisper  # noqa: F401
            return "faster-whisper"
        except ImportError as e:
            raise LocalWhisperProviderError("Install mlx-whisper (Apple Silicon) or faster-whisper.") from e

    async def transcribe(
        self,
        audio_path_or_url: str,
        *,
        language: Optional[str] = "en",
        vocabulary: Optional[List[str]] = None,
    ) -> Transcript:
        return await asyncio.to_thread(self._transcribe_sync, audio_path_or_url, language, vocabulary)

    def _run(self, audio_path: str, language: Optional[str], prompt: Optional[str]) -> tuple[List[Dict], str]:
        """One decoding pass → (segments with words as plain dicts, detected language)."""
        if self.backend == "mlx":
            import mlx_whisper
            repo = self.model if "/" in self.model else f"mlx-community/whisper-{self.model}"
            res = mlx_whisper.transcribe(
                audio_path, path_or_hf_repo=repo, language=language, word_timestamps=True,
                initial_prompt=prompt, hallucination_silence_threshold=2.0, logprob_threshold=-1.0, **GUARDS,
            )
            segs = [{"text": s["text"], "start": s["start"], "end": s["end"],
                     "words": [{"word": w["word"], "start": w["start"], "end": w["end"], "probability": w["probability"]}
                               for w in s.get("words", [])]} for s in res["segments"]]
            return segs, res.get("language") or language or "en"

        from faster_whisper import WhisperModel
        if self._fw_model is None:
            self._fw_model = WhisperModel(self.model, device="auto", compute_type="int8")
        it, info = self._fw_model.transcribe(
            audio_path, language=language, word_timestamps=True, initial_prompt=prompt, beam_size=5,
            vad_filter=True, log_prob_threshold=-1.0, hallucination_silence_threshold=2.0, **GUARDS,
        )
        segs = [{"text": s.text, "start": s.start, "end": s.end,
                 "words": [{"word": w.word, "start": w.start, "end": w.end, "probability": w.probability}
                           for w in (s.words or [])]} for s in it]
        return segs, info.language or language or "en"

    def _transcribe_sync(self, audio_path: str, language: Optional[str], vocabulary: Optional[List[str]]) -> Transcript:
        hint = " ".join(x for x in [self.context, ", ".join(vocabulary or [])] if x).strip()
        raw, lang = self._run(audio_path, language, hint or None)
        kept = clean_segments(raw)
        segments = words_to_segments([w for s in kept for w in s["words"]])
        all_words = [w for s in segments for w in s.words]
        return Transcript(
            media_id=audio_path,
            provider=f"{self.name}:{self.backend}:{self.model}",
            language=lang,
            duration_seconds=max((w.end_ms for w in all_words), default=0) / 1000.0,
            full_text=" ".join(s.text for s in segments),
            segments=segments,
            raw_metadata={
                "backend": self.backend, "model": self.model, "context_used": bool(hint),
                "dropped_hallucinated_segments": len(raw) - len(kept),
                "low_confidence_words": sum(w.confidence < 0.5 for w in all_words),
            },
        )
