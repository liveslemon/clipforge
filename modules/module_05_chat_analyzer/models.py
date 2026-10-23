"""Data models for chat messages, velocity analysis, and audience reaction scoring."""
from __future__ import annotations

from typing import List, Optional, Dict
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    timestamp_s: float  # Relative offset in seconds from stream start
    author: str
    text: str
    emotes: List[str] = Field(default_factory=list)


class ChatMetricsPoint(BaseModel):
    timestamp_s: float
    msg_rate_per_sec: float
    emote_rate_per_sec: float
    clip_keyword_count: int


class ChatScore(BaseModel):
    score: float  # S_chat normalized 0.0 to 1.0
    peak_msg_rate: float
    baseline_mean: float
    baseline_std: float
    has_clip_it_trigger: bool
    top_emotes: Dict[str, int] = Field(default_factory=dict)
