"""Lossless segmentation engine for parallelizing long stream VOD processing."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List

from .models import StreamChunk
from .inspector import MediaInspector


class SegmenterError(Exception):
    pass


class VideoSegmenter:
    """Splits media into lossless chunks using FFmpeg segment muxer."""

    def __init__(self, ffmpeg_bin: str = "ffmpeg", inspector: MediaInspector | None = None):
        self.ffmpeg_bin = ffmpeg_bin
        self.inspector = inspector or MediaInspector()

    def segment_file(
        self,
        video_path: str | Path,
        output_dir: str | Path,
        segment_time_seconds: int = 1800,  # 30 minutes default per blueprint
    ) -> List[StreamChunk]:
        """Segments video losslessly using ffmpeg -f segment -segment_time X -c copy."""
        vpath = Path(video_path)
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        if not vpath.exists():
            raise SegmenterError(f"Video file not found: {video_path}")

        pattern = str(out_path / f"{vpath.stem}_chunk_%04d{vpath.suffix}")
        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-i", str(vpath),
            "-f", "segment",
            "-segment_time", str(segment_time_seconds),
            "-segment_time_delta", "0.5",
            "-reset_timestamps", "1",
            "-c", "copy",
            pattern,
        ]

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise SegmenterError(f"FFmpeg segmentation failed: {e.stderr}") from e

        # Gather generated chunks
        chunks: List[StreamChunk] = []
        generated_files = sorted(out_path.glob(f"{vpath.stem}_chunk_*{vpath.suffix}"))

        accumulated_time = 0.0
        for idx, file_path in enumerate(generated_files):
            try:
                meta = self.inspector.inspect(file_path)
                dur = meta.duration_seconds
            except Exception:
                dur = float(segment_time_seconds)

            chunks.append(
                StreamChunk(
                    index=idx,
                    file_path=str(file_path.resolve()),
                    start_time_s=accumulated_time,
                    duration_s=dur,
                    size_bytes=file_path.stat().st_size,
                )
            )
            accumulated_time += dur

        return chunks
