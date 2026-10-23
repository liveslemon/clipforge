"""Transcription provider protocol definition."""
from __future__ import annotations

from typing import Protocol, Optional, List
from .models import Transcript


class TranscriptionProvider(Protocol):
    """Protocol for Speech-to-Text adapters (AssemblyAI, Deepgram, Whisper, Mock)."""

    name: str

    async def transcribe(
        self,
        audio_path_or_url: str,
        *,
        language: Optional[str] = "en",
        vocabulary: Optional[List[str]] = None,
    ) -> Transcript:
        """Transcribe an audio file and return word-level timestamps."""
        ...
