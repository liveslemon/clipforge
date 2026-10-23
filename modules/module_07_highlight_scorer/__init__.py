"""Multi-Signal Highlight Scoring & Boundary Snapping Module for ClipForge."""

from .models import (
    NichePreset,
    NicheWeights,
    PRESET_WEIGHTS,
    CandidateComponents,
    HighlightCandidate,
)
from .hook_narrative_evaluator import (
    HookNarrativeEvaluator,
    HOOK_QUESTION_TRIGGERS,
    CURIOSITY_PHRASES,
)
from .composite_scorer import HighlightScorer
from .llm_selector import LLMClipSelector, ClipPlan, ClipProposal

__all__ = [
    "NichePreset",
    "NicheWeights",
    "PRESET_WEIGHTS",
    "CandidateComponents",
    "HighlightCandidate",
    "HookNarrativeEvaluator",
    "HOOK_QUESTION_TRIGGERS",
    "CURIOSITY_PHRASES",
    "HighlightScorer",
    "LLMClipSelector",
    "ClipPlan",
    "ClipProposal",
]
