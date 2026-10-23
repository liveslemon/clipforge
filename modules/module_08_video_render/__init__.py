"""Render Spec Engine & Video Compositor Module for ClipForge."""

from .models import (
    OutputAspect,
    RenderLayout,
    CaptionStyle,
    CaptionConfig,
    AudioConfig,
    BrandConfig,
    RenderSpec,
    RenderOutput,
)
from .ass_generator import (
    ASSSubtitleGenerator,
    sanitize_ass_text,
    ms_to_ass_time,
)
from .ffmpeg_compositor import VideoCompositor, RenderError

__all__ = [
    "OutputAspect",
    "RenderLayout",
    "CaptionStyle",
    "CaptionConfig",
    "AudioConfig",
    "BrandConfig",
    "RenderSpec",
    "RenderOutput",
    "ASSSubtitleGenerator",
    "sanitize_ass_text",
    "ms_to_ass_time",
    "VideoCompositor",
    "RenderError",
]
