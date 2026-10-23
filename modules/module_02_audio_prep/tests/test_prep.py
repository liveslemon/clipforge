"""Tests for Module 2: Audio extraction, waveform generation, and proxy transcoding."""
import wave
import subprocess
from pathlib import Path
import pytest

from modules.module_02_audio_prep.audio_extractor import AudioExtractor
from modules.module_02_audio_prep.waveform_generator import WaveformGenerator
from modules.module_02_audio_prep.proxy_transcoder import MediaPreprocessor
from modules.module_01_stream_ingest.inspector import MediaInspector


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory) -> Path:
    """Generates a small 3-second test MP4 video with a 440Hz sine wave audio track."""
    tmp_dir = tmp_path_factory.mktemp("prep_fixtures")
    video_path = tmp_dir / "sample_prep_video.mp4"

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=3:size=1920x1080:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(video_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return video_path


def test_audio_extraction(sample_video: Path, tmp_path: Path):
    out_wav = tmp_path / "extracted_16k.wav"
    extractor = AudioExtractor()
    extractor.extract_stt_audio(sample_video, out_wav)

    assert out_wav.exists()
    assert out_wav.stat().st_size > 0

    with wave.open(str(out_wav), "rb") as wf:
        assert wf.getframerate() == 16000
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2  # 16-bit PCM


def test_waveform_generation(sample_video: Path, tmp_path: Path):
    out_wav = tmp_path / "waveform_source.wav"
    out_json = tmp_path / "waveform.json"

    extractor = AudioExtractor()
    extractor.extract_stt_audio(sample_video, out_wav)

    generator = WaveformGenerator(bucket_interval_s=0.1)
    waveform = generator.generate(out_wav, out_json)

    assert out_json.exists()
    assert waveform.duration_s >= 2.9
    assert len(waveform.points) > 20
    # Every point must be bounded in [0.0, 1.0]
    for p in waveform.points:
        assert 0.0 <= p.peak <= 1.0
        assert 0.0 <= p.rms <= 1.0


def test_proxy_transcoding(sample_video: Path, tmp_path: Path):
    out_proxy = tmp_path / "proxy_720p.mp4"
    preprocessor = MediaPreprocessor()
    preprocessor.generate_proxy_video(sample_video, out_proxy)

    assert out_proxy.exists()
    inspector = MediaInspector()
    meta = inspector.inspect(out_proxy)

    assert meta.primary_video is not None
    assert meta.primary_video.height == 720
    assert meta.primary_video.width == 1280
    assert meta.has_audio is True


def test_process_all_pipeline(sample_video: Path, tmp_path: Path):
    out_dir = tmp_path / "prep_pipeline_output"
    preprocessor = MediaPreprocessor()
    result = preprocessor.process_all(sample_video, out_dir, extract_thumbnails_flag=True)

    assert Path(result.audio_wav_path).exists()
    assert Path(result.proxy_video_path).exists()
    assert Path(result.waveform_json_path).exists()
    assert result.thumbnails_dir is not None
    assert Path(result.thumbnails_dir).exists()
    assert len(list(Path(result.thumbnails_dir).glob("*.jpg"))) > 0


def test_audio_extraction_falls_back_to_silence_for_silent_video(tmp_path: Path):
    """A video with no audio track yields a silent 16 kHz WAV of the same length instead of crashing."""
    silent_video = tmp_path / "no_audio.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=15",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent_video)], check=True, capture_output=True)

    wav_path = AudioExtractor().extract_stt_audio(silent_video, tmp_path / "out.wav")

    with wave.open(str(wav_path), "rb") as wf:
        assert wf.getframerate() == 16000
        assert wf.getnchannels() == 1
        assert abs(wf.getnframes() / 16000 - 2.0) < 0.1
