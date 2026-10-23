"""Data models for render specs and video composition."""
from __future__ import annotations

from enum import Enum
from typing import Optional, List, Dict, Tuple
from pydantic import BaseModel, Field


class OutputAspect(str, Enum):
    VERTICAL_9_16 = "9:16"
    SQUARE_1_1 = "1:1"
    HORIZONTAL_16_9 = "16:9"


class RenderLayout(str, Enum):
    SPLIT = "split"        # Facecam top, gameplay bottom
    CROP = "crop"          # Centered facecam/action crop
    FIT = "fit"            # Letterbox with blurred background


class CaptionStyle(str, Enum):
    BOLD_POP = "bold_pop"            # Bold font with word-level scale pop
    WORD_HIGHLIGHT = "word_highlight"  # Active spoken word highlighted in bright yellow
    CLEAN = "clean"                  # Minimalist white with black border


class CaptionConfig(BaseModel):
    enabled: bool = True
    style: CaptionStyle = CaptionStyle.WORD_HIGHLIGHT
    # Defaults follow short-form norms: big bold 2-3 word captions with a heavy outline, placed above the
    # bottom ~20% that TikTok/Shorts/Reels cover with their UI.
    font_name: str = "Arial Black"
    font_size: int = 90                  # px on the 1080x1920 canvas
    bold: bool = True
    uppercase: bool = False
    words_per_group: int = 3
    outline_px: int = 6
    shadow_px: int = 2
    primary_color: str = "&H00FFFFFF"    # White (&HAABBGGRR)
    highlight_color: str = "&H0000FFFF"  # Yellow active word
    outline_color: str = "&H00000000"    # Black outline
    position_percent_y: float = 0.68     # caption baseline 68% down the screen (platform safe zone)


class AudioConfig(BaseModel):
    normalize: bool = True               # EBU R128 loudnorm (platform norm is about -14 LUFS integrated)
    normalize_lufs: float = -14.0
    true_peak_db: float = -1.0
    mute_music: bool = False


class BrandConfig(BaseModel):
    watermark: bool = False
    logo_path: Optional[str] = None


class RenderSpec(BaseModel):
    version: int = 3
    source_media_path: str
    in_s: float
    out_s: float
    aspect: OutputAspect = OutputAspect.VERTICAL_9_16
    layout: RenderLayout = RenderLayout.SPLIT
    face_region: Optional[Tuple[int, int, int, int]] = (1500, 50, 350, 350)  # [x, y, w, h]
    game_region: Optional[Tuple[int, int, int, int]] = (0, 0, 1920, 1080)   # [x, y, w, h]
    captions: CaptionConfig = Field(default_factory=CaptionConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    brand: BrandConfig = Field(default_factory=BrandConfig)
    # Face-tracked reframe for CROP layout: [(t relative to in_s, crop left x in source px)]; None = centre crop
    crop_path: Optional[List[Tuple[float, float]]] = None
    video_crf: int = 18                  # x264 quality (lower = better; 18 is visually lossless for shorts)
    max_fps: int = 60                    # keep source frame rate up to this cap

    @property
    def duration_s(self) -> float:
        return max(0.1, self.out_s - self.in_s)


class RenderOutput(BaseModel):
    output_path: str
    duration_s: float
    width: int
    height: int
    file_size_bytes: int
