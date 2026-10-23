"""Tests for the AssemblyAI request/response mapping and the Claude caption proofreader (no network)."""
from modules.module_03_transcription.caption_proofreader import (
    Correction,
    ProofreadResult,
    apply_corrections,
    proofread,
    validate,
)
from modules.module_03_transcription.models import TimedWord, Transcript, TranscriptSegment
from modules.module_03_transcription.providers.assemblyai_provider import SPEECH_MODELS, AssemblyAIProvider


def _transcript():
    words = [TimedWord(word=w, start_ms=i * 500, end_ms=i * 500 + 400, confidence=c)
             for i, (w, c) in enumerate([("we", .9), ("waste", .9), ("nearly", .9), ("4-3%", .3), ("of", .9),
                                         ("energy", .9), ("firing", .35), ("classrooms", .9)])]
    seg = TranscriptSegment(id=1, start_ms=0, end_ms=words[-1].end_ms, text=" ".join(w.word for w in words), words=words)
    return Transcript(provider="test", duration_seconds=4.0, full_text=seg.text, segments=[seg])


def test_assemblyai_request_uses_current_api_fields():
    provider = AssemblyAIProvider(api_key="k", context="Campus energy promo with background music")
    body = provider.build_request("https://cdn/x.wav", language=None,
                                  vocabulary=["EcoSense", "motion sensors", "a phrase that is far too long to be a keyterm"])
    assert body["speech_models"] == SPEECH_MODELS == ["universal-3-5-pro", "universal-2"]
    assert body["prompt"].startswith("Campus energy promo")
    assert body["keyterms_prompt"] == ["EcoSense", "motion sensors"]  # >6-word phrases dropped
    assert body["language_detection"] is True and "language_code" not in body
    assert "word_boost" not in body  # legacy field


def test_assemblyai_response_parsing():
    data = {"id": "t1", "text": "Hi chat.", "audio_duration": 2.0, "language_code": "en", "speech_model_used": "universal-3-5-pro",
            "utterances": [{"start": 100, "end": 900, "text": "Hi chat.", "speaker": "A", "confidence": 0.9,
                            "words": [{"text": "Hi", "start": 100, "end": 400, "confidence": 0.95},
                                      {"text": "chat.", "start": 450, "end": 900, "confidence": 0.4}]}]}
    t = AssemblyAIProvider(api_key="k").parse_response(data, "a.wav")
    assert t.provider == "assemblyai:universal-3-5-pro"
    assert [w.word for w in t.all_words] == ["Hi", "chat."]
    assert t.segments[0].speaker == "A"
    assert t.raw_metadata["low_confidence_words"] == 1


def test_proofreader_only_touches_uncertain_words_and_keeps_timing():
    t = _transcript()
    good = Correction(segment_id=1, start_word=3, end_word=3, replacement="40%", reason="'nearly 4-3%' -> 40%")
    two_words = Correction(segment_id=1, start_word=6, end_word=6, replacement="powering", reason="fits energy context")
    confident = Correction(segment_id=1, start_word=0, end_word=1, replacement="we save", reason="rewrite")
    assert validate(confident, t) == "span has no uncertain word"
    assert validate(Correction(segment_id=1, start_word=6, end_word=40, replacement="x", reason=""), t) == "word range out of bounds"

    new_t, applied = apply_corrections(t, [good, two_words, confident])
    words = new_t.all_words
    assert [w.word for w in words] == ["we", "waste", "nearly", "40%", "of", "energy", "powering", "classrooms"]
    assert (words[3].start_ms, words[3].end_ms) == (1500, 1900)  # inherits the replaced word's timing
    assert len(applied) == 2 and new_t.raw_metadata["proofread_corrections"] == 2


def test_multiword_replacement_splits_time_span():
    t = _transcript()
    new_t, _ = apply_corrections(t, [Correction(segment_id=1, start_word=6, end_word=6,
                                                replacement="powering up", reason="")])
    w = new_t.all_words
    assert [x.word for x in w[6:8]] == ["powering", "up"]
    assert w[6].start_ms == 3000 and w[7].end_ms == 3400 and w[6].end_ms == w[7].start_ms


def test_proofread_is_a_noop_without_api_key(monkeypatch):
    monkeypatch.setattr("modules.module_03_transcription.caption_proofreader.llm_available", lambda: False)
    t = _transcript()
    out, applied, status = proofread(t, "context")
    assert out is t and applied == [] and status.startswith("skipped")


def test_proofread_applies_claude_corrections(monkeypatch):
    monkeypatch.setattr("modules.module_03_transcription.caption_proofreader.llm_available", lambda: True)
    captured = {}

    def fake_call(system, user, schema, **kw):
        captured["user"] = user
        return ProofreadResult(corrections=[Correction(segment_id=1, start_word=6, end_word=6, replacement="powering", reason="")])

    monkeypatch.setattr("modules.module_03_transcription.caption_proofreader.structured_call", fake_call)
    out, applied, status = proofread(_transcript(), "campus energy promo")
    assert "campus energy promo" in captured["user"] and "6:firing(0.35)" in captured["user"]
    assert "powering" in out.full_text and status.startswith("ok: 1")
