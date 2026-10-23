"""Stream Ingestion & Inspection Module for ClipForge."""

from .models import (
    StreamPlatform,
    MediaType,
    VideoStreamInfo,
    AudioStreamInfo,
    MediaMetadata,
    StreamChunk,
)
from .inspector import MediaInspector, MediaInspectorError, compute_fast_sha256
from .downloader import (
    StreamDownloader,
    DownloaderError,
    detect_platform_and_type,
)
from .segmenter import VideoSegmenter, SegmenterError

__all__ = [
    "StreamPlatform",
    "MediaType",
    "VideoStreamInfo",
    "AudioStreamInfo",
    "MediaMetadata",
    "StreamChunk",
    "MediaInspector",
    "MediaInspectorError",
    "compute_fast_sha256",
    "StreamDownloader",
    "DownloaderError",
    "detect_platform_and_type",
    "VideoSegmenter",
    "SegmenterError",
]
