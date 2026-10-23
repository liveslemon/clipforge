"""Tests for face-tracked reframing and the YuNet detector wrapper."""
import subprocess
from pathlib import Path

import pytest

from modules.module_06_vision_analyzer.models import BoundingBox, SceneCut
from modules.module_06_vision_analyzer.reframe import build_crop_path, sendcmd_script


def _face(cx, size=200, y=300):
    return BoundingBox(x=int(cx - size / 2), y=y, width=size, height=size)


def test_crop_path_follows_face_and_stays_in_frame():
    # face walks from the left third to the right third of a 1920x1080 frame over 10 s
    dets = [(t / 4, _face(400 + (1100 * t / 40)), 0.9) for t in range(41)]
    path = build_crop_path(dets, 1920, 1080, in_s=0.0, out_s=10.0)
    crop_w = 1080 * 9 / 16
    xs = [x for _, x in path]
    assert path[0][0] == 0.0 and abs(path[-1][0] - 10.0) < 0.11
    assert all(0 <= x <= 1920 - crop_w for x in xs)
    assert xs[-1] > xs[0] + 600                      # camera followed the face right
    assert max(abs(b - a) for a, b in zip(xs, xs[1:])) < 60  # no jumps: smooth pan


def test_deadband_ignores_jitter():
    dets = [(t / 4, _face(960 + (15 if t % 2 else -15)), 0.9) for t in range(40)]
    xs = [x for _, x in build_crop_path(dets, 1920, 1080, 0.0, 9.0)]
    assert max(xs) - min(xs) < 1.0


def test_scene_cut_snaps_instead_of_panning():
    dets = [(t / 4, _face(400 if t < 20 else 1500), 0.9) for t in range(40)]
    path = build_crop_path(dets, 1920, 1080, 0.0, 9.0, scene_cuts=[SceneCut(timestamp_s=5.0, score=0.9, scene_index=1)])
    before = [x for t, x in path if 4.6 < t < 4.95][-1]
    after = [x for t, x in path if 5.0 <= t < 5.2][0]
    assert after - before > 300  # jumped at the cut


def test_vertical_source_needs_no_reframe():
    assert build_crop_path([(0.0, _face(500), 0.9)], 1080, 1920, 0.0, 5.0) is None


def test_sendcmd_script_format():
    assert sendcmd_script([(0.0, 10.0), (0.1, 12.5)]) == "0.000 crop x 10.0;\n0.100 crop x 12.5;\n"


def test_yunet_finds_no_face_in_blank_video(tmp_path: Path):
    cv2 = pytest.importorskip("cv2")
    if not hasattr(cv2, "FaceDetectorYN"):
        pytest.skip("OpenCV without YuNet")
    from modules.module_06_vision_analyzer.face_detector import YuNetFaceDetector, YUNET_FILE
    from modules.config import MODELS_DIR
    if not (MODELS_DIR / YUNET_FILE).exists():
        pytest.skip("YuNet model not downloaded")
    video = tmp_path / "blank.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=gray:s=640x360:d=1", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(video)], check=True, capture_output=True)
    assert YuNetFaceDetector().track_video(video, sample_fps=4) == []
