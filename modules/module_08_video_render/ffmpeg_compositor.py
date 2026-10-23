"""FFmpeg video compositor executing RenderSpec documents into vertical MP4s.

Output follows short-form platform norms: 1080x1920 H.264 High profile (CRF 18), source frame rate up to 60 fps,
AAC 48 kHz 192 kb/s loudness-normalised to about -14 LUFS (EBU R128), captions burned in when FFmpeg has libass.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import List, Optional

from .models import RenderLayout, RenderOutput, RenderSpec
from .ass_generator import ASSSubtitleGenerator
from ..module_03_transcription.models import TimedWord


class RenderError(Exception):
    pass


def is_filter_supported(ffmpeg_bin: str, filter_name: str) -> bool:
    """Checks if an FFmpeg filter (e.g. 'subtitles' or 'ass') is compiled into the binary."""
    try:
        res = subprocess.run([ffmpeg_bin, "-h", f"filter={filter_name}"], capture_output=True, text=True)
        return "Unknown filter" not in res.stdout and "No such filter" not in res.stderr
    except Exception:
        return False


def _clamped_crop(w: int, h: int, x: int, y: int) -> str:
    """Crop filter whose region is clipped to the input frame, so regions authored for 1920x1080
    still work on 1280x720, portrait phone footage, etc."""
    return (
        f"crop=min({w}\\,iw):min({h}\\,ih)"
        f":max(0\\,min({x}\\,iw-ow)):max(0\\,min({y}\\,ih-oh))"
    )


def _filter_path(path: Path) -> str:
    """Quotes a file path for use inside an FFmpeg filtergraph option."""
    return "'" + str(path.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'") + "'"


class VideoCompositor:
    """Renders video according to RenderSpec JSON using FFmpeg."""

    def __init__(self, ffmpeg_bin: str = "ffmpeg"):
        self.ffmpeg_bin = ffmpeg_bin
        self.ass_generator = ASSSubtitleGenerator()
        self.has_ass_filter = is_filter_supported(ffmpeg_bin, "ass")
        self.has_subtitles_filter = self.has_ass_filter or is_filter_supported(ffmpeg_bin, "subtitles")
        self.has_loudnorm = is_filter_supported(ffmpeg_bin, "loudnorm")

    def build_filtergraph(
        self,
        spec: RenderSpec,
        ass_path: Optional[Path] = None,
        sendcmd_path: Optional[Path] = None,
    ) -> str:
        """Constructs FFmpeg filter complex string for the specified layout and subtitles."""
        filters = []

        if spec.layout == RenderLayout.SPLIT:
            # Facecam top (1080x760), gameplay bottom (1080x1160)
            fx, fy, fw, fh = spec.face_region or (1500, 50, 350, 350)
            gx, gy, gw, gh = spec.game_region or (0, 0, 1920, 1080)
            filters.append(
                f"[0:v]split=2[face_in][game_in];"
                f"[face_in]{_clamped_crop(fw, fh, fx, fy)},scale=1080:760:force_original_aspect_ratio=increase,crop=1080:760[face_top];"
                f"[game_in]{_clamped_crop(gw, gh, gx, gy)},scale=1080:1160:force_original_aspect_ratio=increase,crop=1080:1160[game_bot];"
                f"[face_top][game_bot]vstack=inputs=2[stacked]"
            )
            last_pad = "[stacked]"

        elif spec.layout == RenderLayout.FIT:
            # Blurred background + sharp centred original
            filters.append(
                f"[0:v]split=2[bg_in][fg_in];"
                f"[bg_in]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[bg];"
                f"[fg_in]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2[fitted]"
            )
            last_pad = "[fitted]"

        else:  # RenderLayout.CROP — widest 9:16 window; follows the face when a crop path is supplied
            crop_w, crop_h = "min(iw\\,ih*9/16)", "min(ih\\,iw*16/9)"
            if sendcmd_path and spec.crop_path:
                x0 = spec.crop_path[0][1]
                filters.append(
                    f"[0:v]sendcmd=f={_filter_path(sendcmd_path)},"
                    f"crop=w={crop_w}:h={crop_h}:x={x0:.1f}:y=(ih-oh)/2,scale=1080:1920,setsar=1[cropped]"
                )
            else:
                filters.append(f"[0:v]crop={crop_w}:{crop_h}:(iw-ow)/2:(ih-oh)/2,scale=1080:1920,setsar=1[cropped]")
            last_pad = "[cropped]"

        # Burn subtitles if ASS path is provided and filter is available in binary
        if ass_path and spec.captions.enabled and self.has_subtitles_filter:
            filter_cmd = "ass" if self.has_ass_filter else "subtitles"
            filters.append(f"{last_pad}{filter_cmd}={_filter_path(ass_path)}[outv]")
        else:
            filters.append(f"{last_pad}null[outv]")

        return ";".join(filters)

    def measure_loudness(self, spec: RenderSpec) -> Optional[dict]:
        """Pass 1 of two-pass loudnorm: measure the clip's audio (fast, audio only)."""
        target = f"I={spec.audio.normalize_lufs}:TP={spec.audio.true_peak_db}:LRA=11"
        cmd = [self.ffmpeg_bin, "-hide_banner", "-nostats", "-ss", str(spec.in_s), "-to", str(spec.out_s),
               "-i", str(spec.source_media_path), "-map", "0:a:0?", "-af", f"loudnorm={target}:print_format=json",
               "-f", "null", "-"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", res.stderr)
        if not m:
            return None
        stats = json.loads(m.group(0))
        if not stats.get("input_i") or stats["input_i"] in ("-inf", "inf"):
            return None  # silent clip
        return stats

    def audio_filter(self, spec: RenderSpec) -> Optional[str]:
        """Two-pass EBU R128: measured values make loudnorm apply a precise linear gain (one-pass undershoots on
        short clips by 2-3 LU)."""
        if not (spec.audio.normalize and self.has_loudnorm):
            return None
        target = f"I={spec.audio.normalize_lufs}:TP={spec.audio.true_peak_db}:LRA=11"
        stats = self.measure_loudness(spec)
        if not stats:
            return f"loudnorm={target}"
        return (f"loudnorm={target}:measured_I={stats['input_i']}:measured_TP={stats['input_tp']}"
                f":measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}"
                f":offset={stats['target_offset']}:linear=true")

    def render(
        self,
        spec: RenderSpec,
        output_path: str | Path,
        words: Optional[List[TimedWord]] = None,
    ) -> RenderOutput:
        """Executes full render of the clip."""
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        src_path = Path(spec.source_media_path)

        if not src_path.exists():
            raise RenderError(f"Source media not found: {spec.source_media_path}")

        # Generate ASS subtitle file if words provided and captions enabled
        ass_path = None
        if words and spec.captions.enabled:
            ass_path = out_file.parent / f"{out_file.stem}_captions.ass"
            self.ass_generator.generate_ass(
                words=words,
                clip_in_s=spec.in_s,
                clip_out_s=spec.out_s,
                config=spec.captions,
                output_file=ass_path,
            )

        sendcmd_path = None
        if spec.layout == RenderLayout.CROP and spec.crop_path:
            from ..module_06_vision_analyzer.reframe import sendcmd_script
            sendcmd_path = out_file.parent / f"{out_file.stem}_reframe.cmd"
            sendcmd_path.write_text(sendcmd_script(spec.crop_path))

        filtergraph = self.build_filtergraph(spec, ass_path, sendcmd_path)

        # Fast seek before input, accurate duration
        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-ss", str(spec.in_s),
            "-to", str(spec.out_s),
            "-i", str(src_path),
        ]

        # If hard-burning wasn't available but ASS exists, embed as subtitle stream
        soft_subs = bool(ass_path and spec.captions.enabled and not self.has_subtitles_filter)
        if soft_subs:
            cmd.extend(["-i", str(ass_path)])

        cmd.extend([
            "-filter_complex", filtergraph,
            "-map", "[outv]",
            "-map", "0:a:0?",  # first track only: iPhones add an undecodable spatial track (apple_apac)
        ])
        if soft_subs:
            cmd.extend(["-map", "1:s?", "-c:s", "mov_text"])

        audio_filter = self.audio_filter(spec)
        if audio_filter:
            cmd.extend(["-af", audio_filter])

        cmd.extend([
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", str(spec.video_crf),
            "-profile:v", "high",
            "-pix_fmt", "yuv420p",
            "-fps_mode", "cfr",
            "-fpsmax", str(spec.max_fps),
            "-c:a", "aac",
            "-ar", "48000",
            "-b:a", "192k",
            "-movflags", "+faststart",
            str(out_file),
        ])

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise RenderError(f"FFmpeg render failed: {e.stderr[-3000:]}") from e

        return RenderOutput(
            output_path=str(out_file.resolve()),
            duration_s=spec.duration_s,
            width=1080,
            height=1920,
            file_size_bytes=out_file.stat().st_size,
        )
