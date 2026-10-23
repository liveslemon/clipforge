"""Tests for Claude-driven clip selection post-processing (Claude itself is faked)."""
from modules.module_03_transcription.models import TimedWord, Transcript, TranscriptSegment
from modules.module_04_audio_signals.models import AudioSignalPoint, AudioSignalsTimeline
from modules.module_07_highlight_scorer.llm_selector import ClipPlan, ClipProposal, LLMClipSelector, _signal_summary
from modules.module_07_highlight_scorer.models import NichePreset


def _fixture(duration_s=120):
    segs, words = [], []
    for i in range(0, duration_s - 4, 4):  # one 6-word sentence every 4 s
        ws = [TimedWord(word=w, start_ms=i * 1000 + j * 500, end_ms=i * 1000 + j * 500 + 400)
              for j, w in enumerate(["Wait", "did", "you", "see", "that", "play."])]
        words += ws
        segs.append(TranscriptSegment(id=len(segs) + 1, start_ms=ws[0].start_ms, end_ms=ws[-1].end_ms,
                                      text=" ".join(w.word for w in ws), words=ws))
    t = Transcript(provider="test", duration_seconds=duration_s, full_text="", segments=segs)
    pts = [AudioSignalPoint(timestamp_s=k / 10, rms=0.05, z_rms=3.0 if 400 <= k < 420 else 0.0, pitch_hz=0,
                            z_pitch=0, event_prob=0, is_speech=True) for k in range(duration_s * 10)]
    tl = AudioSignalsTimeline(duration_s=duration_s, interval_s=0.1, baseline_rms_mean=0.05, baseline_rms_std=0.01,
                              baseline_pitch_mean=150, baseline_pitch_std=30, points=pts)
    return t, tl


def _proposal(start, end, worth, title="Clip"):
    return ClipProposal(start_s=start, end_s=end, title=title, hook_line="Wait did you see that", why="payoff",
                        clip_worthiness=worth, hashtags=["#gaming", "clutch"])


def test_candidates_are_snapped_ranked_and_deduplicated():
    t, tl = _fixture()
    plan = ClipPlan(clips=[
        _proposal(8.2, 30.0, 70, "A"),
        _proposal(9.0, 29.0, 95, "duplicate of A"),   # >40% overlap with A -> dropped
        _proposal(40.1, 63.0, 90, "B"),
        _proposal(70.0, 72.0, 99, "too short"),       # < min duration -> dropped
    ])
    cands = LLMClipSelector().to_candidates(plan, t, tl, None, NichePreset.GAMING, 15, 60, 8)
    titles = [c.title for c in cands]
    assert titles == ["B", "A"]  # ranked by blended score; B has the higher Claude score and the loud moment
    for c in cands:
        assert c.source == "llm+signals"
        assert 15 * 0.8 <= c.duration_s <= 60 * 1.05
        assert 0 < c.components.s_llm <= 1
        assert c.hashtags[0] == "gaming"
        # starts at a word start (or its 300 ms lead-in), never mid-word
        assert any(abs(c.start_ms - (w.start_ms - 300)) <= 1 or c.start_ms == w.start_ms for w in t.all_words)


def test_overlong_clip_is_trimmed_to_max_at_word_boundary():
    t, tl = _fixture()
    cands = LLMClipSelector().to_candidates(ClipPlan(clips=[_proposal(0.0, 110.0, 80)]), t, tl, None,
                                            NichePreset.GAMING, 15, 60, 8)
    assert len(cands) == 1 and cands[0].duration_s <= 60 * 1.05


def test_signal_summary_lists_loud_moments():
    _, tl = _fixture()
    assert "loud moment at 0:40.0" in _signal_summary(tl, None)
