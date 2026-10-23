"""Subtitle and caption exporters (SRT, VTT, JSON)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, List
from .models import Transcript, TranscriptSegment, TimedWord


def ms_to_srt_time(ms: int) -> str:
    """Converts milliseconds to HH:MM:SS,mmm format for SRT."""
    total_seconds = ms // 1000
    milli = ms % 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milli:03d}"


def ms_to_vtt_time(ms: int) -> str:
    """Converts milliseconds to HH:MM:SS.mmm format for WebVTT."""
    total_seconds = ms // 1000
    milli = ms % 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milli:03d}"


class SubtitleExporter:
    """Exports transcripts to standard subtitle formats."""

    @staticmethod
    def to_srt(
        transcript: Transcript,
        output_file: Optional[str | Path] = None,
        words_per_caption: int = 4,  # Optimal for TikTok/Reels vertical reading
    ) -> str:
        """Generates an SRT string, optionally chunking into short phrases for vertical video."""
        all_words = transcript.all_words
        lines: List[str] = []
        counter = 1

        for i in range(0, len(all_words), words_per_caption):
            chunk = all_words[i : i + words_per_caption]
            if not chunk:
                continue

            start_str = ms_to_srt_time(chunk[0].start_ms)
            end_str = ms_to_srt_time(chunk[-1].end_ms)
            phrase = " ".join(w.word for w in chunk)

            lines.append(str(counter))
            lines.append(f"{start_str} --> {end_str}")
            lines.append(phrase)
            lines.append("")
            counter += 1

        srt_content = "\n".join(lines)
        if output_file:
            Path(output_file).write_text(srt_content, encoding="utf-8")
        return srt_content

    @staticmethod
    def to_vtt(transcript: Transcript, output_file: Optional[str | Path] = None) -> str:
        """Generates WebVTT subtitles."""
        lines = ["WEBVTT", ""]
        all_words = transcript.all_words

        counter = 1
        for i in range(0, len(all_words), 4):
            chunk = all_words[i : i + 4]
            if not chunk:
                continue

            start_str = ms_to_vtt_time(chunk[0].start_ms)
            end_str = ms_to_vtt_time(chunk[-1].end_ms)
            phrase = " ".join(w.word for w in chunk)

            lines.append(str(counter))
            lines.append(f"{start_str} --> {end_str}")
            lines.append(phrase)
            lines.append("")
            counter += 1

        vtt_content = "\n".join(lines)
        if output_file:
            Path(output_file).write_text(vtt_content, encoding="utf-8")
        return vtt_content

    @staticmethod
    def to_json(transcript: Transcript, output_file: Optional[str | Path] = None) -> str:
        """Exports transcript model as JSON."""
        json_content = transcript.model_dump_json(indent=2)
        if output_file:
            Path(output_file).write_text(json_content, encoding="utf-8")
        return json_content
