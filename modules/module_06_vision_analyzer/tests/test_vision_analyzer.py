"""Tests for Module 6: Scene detection, facecam tracking, and camera deadband smoothing."""
import subprocess
import pytest
from pathlib import Path

from modules.module_06_vision_analyzer.models import (
    BoundingBox,
    LayoutMode,
    SceneCut,
)
from modules.module_06_vision_analyzer.facecam_tracker import (
    DeadbandCameraSmoother,
    FacecamTracker,
)
from modules.module_06_vision_analyzer.scene_detector import SceneDetector


@pytest.fixture(scope="session")
def cut_video(tmp_path_factory) -> Path:
    """Generates a small 2-second video with an abrupt scene cut from black to white at t=1s."""
    tmp_dir = tmp_path_factory.mktemp("scene_fixtures")
    video_path = tmp_dir / "scene_cut.mp4"

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=640x360:d=1",
        "-f", "lavfi", "-i", "color=c=white:s=640x360:d=1",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[outv]",
        "-map", "[outv]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(video_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return video_path


def test_deadband_smoothing_ignores_micro_jitter():
    smoother = DeadbandCameraSmoother(frame_width=1920, frame_height=1080, deadband_ratio=0.25)
    # Deadband X = 1920 * 0.25 / 2 = 240 pixels

    # Initial position
    cx, cy = smoother.update(1000.0, 500.0)
    assert cx == 1000.0
    assert cy == 500.0

    # Small jitter within 240px: 1000 -> 1050 (+50px)
    cx2, cy2 = smoother.update(1050.0, 510.0)
    # Center should remain exactly unchanged
    assert cx2 == 1000.0
    assert cy2 == 500.0

    # Another small jitter: 1000 -> 960 (-40px)
    cx3, cy3 = smoother.update(960.0, 490.0)
    assert cx3 == 1000.0
    assert cy3 == 500.0


def test_deadband_smoothing_moves_on_large_shift():
    smoother = DeadbandCameraSmoother(frame_width=1920, frame_height=1080, deadband_ratio=0.25, easing_factor=0.5)
    # Initial
    smoother.update(1000.0, 500.0)

    # Large shift outside deadband: +500px -> 1500px (> 240px deadband)
    cx, cy = smoother.update(1500.0, 500.0)
    # Center must move towards target
    assert cx > 1000.0
    assert cx < 1500.0


def test_facecam_tracker_scene_cut_reset():
    tracker = FacecamTracker(frame_width=1920, frame_height=1080)

    # Streamer is at top right (1600, 200), then at t=2.0s OBS switches scenes to bottom left (200, 800)
    raw = [
        (0.0, BoundingBox(x=1500, y=100, width=200, height=200), 0.9),
        (1.0, BoundingBox(x=1500, y=100, width=200, height=200), 0.9),
        (2.0, BoundingBox(x=100, y=700, width=200, height=200), 0.9),  # New scene
    ]
    scene_cuts = [SceneCut(timestamp_s=1.95, score=0.8, scene_index=1)]

    points = tracker.smooth_face_tracks(raw, scene_cuts=scene_cuts)
    assert len(points) == 3

    # On scene cut, point at t=2.0s should immediately snap to the new box center (200, 800)
    assert points[2].smoothed_center_x == 200.0
    assert points[2].smoothed_center_y == 800.0


def test_layout_classification():
    tracker = FacecamTracker(frame_width=1920, frame_height=1080)

    # 1. Corner facecam taking < 10% of frame -> SPLIT_SCREEN
    corner_box = BoundingBox(x=1500, y=100, width=320, height=240)
    points = tracker.smooth_face_tracks([(0.0, corner_box, 0.9)])
    layout, rep_box = tracker.detect_stream_layout(points)
    assert layout == LayoutMode.SPLIT_SCREEN
    assert rep_box is not None

    # 2. Large facecam taking > 25% of frame -> FULL_CAM
    large_box = BoundingBox(x=400, y=100, width=1200, height=800)
    points_large = tracker.smooth_face_tracks([(0.0, large_box, 0.9)])
    layout_large, _ = tracker.detect_stream_layout(points_large)
    assert layout_large == LayoutMode.FULL_CAM


def test_scene_detector(cut_video: Path):
    detector = SceneDetector(threshold=0.3)
    cuts = detector.detect_scenes(cut_video)
    # Should detect the cut around t=1.0s
    assert len(cuts) >= 1
    assert abs(cuts[0].timestamp_s - 1.0) < 0.2
