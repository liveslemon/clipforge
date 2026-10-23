"""Chat velocity calculation and reaction spike detection."""
from __future__ import annotations

import re
from typing import List, Dict, Optional, Tuple
from collections import Counter
import numpy as np

from .models import ChatMessage, ChatMetricsPoint, ChatScore

CLIP_KEYWORDS = ["clip it", "clip this", "clip that", "!clip", "clip", "clippers"]


class ChatVelocityEngine:
    """Calculates chat velocity, baseline rates, and S_chat scores with lag compensation."""

    def __init__(
        self,
        window_size_s: float = 5.0,  # 5s sliding window per blueprint
        lag_compensation_s: float = 4.5,  # Shift chat window back 4.5s (in 3-8s range)
    ):
        self.window_size_s = window_size_s
        self.lag_compensation_s = lag_compensation_s

    def compute_timeline(
        self,
        messages: List[ChatMessage],
        step_s: float = 1.0,
    ) -> Tuple[List[ChatMetricsPoint], float, float]:
        """Generates continuous rate timeline and returns (points, mean_rate, std_rate)."""
        if not messages:
            return [], 0.0, 1.0

        max_time = max(m.timestamp_s for m in messages)
        total_steps = int(np.ceil(max_time / step_s)) + 1

        points: List[ChatMetricsPoint] = []
        msg_times = np.array([m.timestamp_s for m in messages])

        rates: List[float] = []

        for step in range(total_steps):
            t = step * step_s
            w_start = max(0.0, t - self.window_size_s / 2.0)
            w_end = t + self.window_size_s / 2.0

            # Find messages in this sliding window
            in_window = [m for m in messages if w_start <= m.timestamp_s <= w_end]
            rate = len(in_window) / self.window_size_s
            rates.append(rate)

            # Emotes in window
            emote_count = sum(len(m.emotes) for m in in_window)
            emote_rate = emote_count / self.window_size_s

            # Keyword trigger
            kw_count = sum(
                1 for m in in_window
                if any(k in m.text.lower() for k in CLIP_KEYWORDS)
            )

            points.append(
                ChatMetricsPoint(
                    timestamp_s=round(t, 2),
                    msg_rate_per_sec=round(rate, 2),
                    emote_rate_per_sec=round(emote_rate, 2),
                    clip_keyword_count=kw_count,
                )
            )

        rates_arr = np.array(rates)
        mean_rate = float(np.mean(rates_arr)) if len(rates_arr) > 0 else 0.0
        std_rate = float(np.std(rates_arr)) if len(rates_arr) > 0 else 1.0
        if std_rate < 1e-4:
            std_rate = 1.0

        return points, mean_rate, std_rate

    def score_window(
        self,
        messages: List[ChatMessage],
        on_stream_start_s: float,
        on_stream_end_s: float,
        mean_rate: Optional[float] = None,
        std_rate: Optional[float] = None,
    ) -> ChatScore:
        """Evaluates S_chat(w) for an on-stream candidate window [start, end].

        Applies lag compensation: chat reaction occurs lag_compensation_s AFTER on-stream event.
        Chat evaluation window = [start + lag, end + lag + 3.0].
        """
        if not messages:
            return ChatScore(
                score=0.0,
                peak_msg_rate=0.0,
                baseline_mean=0.0,
                baseline_std=1.0,
                has_clip_it_trigger=False,
                top_emotes={},
            )

        # Baseline stats if not provided
        if mean_rate is None or std_rate is None:
            _, mean_rate, std_rate = self.compute_timeline(messages)

        chat_start = on_stream_start_s + self.lag_compensation_s
        chat_end = on_stream_end_s + self.lag_compensation_s + 2.0  # slight extension for chat tail

        # Messages in shifted chat window
        window_msgs = [m for m in messages if chat_start <= m.timestamp_s <= chat_end]

        if not window_msgs:
            return ChatScore(
                score=0.0,
                peak_msg_rate=0.0,
                baseline_mean=mean_rate,
                baseline_std=std_rate,
                has_clip_it_trigger=False,
                top_emotes={},
            )

        # Calculate peak message rate using 5s sliding window within the chat window
        duration = max(self.window_size_s, chat_end - chat_start)
        msg_count = len(window_msgs)
        peak_rate = 0.0

        for t in np.arange(chat_start, chat_end, 1.0):
            w_msgs = [m for m in window_msgs if t <= m.timestamp_s <= t + self.window_size_s]
            r = len(w_msgs) / self.window_size_s
            if r > peak_rate:
                peak_rate = r

        if peak_rate == 0.0:
            peak_rate = msg_count / duration

        # Detect "clip it" keyword
        has_clip_it = any(
            any(k in m.text.lower() for k in CLIP_KEYWORDS)
            for m in window_msgs
        )

        # Top emotes
        all_emotes = [e for m in window_msgs for e in m.emotes]
        top_emotes = dict(Counter(all_emotes).most_common(5))

        # Blueprint Section 3.4 formula:
        # S_chat(w) = min(1, max(0, (PeakMsgRate - mu_chat) / (4 * sigma_chat) + 0.25 * I("clip it")))
        z_norm = (peak_rate - mean_rate) / (4.0 * std_rate)
        raw_score = max(0.0, z_norm) + (0.25 if has_clip_it else 0.0)
        s_chat = min(1.0, max(0.0, raw_score))

        return ChatScore(
            score=round(s_chat, 3),
            peak_msg_rate=round(peak_rate, 2),
            baseline_mean=round(mean_rate, 2),
            baseline_std=round(std_rate, 2),
            has_clip_it_trigger=has_clip_it,
            top_emotes=top_emotes,
        )
