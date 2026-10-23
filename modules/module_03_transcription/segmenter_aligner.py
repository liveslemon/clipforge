"""Transcript aligner, pause detector, and boundary snapper."""
from __future__ import annotations

import re
from typing import List, Optional, Tuple
from .models import Transcript, TimedWord, SpeechPause


class TranscriptAligner:
    """Provides word-level timing lookups, pause detection, and sentence snapping."""

    def __init__(self, transcript: Transcript):
        self.transcript = transcript
        self.words = transcript.all_words

    def find_pauses(self, min_silence_ms: int = 150) -> List[SpeechPause]:
        """Detects silent gaps between consecutive words >= min_silence_ms."""
        pauses: List[SpeechPause] = []
        for i in range(len(self.words) - 1):
            curr_word = self.words[i]
            next_word = self.words[i + 1]
            gap = next_word.start_ms - curr_word.end_ms
            if gap >= min_silence_ms:
                pauses.append(
                    SpeechPause(
                        start_ms=curr_word.end_ms,
                        end_ms=next_word.start_ms,
                        duration_ms=gap,
                    )
                )
        return pauses

    def snap_start_boundary(
        self,
        target_ms: int,
        max_lookback_ms: int = 20000,
        min_silence_ms: int = 150,
    ) -> int:
        """Snaps clip start to preceding sentence start or natural pause (Blueprint Section 3.4).

        Searches backward up to max_lookback_ms (default 20s) for a sentence boundary,
        then snaps to a silence gap >= min_silence_ms.
        """
        if not self.words:
            return max(0, target_ms)

        # 1. Find words within lookback window [target_ms - max_lookback_ms, target_ms]
        earliest_ms = max(0, target_ms - max_lookback_ms)
        candidate_indices = [
            i for i, w in enumerate(self.words)
            if earliest_ms <= w.start_ms <= target_ms
        ]

        if not candidate_indices:
            # Snap to closest word before target
            prior_words = [w for w in self.words if w.start_ms <= target_ms]
            return prior_words[-1].start_ms if prior_words else target_ms

        # 2. Look for sentence start (word following punctuation . ? ! or capital letter)
        sentence_starts = []
        for idx in candidate_indices:
            if idx == 0:
                sentence_starts.append(idx)
            else:
                prev_word = self.words[idx - 1]
                if any(prev_word.word.endswith(p) for p in [".", "?", "!"]):
                    sentence_starts.append(idx)
                elif self.words[idx].word and self.words[idx].word[0].isupper():
                    # Gap before capitalized word
                    gap = self.words[idx].start_ms - prev_word.end_ms
                    if gap >= min_silence_ms:
                        sentence_starts.append(idx)

        if sentence_starts:
            # Pick the sentence start closest to target_ms (to keep clip concise)
            chosen_idx = sentence_starts[-1]
            return max(0, self.words[chosen_idx].start_ms - 300)  # 300ms lead-in padding

        # 3. Fallback: snap to the largest silence gap in window
        best_gap_ms = 0
        best_time = target_ms
        for idx in candidate_indices:
            if idx > 0:
                gap = self.words[idx].start_ms - self.words[idx - 1].end_ms
                if gap >= min_silence_ms and gap > best_gap_ms:
                    best_gap_ms = gap
                    best_time = self.words[idx].start_ms

        return max(0, best_time - 300)

    def snap_end_boundary(self, target_ms: int, pad_ms: int = 300) -> int:
        """Snaps clip end after the last spoken word boundary plus padding.

        Never cuts inside a spoken word.
        """
        if not self.words:
            return target_ms

        # Find words around target_ms
        for i, w in enumerate(self.words):
            # If target cuts directly inside a word, extend to word end
            if w.start_ms <= target_ms <= w.end_ms:
                return w.end_ms + pad_ms

        # Otherwise find the last word ending before or at target_ms
        before = [w for w in self.words if w.end_ms <= target_ms]
        if before:
            return before[-1].end_ms + pad_ms

        return target_ms + pad_ms
