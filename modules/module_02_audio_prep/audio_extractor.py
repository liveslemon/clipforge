"""Audio extractor extracting 16kHz mono WAV for STT and computing audio loudness."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from .models import AudioExtractionConfig


class AudioExtractorError(Exception):
    pass


class AudioExtractor:
    """Extracts 16kHz mono audio from media files using FFmpeg."""

    def __init__(self, ffmpeg_bin: str = "ffmpeg"):
        self.ffmpeg_bin = ffmpeg_bin

    def extract_stt_audio(
        self,
        media_path: str | Path,
        output_wav_path: str | Path,
        config: Optional[AudioExtractionConfig] = None,
    ) -> Path:
        """Extracts a 16kHz 16-bit mono WAV file optimal for Speech-to-Text and VAD."""
        cfg = config or AudioExtractionConfig()
        in_p = Path(media_path)
        out_p = Path(output_wav_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        if not in_p.exists():
            raise AudioExtractorError(f"Media file not found: {media_path}")

        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-i", str(in_p),
            "-map", "0:a:0",  # first track only: iPhones add an undecodable spatial track (apple_apac)
            "-vn",  # No video
            "-acodec", "pcm_s16le",
            "-ar", str(cfg.sample_rate),
            "-ac", str(cfg.channels),
            str(out_p),
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            if self._has_audio_stream(in_p):
                raise AudioExtractorError(f"FFmpeg audio extraction failed: {e.stderr}") from e
            self._write_silence(in_p, out_p, cfg)

        return out_p

    def _has_audio_stream(self, media_path: Path) -> bool:
        ffprobe_bin = self.ffmpeg_bin.replace("ffmpeg", "ffprobe")
        res = subprocess.run(
            [ffprobe_bin, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(media_path)],
            capture_output=True, text=True,
        )
        return bool(res.stdout.strip())

    def _write_silence(self, media_path: Path, out_p: Path, cfg: AudioExtractionConfig) -> None:
        """Silent-video fallback: emit silence matching the video duration so downstream analysis still runs."""
        ffprobe_bin = self.ffmpeg_bin.replace("ffmpeg", "ffprobe")
        res = subprocess.run(
            [ffprobe_bin, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(media_path)],
            capture_output=True, text=True,
        )
        try:
            duration = float(res.stdout.strip())
        except ValueError as e:
            raise AudioExtractorError(f"Media has no audio stream and no readable duration: {media_path}") from e

        layout = "mono" if cfg.channels == 1 else "stereo"
        cmd = [
            self.ffmpeg_bin, "-y",
            "-f", "lavfi", "-i", f"anullsrc=r={cfg.sample_rate}:cl={layout}",
            "-t", f"{duration:.3f}",
            "-acodec", "pcm_s16le",
            str(out_p),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise AudioExtractorError(f"FFmpeg silent audio generation failed: {e.stderr}") from e
