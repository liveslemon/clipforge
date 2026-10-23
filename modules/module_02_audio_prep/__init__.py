"""Audio Preparation & Proxy Transcoding Module for ClipForge."""

from .models import (
    AudioExtractionConfig,
    ProxyTranscodeConfig,
    WaveformPoint,
    WaveformData,
    PrepResult,
)
from .audio_extractor import AudioExtractor, AudioExtractorError
from .waveform_generator import WaveformGenerator
from .proxy_transcoder import MediaPreprocessor, TranscoderError

__all__ = [
    "AudioExtractionConfig",
    "ProxyTranscodeConfig",
    "WaveformPoint",
    "WaveformData",
    "PrepResult",
    "AudioExtractor",
    "AudioExtractorError",
    "WaveformGenerator",
    "MediaPreprocessor",
    "TranscoderError",
]
