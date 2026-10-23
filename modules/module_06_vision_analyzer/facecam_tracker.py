"""Facecam tracking, deadband camera smoothing, and OBS layout auto-detection."""
from __future__ import annotations

from typing import List, Optional, Tuple
from .models import (
    BoundingBox,
    FaceTrackingPoint,
    LayoutMode,
    VisionAnalysisResult,
    SceneCut,
)


class DeadbandCameraSmoother:
    """Implements deadband camera smoothing (Blueprint Section 3.8).

    The camera crop center only moves when the tracked face leaves the inner deadband
    (default 25% of the frame dimensions), preventing micro-jitter and applying easing.
    """

    def __init__(
        self,
        frame_width: int = 1920,
        frame_height: int = 1080,
        deadband_ratio: float = 0.25,  # 25% inner threshold
        easing_factor: float = 0.20,   # Exponential smoothing factor alpha
    ):
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.deadband_x = frame_width * deadband_ratio / 2.0
        self.deadband_y = frame_height * deadband_ratio / 2.0
        self.easing = easing_factor

        self.current_center_x: Optional[float] = None
        self.current_center_y: Optional[float] = None

    def reset(self, initial_center_x: float, initial_center_y: float):
        """Resets deadband tracker (e.g. after a scene cut / OBS scene switch)."""
        self.current_center_x = initial_center_x
        self.current_center_y = initial_center_y

    def update(self, target_x: float, target_y: float) -> Tuple[float, float]:
        """Calculates smoothed camera center given face center target."""
        if self.current_center_x is None or self.current_center_y is None:
            self.reset(target_x, target_y)
            return target_x, target_y

        diff_x = target_x - self.current_center_x
        diff_y = target_y - self.current_center_y

        # Only adjust if target moves outside deadband
        if abs(diff_x) > self.deadband_x:
            pull_x = target_x - (self.deadband_x if diff_x > 0 else -self.deadband_x)
            self.current_center_x += self.easing * (pull_x - self.current_center_x)

        if abs(diff_y) > self.deadband_y:
            pull_y = target_y - (self.deadband_y if diff_y > 0 else -self.deadband_y)
            self.current_center_y += self.easing * (pull_y - self.current_center_y)

        return self.current_center_x, self.current_center_y


class FacecamTracker:
    """Tracks facecam overlay and applies deadband smoothing."""

    def __init__(
        self,
        frame_width: int = 1920,
        frame_height: int = 1080,
    ):
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.smoother = DeadbandCameraSmoother(frame_width, frame_height)

    def smooth_face_tracks(
        self,
        raw_detections: List[Tuple[float, BoundingBox, float]],  # (ts, bbox, confidence)
        scene_cuts: Optional[List[SceneCut]] = None,
    ) -> List[FaceTrackingPoint]:
        """Applies deadband smoothing across a series of face detections,

        resetting on scene transitions.
        """
        cut_times = [c.timestamp_s for c in (scene_cuts or [])]
        points: List[FaceTrackingPoint] = []

        last_ts = 0.0
        for ts, bbox, conf in raw_detections:
            # Check if a scene cut occurred between last_ts and ts
            if any(last_ts < ct <= ts for ct in cut_times):
                self.smoother.reset(bbox.center_x, bbox.center_y)

            sx, sy = self.smoother.update(bbox.center_x, bbox.center_y)
            points.append(
                FaceTrackingPoint(
                    timestamp_s=ts,
                    bbox=bbox,
                    smoothed_center_x=round(sx, 1),
                    smoothed_center_y=round(sy, 1),
                    confidence=conf,
                )
            )
            last_ts = ts

        return points

    def detect_stream_layout(
        self,
        face_points: List[FaceTrackingPoint],
    ) -> Tuple[LayoutMode, Optional[BoundingBox]]:
        """Classifies stream layout:

        - SPLIT_SCREEN: small facecam box (e.g. corner camera taking < 25% of frame)
        - FULL_CAM: facecam takes majority of frame (e.g. Just Chatting podcast)
        - FULL_GAMEPLAY: no facecam detected.
        """
        if not face_points:
            return LayoutMode.FULL_GAMEPLAY, None

        # Average facecam box size
        avg_w = sum(p.bbox.width for p in face_points) / len(face_points)
        avg_h = sum(p.bbox.height for p in face_points) / len(face_points)
        avg_x = sum(p.bbox.x for p in face_points) / len(face_points)
        avg_y = sum(p.bbox.y for p in face_points) / len(face_points)

        frame_area = self.frame_width * self.frame_height
        face_area = avg_w * avg_h
        area_ratio = face_area / float(frame_area)

        representative_box = BoundingBox(
            x=int(avg_x),
            y=int(avg_y),
            width=int(avg_w),
            height=int(avg_h),
        )

        if area_ratio > 0.20:
            return LayoutMode.FULL_CAM, representative_box
        else:
            return LayoutMode.SPLIT_SCREEN, representative_box
