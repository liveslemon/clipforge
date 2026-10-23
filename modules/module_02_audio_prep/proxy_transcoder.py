"""Proxy transcoder for lightweight web preview and multi-pass media preparation."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from .models import (
    AudioExtractionConfig,
    ProxyTranscodeConfig,
    PrepResult,
)
from .audio_extractor import AudioExtractor
from .waveform_generator import WaveformGenerator


class TranscoderError(Exception):
    pass


class MediaPreprocessor:
    """Orchestrates audio extraction, waveform generation, and 720p proxy generation."""

    def __init__(
        self,
        ffmpeg_bin: str = "ffmpeg",
        audio_extractor: Optional[AudioExtractor] = None,
        waveform_generator: Optional[WaveformGenerator] = None,
    ):
        self.ffmpeg_bin = ffmpeg_bin
        self.audio_extractor = audio_extractor or AudioExtractor(ffmpeg_bin=ffmpeg_bin)
        self.waveform_generator = waveform_generator or WaveformGenerator()

    def generate_proxy_video(
        self,
        media_path: str | Path,
        output_proxy_path: str | Path,
        config: Optional[ProxyTranscodeConfig] = None,
    ) -> Path:
        """Transcodes a lightweight 720p CFR MP4 proxy for smooth browser preview scrubbing."""
        cfg = config or ProxyTranscodeConfig()
        in_p = Path(media_path)
        out_p = Path(output_proxy_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        # Scale preserving aspect ratio, clamp max height to 720, force CFR
        scale_filter = f"scale=-2:min({cfg.height}\\,ih)"
        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-i", str(in_p),
            "-map", "0:v:0",
            "-map", "0:a:0?",  # first track only: iPhones add an undecodable spatial track (apple_apac)
            "-vf", scale_filter,
            "-r", str(cfg.fps),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", cfg.preset,
            "-b:v", cfg.video_bitrate,
            "-c:a", "aac",
            "-b:a", cfg.audio_bitrate,
            "-movflags", "+faststart",  # Enable immediate web streaming
            str(out_p),
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise TranscoderError(f"FFmpeg proxy transcode failed: {e.stderr}") from e

        return out_p

    def extract_thumbnails(
        self,
        media_path: str | Path,
        output_dir: str | Path,
        fps: float = 0.5,  # 1 frame every 2 seconds
        height: int = 160,
    ) -> Path:
        """Extracts low-resolution thumbnail frames for timeline scrubbing."""
        in_p = Path(media_path)
        out_p = Path(output_dir)
        out_p.mkdir(parents=True, exist_ok=True)

        pattern = str(out_p / "thumb_%05d.jpg")
        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-i", str(in_p),
            "-vf", f"fps={fps},scale=-1:{height}",
            "-q:v", "5",
            pattern,
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise TranscoderError(f"FFmpeg thumbnail extraction failed: {e.stderr}") from e

        return out_p

    def process_all(
        self,
        media_path: str | Path,
        output_dir: str | Path,
        extract_thumbnails_flag: bool = True,
    ) -> PrepResult:
        """One-stop media preparation: extracts 16kHz WAV, generates 720p proxy, thumbnails, and waveform."""
        in_p = Path(media_path)
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        stem = in_p.stem

        wav_path = out_dir / f"{stem}_16k_mono.wav"
        proxy_path = out_dir / f"{stem}_proxy_720p.mp4"
        waveform_json = out_dir / f"{stem}_waveform.json"
        thumbs_dir = out_dir / "thumbnails" if extract_thumbnails_flag else None

        # 1. Extract 16kHz audio
        self.audio_extractor.extract_stt_audio(in_p, wav_path)

        # 2. Generate waveform JSON
        wf_data = self.waveform_generator.generate(wav_path, waveform_json)

        # 3. Generate 720p proxy video
        self.generate_proxy_video(in_p, proxy_path)

        # 4. Extract thumbnails
        if extract_thumbnails_flag and thumbs_dir:
            self.extract_thumbnails(in_p, thumbs_dir, fps=0.5)

        return PrepResult(
            source_path=str(in_p.resolve()),
            audio_wav_path=str(wav_path.resolve()),
            proxy_video_path=str(proxy_path.resolve()),
            waveform_json_path=str(waveform_json.resolve()),
            thumbnails_dir=str(thumbs_dir.resolve()) if thumbs_dir else None,
            duration_s=wf_data.duration_s,
            audio_sample_rate=16000,
            audio_channels=1,
        )
