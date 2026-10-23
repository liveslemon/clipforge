"""ASS (Advanced SubStation Alpha) subtitle generator with word-level highlight animation."""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from .models import CaptionConfig, CaptionStyle
from ..module_03_transcription.models import TimedWord


def ms_to_ass_time(ms: int) -> str:
    """Converts milliseconds to H:MM:SS.cc for ASS subtitles."""
    total_sec = ms // 1000
    centis = (ms % 1000) // 10
    hours = total_sec // 3600
    mins = (total_sec % 3600) // 60
    secs = total_sec % 60
    return f"{hours}:{mins:02d}:{secs:02d}.{centis:02d}"


def sanitize_ass_text(text: str) -> str:
    """Sanitizes text by escaping curly braces to prevent ASS override tag injection (Blueprint Section 6.2)."""
    text = text.replace("{", "(").replace("}", ")")
    return text.strip()


class ASSSubtitleGenerator:
    """Generates styled ASS subtitle files for video burning."""

    def __init__(self, canvas_width: int = 1080, canvas_height: int = 1920):
        self.canvas_width = canvas_width
        self.canvas_height = canvas_height

    def generate_ass(
        self,
        words: List[TimedWord],
        clip_in_s: float,
        clip_out_s: float,
        config: CaptionConfig,
        output_file: Optional[str | Path] = None,
        words_per_group: Optional[int] = None,
    ) -> str:
        """Generates ASS content with word-by-word active highlight styling."""
        words_per_group = words_per_group or config.words_per_group
        in_ms = int(clip_in_s * 1000)
        out_ms = int(clip_out_s * 1000)

        # Filter words inside the clip window and re-base to t=0
        clip_words = []
        for w in words:
            if w.end_ms > in_ms and w.start_ms < out_ms:
                rel_start = max(0, w.start_ms - in_ms)
                rel_end = min(out_ms - in_ms, w.end_ms - in_ms)
                clip_words.append(
                    TimedWord(
                        word=sanitize_ass_text(w.word.upper() if config.uppercase else w.word),
                        start_ms=rel_start,
                        end_ms=rel_end,
                        confidence=w.confidence,
                    )
                )

        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {self.canvas_width}
PlayResY: {self.canvas_height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{config.font_name},{config.font_size},{config.primary_color},&H000000FF,{config.outline_color},&H80000000,{-1 if config.bold else 0},0,0,0,100,100,0,0,1,{config.outline_px},{config.shadow_px},2,80,80,{int(self.canvas_height * (1.0 - config.position_percent_y))},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        events: List[str] = []

        # Group words into 3-5 word groups
        for g in range(0, len(clip_words), words_per_group):
            group = clip_words[g : g + words_per_group]
            if not group:
                continue

            # For each word in the group, create a sub-event highlighting that active word
            for active_idx, active_word in enumerate(group):
                start_str = ms_to_ass_time(active_word.start_ms)
                end_str = ms_to_ass_time(active_word.end_ms)

                phrase_parts = []
                for idx, w in enumerate(group):
                    if idx == active_idx and config.style == CaptionStyle.WORD_HIGHLIGHT:
                        # Highlight active word in highlight_color (e.g. yellow) + scale up 110%
                        phrase_parts.append(f"{{\\c{config.highlight_color}\\fscx110\\fscy110}}{w.word}{{\\r}}")
                    elif idx == active_idx and config.style == CaptionStyle.BOLD_POP:
                        # Pop animation
                        phrase_parts.append(f"{{\\fscx120\\fscy120}}{w.word}{{\\r}}")
                    else:
                        phrase_parts.append(w.word)

                text_line = " ".join(phrase_parts)
                events.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{text_line}")

        ass_content = header + "\n".join(events) + "\n"

        if output_file:
            Path(output_file).write_text(ass_content, encoding="utf-8")

        return ass_content
