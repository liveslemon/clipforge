"""Tests for Module 8: Render spec engine and FFmpeg video compositor."""
import subprocess
import pytest
from pathlib import Path

from modules.module_08_video_render.models import (
    RenderSpec,
    RenderLayout,
    CaptionStyle,
    CaptionConfig,
)
from modules.module_08_video_render.ass_generator import (
    ASSSubtitleGenerator,
    sanitize_ass_text,
    ms_to_ass_time,
)
from modules.module_08_video_render.ffmpeg_compositor import VideoCompositor
from modules.module_03_transcription.models import TimedWord
from modules.module_01_stream_ingest.inspector import MediaInspector


@pytest.fixture(scope="session")
def render_fixture_video(tmp_path_factory) -> Path:
    """Generates a 3-second 1920x1080 test video with audio."""
    tmp_dir = tmp_path_factory.mktemp("render_fixtures")
    video_path = tmp_dir / "input_1080p.mp4"

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=3:size=1920x1080:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(video_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return video_path


def test_sanitize_ass_text():
    raw = "Normal text {override_tag} with {braces}"
    sanitized = sanitize_ass_text(raw)
    assert "{" not in sanitized
    assert "}" not in sanitized
    assert "(" in sanitized


def test_ass_time_formatting():
    assert ms_to_ass_time(0) == "0:00:00.00"
    assert ms_to_ass_time(15420) == "0:00:15.42"
    assert ms_to_ass_time(3665120) == "1:01:05.12"


def test_ass_generator(tmp_path: Path):
    gen = ASSSubtitleGenerator(canvas_width=1080, canvas_height=1920)
    words = [
        TimedWord(word="Hello", start_ms=200, end_ms=600),
        TimedWord(word="world", start_ms=650, end_ms=1100),
        TimedWord(word="stream", start_ms=1150, end_ms=1600),
    ]
    cfg = CaptionConfig(style=CaptionStyle.WORD_HIGHLIGHT)
    ass_file = tmp_path / "test.ass"
    content = gen.generate_ass(words, clip_in_s=0.0, clip_out_s=2.0, config=cfg, output_file=ass_file)

    assert ass_file.exists()
    assert "[Script Info]" in content
    assert "Dialogue:" in content
    assert "Hello" in content
    assert "\\c" in content  # Contains color highlight override tag


def test_split_screen_render(render_fixture_video: Path, tmp_path: Path):
    out_mp4 = tmp_path / "vertical_split.mp4"
    words = [
        TimedWord(word="Test", start_ms=100, end_ms=500),
        TimedWord(word="split", start_ms=550, end_ms=1000),
        TimedWord(word="render", start_ms=1050, end_ms=1500),
    ]

    spec = RenderSpec(
        source_media_path=str(render_fixture_video),
        in_s=0.5,
        out_s=2.0,
        layout=RenderLayout.SPLIT,
        face_region=(1500, 50, 350, 350),
        game_region=(0, 0, 1920, 1080),
    )
    spec.captions.enabled = True
    spec.captions.style = CaptionStyle.WORD_HIGHLIGHT

    compositor = VideoCompositor()
    result = compositor.render(spec, out_mp4, words=words)

    assert out_mp4.exists()
    assert result.file_size_bytes > 0

    # Inspect rendered media
    inspector = MediaInspector()
    meta = inspector.inspect(out_mp4)

    assert meta.primary_video is not None
    assert meta.primary_video.width == 1080
    assert meta.primary_video.height == 1920  # Exactly 9:16 vertical!
    assert abs(meta.duration_seconds - 1.5) < 0.2  # 2.0 - 0.5 = 1.5s duration
    assert meta.has_audio is True


def test_fit_and_crop_renders(render_fixture_video: Path, tmp_path: Path):
    compositor = VideoCompositor()
    inspector = MediaInspector()

    # 1. Fit layout
    out_fit = tmp_path / "vertical_fit.mp4"
    spec_fit = RenderSpec(
        source_media_path=str(render_fixture_video),
        in_s=0.0,
        out_s=1.0,
        layout=RenderLayout.FIT,
    )
    spec_fit.captions.enabled = False
    compositor.render(spec_fit, out_fit)

    meta_fit = inspector.inspect(out_fit)
    assert meta_fit.primary_video.width == 1080
    assert meta_fit.primary_video.height == 1920

    # 2. Crop layout
    out_crop = tmp_path / "vertical_crop.mp4"
    spec_crop = RenderSpec(
        source_media_path=str(render_fixture_video),
        in_s=0.0,
        out_s=1.0,
        layout=RenderLayout.CROP,
    )
    spec_crop.captions.enabled = False
    compositor.render(spec_crop, out_crop)

    meta_crop = inspector.inspect(out_crop)
    assert meta_crop.primary_video.width == 1080
    assert meta_crop.primary_video.height == 1920


@pytest.mark.parametrize("size", ["640x360", "360x640", "360x900"])
def test_regions_are_clamped_to_any_source_size(size: str, tmp_path: Path):
    """1920x1080-authored regions must still render on 720p, portrait and extra-tall phone sources."""
    src = tmp_path / f"src_{size}.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=duration=1:size={size}:rate=15",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)], check=True, capture_output=True)
    compositor = VideoCompositor()
    for layout in (RenderLayout.SPLIT, RenderLayout.CROP):
        spec = RenderSpec(source_media_path=str(src), in_s=0.0, out_s=1.0, layout=layout,
                          face_region=(1500, 50, 350, 350), game_region=(0, 0, 1920, 1080))
        spec.captions.enabled = False
        out = tmp_path / f"out_{size}_{layout.value}.mp4"
        compositor.render(spec, out)

        meta = MediaInspector().inspect(out)
        assert (meta.primary_video.width, meta.primary_video.height) == (1080, 1920)


def test_render_uses_only_first_audio_track(tmp_path: Path):
    """iPhone files carry extra audio tracks (e.g. undecodable spatial audio); only the first is rendered."""
    src = tmp_path / "multi_audio.mov"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=640x360:rate=15",
                    "-f", "lavfi", "-i", "sine=f=440:d=1", "-f", "lavfi", "-i", "sine=f=880:d=1",
                    "-map", "0", "-map", "1", "-map", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(src)], check=True, capture_output=True)
    spec = RenderSpec(source_media_path=str(src), in_s=0.0, out_s=1.0, layout=RenderLayout.FIT)
    spec.captions.enabled = False
    out = tmp_path / "out.mp4"
    VideoCompositor().render(spec, out)

    meta = MediaInspector().inspect(out)
    assert len(meta.audio_streams) == 1


def test_two_pass_loudnorm_hits_platform_target(tmp_path: Path):
    """A quiet source (~-30 LUFS) comes out at -14 LUFS ±1 (two-pass, linear EBU R128)."""
    import re
    src = tmp_path / "quiet.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=6:size=640x360:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=330:duration=6,volume=0.03",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)],
                   check=True, capture_output=True)
    compositor = VideoCompositor()
    if not compositor.has_loudnorm:
        pytest.skip("ffmpeg without loudnorm")
    spec = RenderSpec(source_media_path=str(src), in_s=0.0, out_s=6.0, layout=RenderLayout.FIT)
    spec.captions.enabled = False
    assert "linear=true" in compositor.audio_filter(spec)
    out = tmp_path / "loud.mp4"
    compositor.render(spec, out)
    res = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(out), "-af", "ebur128=framelog=quiet",
                          "-f", "null", "-"], capture_output=True, text=True)
    lufs = float(re.findall(r"I:\s+(-?[0-9.]+) LUFS", res.stderr)[-1])
    assert abs(lufs + 14.0) <= 1.0
