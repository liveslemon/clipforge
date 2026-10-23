"""Data models for audio acoustic feature extraction and energy scoring."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AudioSignalPoint(BaseModel):
    timestamp_s: float
    rms: float
    z_rms: float
    pitch_hz: float
    z_pitch: float
    event_prob: float  # probability of scream/laughter/cheering (0.0 to 1.0)
    is_speech: bool


class AudioSignalsTimeline(BaseModel):
    duration_s: float
    interval_s: float
    baseline_rms_mean: float
    baseline_rms_std: float
    baseline_pitch_mean: float
    baseline_pitch_std: float
    points: List[AudioSignalPoint] = Field(default_factory=list)
    event_source: str = "heuristic"  # "panns" when the trained AudioSet model produced event_prob
    music_ratio: float = 0.0         # share of frames with music likely (>0.5); high = harder transcription
    reaction_peaks: List[Dict[str, Any]] = Field(default_factory=list)  # [{"t", "event", "prob"}]


class EnergyScore(BaseModel):
    energy_score: float  # Normalized 0.0 to 1.0
    max_z_rms: float
    max_z_pitch: float
    event_prob: float
    dead_air_ratio: float  # P_dead: fraction of time with silence > 1.2s (0.0 to 1.0)
