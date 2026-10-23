"""Data models for visual scene detection, face tracking, and camera deadband smoothing."""
from __future__ import annotations

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class LayoutMode(str, Enum):
    SPLIT_SCREEN = "split"           # Facecam top, gameplay bottom
    CENTER_CROP = "crop_tracked"     # 9:16 vertical crop with face tracking
    FULL_GAMEPLAY = "gameplay"       # Fit gameplay with letterbox/blur
    FULL_CAM = "cam"                 # Facecam fills vertical frame


class BoundingBox(BaseModel):
    x: int
    y: int
    width: int
    height: int

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2.0

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2.0


class FaceTrackingPoint(BaseModel):
    timestamp_s: float
    bbox: BoundingBox
    smoothed_center_x: float
    smoothed_center_y: float
    confidence: float = 1.0


class SceneCut(BaseModel):
    timestamp_s: float
    score: float
    scene_index: int


class VisionAnalysisResult(BaseModel):
    duration_s: float
    scene_cuts: List[SceneCut] = Field(default_factory=list)
    face_tracks: List[FaceTrackingPoint] = Field(default_factory=list)
    suggested_layout: LayoutMode = LayoutMode.SPLIT_SCREEN
    detected_facecam_box: Optional[BoundingBox] = None
