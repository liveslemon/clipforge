"""Speech-to-Text & Word Alignment Module for ClipForge."""

from .models import (
    TimedWord,
    TranscriptSegment,
    Transcript,
    SpeechPause,
)
from .protocol import TranscriptionProvider
from .providers.mock_provider import MockTranscriptionProvider
from .providers.assemblyai_provider import AssemblyAIProvider, AssemblyAIProviderError
from .providers.faster_whisper_provider import FasterWhisperProvider, FasterWhisperProviderError
from .providers.local_whisper_provider import LocalWhisperProvider, LocalWhisperProviderError
from .segmenter_aligner import TranscriptAligner
from .caption_proofreader import proofread, apply_corrections, Correction
from .exporters import SubtitleExporter, ms_to_srt_time, ms_to_vtt_time

__all__ = [
    "TimedWord",
    "TranscriptSegment",
    "Transcript",
    "SpeechPause",
    "TranscriptionProvider",
    "MockTranscriptionProvider",
    "AssemblyAIProvider",
    "AssemblyAIProviderError",
    "FasterWhisperProvider",
    "FasterWhisperProviderError",
    "LocalWhisperProvider",
    "LocalWhisperProviderError",
    "TranscriptAligner",
    "proofread",
    "apply_corrections",
    "Correction",
    "SubtitleExporter",
    "ms_to_srt_time",
    "ms_to_vtt_time",
]
