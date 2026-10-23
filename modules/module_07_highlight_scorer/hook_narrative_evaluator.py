"""Hook and narrative evaluation module."""
from __future__ import annotations

import re
from typing import List, Tuple
from ..module_03_transcription.models import Transcript, TimedWord

HOOK_QUESTION_TRIGGERS = [
    "why", "how", "what", "wait", "did you", "did he", "did they",
    "is this", "can we", "look at", "watch this", "are you serious", "who"
]

CURIOSITY_PHRASES = [
    "i can't believe", "no way", "oh my god", "what happened",
    "you won't believe", "never seen this", "clip that", "insane", "check this out"
]

HANGING_WORDS = {
    "and", "but", "so", "because", "or", "then", "if", "when", "that", "with", "at", "to", "for"
}


class HookNarrativeEvaluator:
    """Evaluates S_hook and S_narrative from transcript words and sentences."""

    def evaluate_hook(self, words_in_window: List[TimedWord], window_start_ms: int) -> Tuple[float, str]:
        """Evaluates S_hook in the first 3.5s [start, start + 3500ms]."""
        hook_end_ms = window_start_ms + 3500
        hook_words = [w for w in words_in_window if w.start_ms <= hook_end_ms]

        if not hook_words:
            return 0.20, "Low initial speech activity"

        hook_text = " ".join(w.word for w in hook_words).lower()

        score = 0.40  # Baseline speech presence
        reasons = []

        # Question hook
        if any(hook_text.startswith(q) or f" {q} " in hook_text for q in HOOK_QUESTION_TRIGGERS):
            score += 0.35
            reasons.append("Question hook")

        # Curiosity phrase
        if any(p in hook_text for p in CURIOSITY_PHRASES):
            score += 0.25
            reasons.append("Curiosity / shock phrase")

        # Hook confidence
        avg_conf = sum(w.confidence for w in hook_words) / len(hook_words)
        if avg_conf > 0.90:
            score += 0.05

        final_score = min(1.0, score)
        reason_str = " + ".join(reasons) if reasons else "Clear speech opening"
        return round(final_score, 2), reason_str

    def evaluate_narrative(self, words_in_window: List[TimedWord], duration_s: float) -> Tuple[float, str]:
        """Evaluates S_narrative based on completeness, pacing, and absence of hanging sentences."""
        if not words_in_window:
            return 0.10, "No speech"

        full_text = " ".join(w.word for w in words_in_window).strip()
        last_word = words_in_window[-1].word.lower().strip(".,!?")

        score = 0.50
        reasons = []

        # Optimal length check for vertical reels/shorts (15s - 60s)
        if 15.0 <= duration_s <= 55.0:
            score += 0.20
            reasons.append("Optimal shorts length")
        elif duration_s < 10.0:
            score -= 0.20
            reasons.append("Too short (<10s)")
        elif duration_s > 75.0:
            score -= 0.15
            reasons.append("Overly long (>75s)")

        # Check for hanging / cut-off ending word
        if last_word in HANGING_WORDS:
            score -= 0.30
            reasons.append(f"Cut mid-thought on '{last_word}'")
        else:
            score += 0.20
            reasons.append("Clean resolution")

        # Word count / pacing check (needs at least ~2.0 words/sec to avoid being boring)
        wps = len(words_in_window) / max(1.0, duration_s)
        if 2.0 <= wps <= 4.5:
            score += 0.10
            reasons.append("Engaging speech pacing")

        final_score = max(0.0, min(1.0, score))
        return round(final_score, 2), " | ".join(reasons)

    def generate_title(self, words_in_window: List[TimedWord]) -> str:
        """Derives a grounded title from the first sentence or hook of the candidate."""
        if not words_in_window:
            return "Stream Highlight"

        first_words = [w.word for w in words_in_window[:8]]
        title_candidate = " ".join(first_words).strip()
        # Clean title
        title_candidate = re.sub(r"[^\w\s'!?]", "", title_candidate)
        return title_candidate.capitalize() if title_candidate else "Stream Highlight"
