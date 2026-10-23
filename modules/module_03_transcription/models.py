"""Data models for transcripts, segments, and word-level timings."""
from __future__ import annotations

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class TimedWord(BaseModel):
    word: str
    start_ms: int
    end_ms: int
    confidence: float = 1.0

    @property
    def start_s(self) -> float:
        return self.start_ms / 1000.0

    @property
    def end_s(self) -> float:
        return self.end_ms / 1000.0

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


class SpeechPause(BaseModel):
    start_ms: int
    end_ms: int
    duration_ms: int


class TranscriptSegment(BaseModel):
    id: int
    start_ms: int
    end_ms: int
    text: str
    speaker: Optional[str] = None
    confidence: float = 1.0
    words: List[TimedWord] = Field(default_factory=list)

    @property
    def start_s(self) -> float:
        return self.start_ms / 1000.0

    @property
    def end_s(self) -> float:
        return self.end_ms / 1000.0


class Transcript(BaseModel):
    media_id: Optional[str] = None
    provider: str
    language: str = "en"
    duration_seconds: float
    full_text: str
    segments: List[TranscriptSegment] = Field(default_factory=list)
    raw_metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def all_words(self) -> List[TimedWord]:
        words = []
        for s in self.segments:
            words.extend(s.words)
        return words
