"""Tests for Module 7: Multi-signal highlight scoring, niche presets, and deduplication."""
import pytest

from modules.module_07_highlight_scorer.models import (
    NichePreset,
    NicheWeights,
    PRESET_WEIGHTS,
    HighlightCandidate,
)
from modules.module_07_highlight_scorer.hook_narrative_evaluator import HookNarrativeEvaluator
from modules.module_07_highlight_scorer.composite_scorer import HighlightScorer
from modules.module_03_transcription.models import Transcript, TranscriptSegment, TimedWord
from modules.module_04_audio_signals.models import AudioSignalsTimeline, AudioSignalPoint
from modules.module_05_chat_analyzer.models import ChatMessage


def test_niche_weights_chat_redistribution():
    gaming_weights = PRESET_WEIGHTS[NichePreset.GAMING]
    assert gaming_weights.w_chat == 0.25

    no_chat = gaming_weights.without_chat()
    assert no_chat.w_chat == 0.0
    # The 0.25 chat weight is redistributed to energy (0.35) and narrative (0.20)
    assert no_chat.w_energy > gaming_weights.w_energy
    assert no_chat.w_narrative > gaming_weights.w_narrative

    # Sum of positive weights should equal 1.0
    total_pos = no_chat.w_hook + no_chat.w_energy + no_chat.w_narrative
    assert abs(total_pos - 1.0) < 0.02


def test_hook_evaluator():
    evaluator = HookNarrativeEvaluator()

    # Question hook
    words = [
        TimedWord(word="Why", start_ms=100, end_ms=400),
        TimedWord(word="did", start_ms=450, end_ms=700),
        TimedWord(word="you", start_ms=750, end_ms=900),
        TimedWord(word="do", start_ms=950, end_ms=1100),
        TimedWord(word="that?", start_ms=1150, end_ms=1500),
    ]
    score, reason = evaluator.evaluate_hook(words, window_start_ms=100)
    assert score >= 0.75
    assert "Question hook" in reason

    # Hanging ending word
    hanging_words = words + [TimedWord(word="because", start_ms=1600, end_ms=2000)]
    narr_score, narr_reason = evaluator.evaluate_narrative(hanging_words, duration_s=25.0)
    assert "Cut mid-thought" in narr_reason


def test_composite_highlight_scorer():
    # 1. Transcript: 40s stream
    # Highlight speech at t=15s: "Wait look at this leaderboard right now!"
    seg1 = TranscriptSegment(
        id=1, start_ms=1000, end_ms=4000, text="Just warming up the stream guys.",
        words=[TimedWord(word="Just", start_ms=1000, end_ms=1500), TimedWord(word="warming", start_ms=1600, end_ms=2200), TimedWord(word="up", start_ms=2300, end_ms=2800)]
    )
    seg2 = TranscriptSegment(
        id=2, start_ms=15000, end_ms=20000, text="Wait did you see that incredible shot?!",
        words=[
            TimedWord(word="Wait", start_ms=15000, end_ms=15400),
            TimedWord(word="did", start_ms=15450, end_ms=15800),
            TimedWord(word="you", start_ms=15850, end_ms=16100),
            TimedWord(word="see", start_ms=16150, end_ms=16600),
            TimedWord(word="that", start_ms=16650, end_ms=17000),
            TimedWord(word="shot?!", start_ms=17050, end_ms=17800),
        ]
    )
    transcript = Transcript(
        provider="mock",
        language="en",
        duration_seconds=40.0,
        full_text="Just warming up. Wait did you see that shot?!",
        segments=[seg1, seg2],
    )

    # 2. Audio signals: 40 seconds (400 points at 0.1s)
    points = []
    for step in range(400):
        t = step * 0.1
        # Loud burst between 15s and 22s
        if 15.0 <= t <= 22.0:
            rms = 0.55
            z_rms = 3.2
            pitch = 350.0
            z_pitch = 2.5
            event_p = 0.85
            is_speech = True
        else:
            rms = 0.05
            z_rms = -0.4
            pitch = 120.0
            z_pitch = -0.2
            event_p = 0.0
            is_speech = (t < 5.0)

        points.append(
            AudioSignalPoint(
                timestamp_s=round(t, 2),
                rms=rms,
                z_rms=z_rms,
                pitch_hz=pitch,
                z_pitch=z_pitch,
                event_prob=event_p,
                is_speech=is_speech,
            )
        )

    audio_timeline = AudioSignalsTimeline(
        duration_s=40.0,
        interval_s=0.1,
        baseline_rms_mean=0.10,
        baseline_rms_std=0.15,
        baseline_pitch_mean=140.0,
        baseline_pitch_std=40.0,
        points=points,
    )

    # 3. Chat: huge burst at t=19s (with lag compensation of ~4s aligns with t=15s on-stream)
    chat_msgs = [
        ChatMessage(timestamp_s=19.5, author=f"viewer{i}", text="CLIP IT KEKW", emotes=["kekw"])
        for i in range(25)
    ]

    scorer = HighlightScorer()
    candidates = scorer.find_candidates(
        transcript=transcript,
        audio_timeline=audio_timeline,
        chat_messages=chat_msgs,
        preset=NichePreset.GAMING,
        min_duration_s=10.0,
        max_duration_s=40.0,
        stride_s=5.0,
        max_candidates=5,
    )

    assert len(candidates) > 0
    top_cand = candidates[0]
    # The top candidate should encapsulate the peak highlight around t=15s
    assert top_cand.start_s <= 16.0
    assert top_cand.end_s >= 17.8
    assert top_cand.score > 60.0
    assert top_cand.components.s_energy > 0.70
    assert top_cand.components.s_chat > 0.50
    assert "CLIP IT" in top_cand.reason or "Acoustic" in top_cand.reason
