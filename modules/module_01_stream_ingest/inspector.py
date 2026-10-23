"""Media inspector using ffprobe for deep audio/video stream verification."""
from __future__ import annotations

import json
import hashlib
import subprocess
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

from .models import (
    MediaMetadata,
    VideoStreamInfo,
    AudioStreamInfo,
    StreamPlatform,
    MediaType,
)


class MediaInspectorError(Exception):
    """Raised when inspecting media fails."""
    pass


def compute_fast_sha256(file_path: Path, chunk_size: int = 16 * 1024 * 1024) -> str:
    """Computes SHA-256 over first 16MB + last 16MB + file size, matching ClipForge Blueprint Section 3.3."""
    hasher = hashlib.sha256()
    size = file_path.stat().st_size
    hasher.update(str(size).encode())

    with open(file_path, "rb") as f:
        # First chunk
        first_chunk = f.read(chunk_size)
        hasher.update(first_chunk)

        # Last chunk if file is larger than 2x chunk_size
        if size > chunk_size * 2:
            f.seek(-chunk_size, 2)
            last_chunk = f.read(chunk_size)
            hasher.update(last_chunk)
        elif size > chunk_size:
            remaining = f.read()
            hasher.update(remaining)

    return hasher.hexdigest()


class MediaInspector:
    """Inspects media files or stream links via ffprobe."""

    def __init__(self, ffprobe_bin: str = "ffprobe"):
        self.ffprobe_bin = ffprobe_bin

    def inspect(
        self,
        target: str | Path,
        platform: StreamPlatform = StreamPlatform.LOCAL_FILE,
        media_type: MediaType = MediaType.RAW_UPLOAD,
        title: Optional[str] = None,
        author: Optional[str] = None,
    ) -> MediaMetadata:
        """Run ffprobe on a file path or URL and construct MediaMetadata."""
        target_str = str(target)
        is_local = Path(target_str).exists()

        cmd = [
            self.ffprobe_bin,
            "-v", "error",
            "-show_format",
            "-show_streams",
            "-print_format", "json",
            target_str,
        ]

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            data = json.loads(res.stdout)
        except subprocess.CalledProcessError as e:
            raise MediaInspectorError(f"ffprobe failed with exit code {e.returncode}: {e.stderr}") from e
        except subprocess.TimeoutExpired as e:
            raise MediaInspectorError(f"ffprobe timed out after 30 seconds inspecting {target_str}") from e
        except json.JSONDecodeError as e:
            raise MediaInspectorError(f"Failed to parse ffprobe JSON output: {e}") from e

        format_data = data.get("format", {})
        streams = data.get("streams", [])

        duration = float(format_data.get("duration", 0.0))
        size_bytes = int(format_data.get("size", 0))
        format_name = format_data.get("format_name", "")

        video_streams = []
        audio_streams = []

        for st in streams:
            codec_type = st.get("codec_type")
            idx = int(st.get("index", 0))
            codec_name = st.get("codec_name", "unknown")
            bit_rate = int(st.get("bit_rate")) if st.get("bit_rate") and st.get("bit_rate").isdigit() else None
            st_dur = float(st.get("duration")) if st.get("duration") else None

            if codec_type == "video":
                width = int(st.get("width", 0))
                height = int(st.get("height", 0))

                # Calculate FPS
                r_frame_rate = st.get("r_frame_rate", "30/1")
                fps = 30.0
                if "/" in r_frame_rate:
                    num, den = r_frame_rate.split("/")
                    if float(den) > 0:
                        fps = float(num) / float(den)
                elif r_frame_rate:
                    fps = float(r_frame_rate)

                # Detect VFR
                avg_frame_rate = st.get("avg_frame_rate", "")
                is_vfr = False
                if avg_frame_rate and "/" in avg_frame_rate:
                    anum, aden = avg_frame_rate.split("/")
                    if float(aden) > 0:
                        avg_fps = float(anum) / float(aden)
                        if abs(avg_fps - fps) > 0.05:
                            is_vfr = True

                # Rotation lives in a tag (older muxers) or display-matrix side data (newer ffprobe)
                rotation = 0
                rotate_tag = st.get("tags", {}).get("rotate")
                if rotate_tag and rotate_tag.lstrip("-").isdigit():
                    rotation = int(rotate_tag)
                for side in st.get("side_data_list", []):
                    if "rotation" in side:
                        rotation = int(float(side["rotation"]))

                video_streams.append(
                    VideoStreamInfo(
                        index=idx,
                        codec_name=codec_name,
                        width=width,
                        height=height,
                        fps=round(fps, 3),
                        bit_rate=bit_rate,
                        duration=st_dur,
                        is_vfr=is_vfr,
                        rotation=rotation,
                    )
                )

            elif codec_type == "audio":
                sample_rate = int(st.get("sample_rate", 44100))
                channels = int(st.get("channels", 2))

                audio_streams.append(
                    AudioStreamInfo(
                        index=idx,
                        codec_name=codec_name,
                        sample_rate=sample_rate,
                        channels=channels,
                        bit_rate=bit_rate,
                        duration=st_dur,
                    )
                )

        sha256 = None
        if is_local:
            local_path = Path(target_str)
            if size_bytes == 0:
                size_bytes = local_path.stat().st_size
            sha256 = compute_fast_sha256(local_path)

        return MediaMetadata(
            file_path=target_str if is_local else None,
            source_url=target_str if not is_local else None,
            platform=platform,
            media_type=media_type,
            title=title or format_data.get("tags", {}).get("title"),
            author=author or format_data.get("tags", {}).get("artist"),
            duration_seconds=duration,
            file_size_bytes=size_bytes,
            video_streams=video_streams,
            audio_streams=audio_streams,
            has_video=len(video_streams) > 0,
            has_audio=len(audio_streams) > 0,
            sha256_hash=sha256,
            format_name=format_name,
            raw_probe={"format": format_data, "streams_count": len(streams)},
        )
