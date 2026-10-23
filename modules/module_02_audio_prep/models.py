"""Data models for audio extraction, waveform generation, and proxy transcoding."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class AudioExtractionConfig(BaseModel):
    sample_rate: int = 16000  # 16kHz optimal for Whisper, AssemblyAI, Silero VAD
    channels: int = 1         # Mono
    format: str = "wav"
    target_lufs: Optional[float] = -14.0  # Normalized broadcast loudness


class ProxyTranscodeConfig(BaseModel):
    width: int = 1280
    height: int = 720
    fps: int = 30
    video_bitrate: str = "1200k"
    audio_bitrate: str = "128k"
    preset: str = "fast"


class WaveformPoint(BaseModel):
    time_s: float
    peak: float  # Normalized 0.0 to 1.0
    rms: float   # Normalized 0.0 to 1.0


class WaveformData(BaseModel):
    duration_s: float
    bucket_interval_s: float
    points: List[WaveformPoint] = Field(default_factory=list)


class PrepResult(BaseModel):
    source_path: str
    audio_wav_path: str
    proxy_video_path: Optional[str] = None
    waveform_json_path: Optional[str] = None
    thumbnails_dir: Optional[str] = None
    duration_s: float
    audio_sample_rate: int
    audio_channels: int
