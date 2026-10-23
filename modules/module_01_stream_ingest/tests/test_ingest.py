"""Tests for Module 1: Stream Ingestion & Inspection."""
import subprocess
from pathlib import Path
import pytest

from modules.module_01_stream_ingest.models import (
    StreamPlatform,
    MediaType,
)
from modules.module_01_stream_ingest.inspector import (
    MediaInspector,
    compute_fast_sha256,
)
from modules.module_01_stream_ingest.downloader import detect_platform_and_type
from modules.module_01_stream_ingest.segmenter import VideoSegmenter


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory) -> Path:
    """Generates a small 3-second test MP4 file with video and audio using FFmpeg."""
    tmp_dir = tmp_path_factory.mktemp("media_fixtures")
    video_path = tmp_dir / "sample_stream.mp4"

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=3:size=1280x720:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=3",
        "-c:v", "libx264", "-g", "30", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(video_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return video_path


def test_url_detection():
    # Twitch Clip
    p, m = detect_platform_and_type("https://www.twitch.tv/shroud/clip/ReliableGiftedWombat")
    assert p == StreamPlatform.TWITCH
    assert m == MediaType.CLIP

    # Twitch VOD
    p, m = detect_platform_and_type("https://www.twitch.tv/videos/123456789")
    assert p == StreamPlatform.TWITCH
    assert m == MediaType.VOD

    # YouTube Short
    p, m = detect_platform_and_type("https://www.youtube.com/shorts/abc123xyz")
    assert p == StreamPlatform.YOUTUBE
    assert m == MediaType.CLIP

    # Kick Livestream
    p, m = detect_platform_and_type("https://kick.com/xqc")
    assert p == StreamPlatform.KICK
    assert m == MediaType.LIVESTREAM


def test_media_inspector(sample_video: Path):
    inspector = MediaInspector()
    meta = inspector.inspect(sample_video)

    assert meta.has_video is True
    assert meta.has_audio is True
    assert meta.duration_seconds >= 2.9
    assert meta.primary_video is not None
    assert meta.primary_video.width == 1280
    assert meta.primary_video.height == 720
    assert meta.primary_video.fps == 30.0
    assert meta.primary_audio is not None
    assert meta.primary_audio.codec_name == "aac"
    assert meta.sha256_hash is not None


def test_fast_sha256(sample_video: Path):
    sha = compute_fast_sha256(sample_video)
    assert len(sha) == 64
    # Check repeatability
    assert compute_fast_sha256(sample_video) == sha


def test_video_segmentation(sample_video: Path, tmp_path: Path):
    out_dir = tmp_path / "chunks"
    segmenter = VideoSegmenter()
    # Segment into 1-second chunks
    chunks = segmenter.segment_file(sample_video, out_dir, segment_time_seconds=1)

    assert len(chunks) >= 2
    assert chunks[0].index == 0
    assert Path(chunks[0].file_path).exists()
    assert chunks[0].duration_s > 0


def test_rotation_metadata_gives_display_size(tmp_path: Path):
    """Phone footage stored as landscape + 90° rotation flag must be reported as vertical."""
    raw = tmp_path / "raw.mp4"
    rotated = tmp_path / "rotated.mov"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=320x180:rate=10",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(raw)], check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-display_rotation:v:0", "90", "-i", str(raw), "-c", "copy", str(rotated)],
                   check=True, capture_output=True)

    meta = MediaInspector().inspect(rotated)
    v = meta.primary_video
    assert abs(v.rotation) == 90
    assert (v.width, v.height) == (320, 180)
    assert (v.display_width, v.display_height) == (180, 320)
    assert meta.is_vertical is True
