"""Data models for multi-signal highlight scoring, niche presets, and candidates."""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class NichePreset(str, Enum):
    GAMING = "GAMING"
    JUST_CHATTING = "JUST_CHATTING"
    IRL = "IRL"
    PODCAST = "PODCAST"
    EDUCATIONAL = "EDUCATIONAL"


class NicheWeights(BaseModel):
    w_hook: float
    w_energy: float
    w_chat: float
    w_narrative: float
    w_dead_penalty: float

    def without_chat(self) -> NicheWeights:
        """Redistributes w_chat to w_energy and w_narrative proportionally (Blueprint Section 3.4)."""
        denom = self.w_energy + self.w_narrative
        if denom <= 0:
            return self

        ratio_e = self.w_energy / denom
        ratio_n = self.w_narrative / denom

        return NicheWeights(
            w_hook=self.w_hook,
            w_energy=round(self.w_energy + self.w_chat * ratio_e, 3),
            w_chat=0.0,
            w_narrative=round(self.w_narrative + self.w_chat * ratio_n, 3),
            w_dead_penalty=self.w_dead_penalty,
        )


PRESET_WEIGHTS: Dict[NichePreset, NicheWeights] = {
    NichePreset.GAMING: NicheWeights(w_hook=0.20, w_energy=0.35, w_chat=0.25, w_narrative=0.20, w_dead_penalty=0.20),
    NichePreset.JUST_CHATTING: NicheWeights(w_hook=0.30, w_energy=0.25, w_chat=0.20, w_narrative=0.25, w_dead_penalty=0.25),
    NichePreset.IRL: NicheWeights(w_hook=0.25, w_energy=0.30, w_chat=0.20, w_narrative=0.25, w_dead_penalty=0.20),
    NichePreset.PODCAST: NicheWeights(w_hook=0.35, w_energy=0.15, w_chat=0.05, w_narrative=0.45, w_dead_penalty=0.30),
    NichePreset.EDUCATIONAL: NicheWeights(w_hook=0.35, w_energy=0.10, w_chat=0.05, w_narrative=0.50, w_dead_penalty=0.30),
}


class CandidateComponents(BaseModel):
    s_hook: float
    s_energy: float
    s_chat: float
    s_narrative: float
    p_dead: float
    s_llm: float = 0.0  # Claude's clip-worthiness judgement (0-1); 0 when no LLM was used


class HighlightCandidate(BaseModel):
    id: str
    start_ms: int
    end_ms: int
    duration_s: float
    score: float  # Composite 0 to 100
    niche: NichePreset
    title: str
    reason: str  # Explainability string for the user
    components: CandidateComponents
    transcript_snippet: str
    source: str = "signals"  # "signals" (heuristic windows) or "llm+signals" (Claude-selected, signal-weighted)
    hook_line: str = ""
    hashtags: List[str] = Field(default_factory=list)

    @property
    def start_s(self) -> float:
        return self.start_ms / 1000.0

    @property
    def end_s(self) -> float:
        return self.end_ms / 1000.0
