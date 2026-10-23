"""Tests for Module 3: Speech-to-Text, aligner, and subtitle export."""
import pytest
from pathlib import Path

from modules.module_03_transcription.models import Transcript, TimedWord, TranscriptSegment
from modules.module_03_transcription.providers.mock_provider import MockTranscriptionProvider
from modules.module_03_transcription.segmenter_aligner import TranscriptAligner
from modules.module_03_transcription.exporters import SubtitleExporter, ms_to_srt_time, ms_to_vtt_time


@pytest.mark.asyncio
async def test_mock_transcription_provider():
    provider = MockTranscriptionProvider()
    transcript = await provider.transcribe("dummy_audio.wav")

    assert transcript.provider == "mock-stt"
    assert len(transcript.segments) == 4
    assert len(transcript.all_words) > 15
    assert transcript.duration_seconds > 0

    first_word = transcript.all_words[0]
    assert first_word.start_ms == 500
    assert first_word.end_ms > first_word.start_ms


def test_timecode_formatting():
    # 0 ms
    assert ms_to_srt_time(0) == "00:00:00,000"
    assert ms_to_vtt_time(0) == "00:00:00.000"

    # 1 hour, 23 minutes, 45 seconds, 678 ms
    ms = (1 * 3600 + 23 * 60 + 45) * 1000 + 678
    assert ms_to_srt_time(ms) == "01:23:45,678"
    assert ms_to_vtt_time(ms) == "01:23:45.678"


@pytest.mark.asyncio
async def test_transcript_aligner_and_snapping():
    provider = MockTranscriptionProvider()
    transcript = await provider.transcribe("dummy_audio.wav")
    aligner = TranscriptAligner(transcript)

    # 1. Detect pauses between segments
    pauses = aligner.find_pauses(min_silence_ms=150)
    assert len(pauses) > 0
    for p in pauses:
        assert p.duration_ms >= 150

    # 2. Test snap start boundary around second sentence (around 5000ms)
    snapped_start = aligner.snap_start_boundary(target_ms=5500, max_lookback_ms=5000)
    # The sentence "Wait what was that noise?" starts at 4200ms
    # With 300ms lead-in padding, should snap to 3900ms
    assert snapped_start <= 4200

    # 3. Test snap end boundary inside a word
    # Third segment starts at 7800ms, word "Oh" is [7800, 8120]
    snapped_end = aligner.snap_end_boundary(target_ms=7900, pad_ms=300)
    # It must extend past 8120ms to not cut the word "Oh"
    assert snapped_end >= 8120 + 300


@pytest.mark.asyncio
async def test_subtitle_exporters(tmp_path: Path):
    provider = MockTranscriptionProvider()
    transcript = await provider.transcribe("dummy_audio.wav")

    # Export SRT
    srt_file = tmp_path / "captions.srt"
    srt_text = SubtitleExporter.to_srt(transcript, srt_file)
    assert srt_file.exists()
    assert "-->" in srt_text
    assert "00:00:" in srt_text

    # Export VTT
    vtt_file = tmp_path / "captions.vtt"
    vtt_text = SubtitleExporter.to_vtt(transcript, vtt_file)
    assert vtt_file.exists()
    assert vtt_text.startswith("WEBVTT")

    # Export JSON
    json_file = tmp_path / "transcript.json"
    json_text = SubtitleExporter.to_json(transcript, json_file)
    assert json_file.exists()
    assert '"provider": "mock-stt"' in json_text


def _seg(text, start, probs):
    words = text.split()
    return {"text": text, "start": start, "end": start + len(words) * 0.3,
            "words": [{"word": " " + w, "start": start + i * 0.3, "end": start + i * 0.3 + 0.25, "probability": p}
                      for i, (w, p) in enumerate(zip(words, probs))]}


def test_hallucination_filter_drops_stock_phrases_and_repeats():
    """Low-confidence 'Thank you.' over music and looping repeats are removed; real speech is kept."""
    from modules.module_03_transcription.providers.local_whisper_provider import clean_segments

    segs = [
        _seg("We have a massive problem here on campus.", 0.0, [0.9] * 8),
        _seg("Thank you.", 5.0, [0.3, 0.3]),                      # invented over music
        _seg("We are all the same kind.", 8.0, [0.5] * 6),
        _seg("We are all the same kind.", 10.0, [0.5] * 6),       # repetition loop
        _seg("Thank you.", 14.0, [0.95, 0.95]),                   # confidently spoken: keep
    ]
    kept = [s["text"] for s in clean_segments(segs)]
    assert kept == ["We have a massive problem here on campus.", "We are all the same kind.", "Thank you."]


def test_words_to_segments_splits_on_sentences_and_pauses():
    from modules.module_03_transcription.providers.local_whisper_provider import words_to_segments

    words = [
        {"word": " Hello", "start": 0.0, "end": 0.3, "probability": 0.9},
        {"word": " chat.", "start": 0.35, "end": 0.6, "probability": 0.8},
        {"word": " Clip", "start": 0.7, "end": 0.9, "probability": 0.7},
        {"word": " that", "start": 0.95, "end": 1.2, "probability": 0.6},
        {"word": " now", "start": 3.0, "end": 3.3, "probability": 0.5},  # 1.8 s pause -> new segment
    ]
    segs = words_to_segments(words)
    assert [s.text for s in segs] == ["Hello chat.", "Clip that", "now"]
    assert segs[0].start_ms == 0 and segs[0].end_ms == 600
    assert segs[1].words[0].word == "Clip"
