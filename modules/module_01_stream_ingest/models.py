"""Data models for stream ingestion and inspection."""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class StreamPlatform(str, Enum):
    TWITCH = "twitch"
    YOUTUBE = "youtube"
    KICK = "kick"
    DIRECT_URL = "direct_url"
    LOCAL_FILE = "local_file"


class MediaType(str, Enum):
    VOD = "vod"
    CLIP = "clip"
    LIVESTREAM = "livestream"
    RAW_UPLOAD = "raw_upload"


class AudioStreamInfo(BaseModel):
    index: int
    codec_name: str
    sample_rate: int
    channels: int
    bit_rate: Optional[int] = None
    duration: Optional[float] = None


class VideoStreamInfo(BaseModel):
    index: int
    codec_name: str
    width: int
    height: int
    fps: float
    bit_rate: Optional[int] = None
    duration: Optional[float] = None
    is_vfr: bool = False  # Variable Frame Rate flag
    rotation: int = 0  # Display rotation in degrees (phones often record landscape + rotate flag)

    @property
    def display_width(self) -> int:
        return self.height if abs(self.rotation) % 180 == 90 else self.width

    @property
    def display_height(self) -> int:
        return self.width if abs(self.rotation) % 180 == 90 else self.height


class MediaMetadata(BaseModel):
    file_path: Optional[str] = None
    source_url: Optional[str] = None
    platform: StreamPlatform
    media_type: MediaType
    title: Optional[str] = None
    author: Optional[str] = None
    duration_seconds: float
    file_size_bytes: int = 0
    video_streams: List[VideoStreamInfo] = Field(default_factory=list)
    audio_streams: List[AudioStreamInfo] = Field(default_factory=list)
    has_video: bool = True
    has_audio: bool = True
    sha256_hash: Optional[str] = None
    format_name: Optional[str] = None
    raw_probe: Dict[str, Any] = Field(default_factory=dict)

    @property
    def primary_video(self) -> Optional[VideoStreamInfo]:
        return self.video_streams[0] if self.video_streams else None

    @property
    def primary_audio(self) -> Optional[AudioStreamInfo]:
        return self.audio_streams[0] if self.audio_streams else None

    @property
    def is_vertical(self) -> bool:
        if not self.primary_video:
            return False
        return self.primary_video.display_height > self.primary_video.display_width


class StreamChunk(BaseModel):
    index: int
    file_path: str
    start_time_s: float
    duration_s: float
    size_bytes: int
