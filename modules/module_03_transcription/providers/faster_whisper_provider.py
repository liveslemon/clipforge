"""Local Whisper transcription provider (faster-whisper / CTranslate2), the blueprint's self-host fallback."""
from __future__ import annotations

import asyncio
import os
from typing import Optional, List

from ..models import Transcript, TranscriptSegment, TimedWord


class FasterWhisperProviderError(Exception):
    pass


class FasterWhisperProvider:
    name: str = "faster-whisper"

    def __init__(self, model_size: Optional[str] = None, device: str = "auto", compute_type: str = "int8"):
        # "base" is a good laptop default; set CLIPFORGE_WHISPER_MODEL=small/medium for better accuracy
        self.model_size = model_size or os.environ.get("CLIPFORGE_WHISPER_MODEL", "base")
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def _load_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise FasterWhisperProviderError("faster-whisper is not installed (pip install faster-whisper).") from e
            self._model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
        return self._model

    async def transcribe(
        self,
        audio_path_or_url: str,
        *,
        language: Optional[str] = "en",
        vocabulary: Optional[List[str]] = None,
    ) -> Transcript:
        return await asyncio.to_thread(self._transcribe_sync, audio_path_or_url, language, vocabulary)

    def _transcribe_sync(self, audio_path: str, language: Optional[str], vocabulary: Optional[List[str]]) -> Transcript:
        model = self._load_model()
        segments_iter, info = model.transcribe(
            audio_path,
            language=language,  # None = auto-detect
            word_timestamps=True,
            vad_filter=True,
            initial_prompt=" ".join(vocabulary) if vocabulary else None,
        )

        segments: List[TranscriptSegment] = []
        for idx, seg in enumerate(segments_iter):
            words = [
                TimedWord(
                    word=w.word.strip(),
                    start_ms=int(w.start * 1000),
                    end_ms=max(int(w.end * 1000), int(w.start * 1000)),
                    confidence=round(float(w.probability), 3),
                )
                for w in (seg.words or [])
                if w.word.strip()
            ]
            confidence = sum(w.confidence for w in words) / len(words) if words else 0.0
            segments.append(
                TranscriptSegment(
                    id=idx + 1,
                    start_ms=int(seg.start * 1000),
                    end_ms=int(seg.end * 1000),
                    text=seg.text.strip(),
                    confidence=round(confidence, 3),
                    words=words,
                )
            )

        return Transcript(
            media_id=audio_path,
            provider=f"{self.name}:{self.model_size}",
            language=info.language or (language or "en"),
            duration_seconds=float(info.duration),
            full_text=" ".join(s.text for s in segments),
            segments=segments,
            raw_metadata={"language_probability": round(float(info.language_probability), 3)},
        )
