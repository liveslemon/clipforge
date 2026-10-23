"""Audio Signal & Acoustic Feature Extraction Module for ClipForge."""

from .models import (
    AudioSignalPoint,
    AudioSignalsTimeline,
    EnergyScore,
)
from .audio_event_detector import AudioEventDetector, AudioEventDetectorError, ensure_panns_files
from .acoustic_analyzer import (
    AcousticAnalyzer,
    sigmoid,
    estimate_pitch_autocorr,
)

__all__ = [
    "AudioSignalPoint",
    "AudioSignalsTimeline",
    "EnergyScore",
    "AcousticAnalyzer",
    "AudioEventDetector",
    "AudioEventDetectorError",
    "ensure_panns_files",
    "sigmoid",
    "estimate_pitch_autocorr",
]
