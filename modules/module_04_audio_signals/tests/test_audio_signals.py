"""Tests for Module 4: Acoustic feature analyzer and energy formulation."""
import wave
import numpy as np
import pytest
from pathlib import Path

from modules.module_04_audio_signals.models import AudioSignalsTimeline, EnergyScore
from modules.module_04_audio_signals.acoustic_analyzer import (
    AcousticAnalyzer,
    sigmoid,
    estimate_pitch_autocorr,
)


@pytest.fixture(scope="session")
def synthetic_audio(tmp_path_factory) -> Path:
    """Generates a 4-second 16kHz mono WAV file with:

    - 0.0s - 1.5s: Quiet background tone (0.05 amplitude, 200 Hz)
    - 1.5s - 2.5s: Loud shouting/burst spike (0.80 amplitude, 400 Hz)
    - 2.5s - 4.0s: Silence (0.0 amplitude, 1.5s > 1.2s dead air)
    """
    tmp_dir = tmp_path_factory.mktemp("audio_signals_fixtures")
    wav_path = tmp_dir / "synthetic_test.wav"

    sample_rate = 16000
    t1 = np.linspace(0, 1.5, int(sample_rate * 1.5), endpoint=False)
    sig1 = 0.05 * np.sin(2 * np.pi * 200 * t1)

    t2 = np.linspace(0, 1.0, int(sample_rate * 1.0), endpoint=False)
    sig2 = 0.80 * np.sin(2 * np.pi * 400 * t2)

    sig3 = np.zeros(int(sample_rate * 1.5))

    full_sig = np.concatenate([sig1, sig2, sig3])
    int16_samples = (full_sig * 32767).astype(np.int16)

    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(int16_samples.tobytes())

    return wav_path


def test_sigmoid():
    assert sigmoid(0.0) == 0.5
    assert sigmoid(10.0) > 0.99
    assert sigmoid(-10.0) < 0.01


def test_pitch_estimation():
    sample_rate = 16000
    t = np.linspace(0, 0.1, int(sample_rate * 0.1), endpoint=False)
    # 250 Hz pure sine wave
    sine = 0.5 * np.sin(2 * np.pi * 250 * t)
    pitch = estimate_pitch_autocorr(sine, sample_rate)
    # Should estimate close to 250 Hz (within 10 Hz)
    assert abs(pitch - 250) < 10


def test_acoustic_analyzer_timeline(synthetic_audio: Path):
    analyzer = AcousticAnalyzer(frame_interval_s=0.1)
    timeline = analyzer.analyze_wav(synthetic_audio)

    assert timeline.duration_s == 4.0
    assert len(timeline.points) == 40

    # The burst occurs between 1.5s and 2.5s
    burst_points = [p for p in timeline.points if 1.6 <= p.timestamp_s <= 2.4]
    quiet_points = [p for p in timeline.points if 0.2 <= p.timestamp_s <= 1.2]

    # Z_RMS of burst must be significantly higher than quiet section
    avg_burst_z = np.mean([p.z_rms for p in burst_points])
    avg_quiet_z = np.mean([p.z_rms for p in quiet_points])
    assert avg_burst_z > avg_quiet_z

    # Check event probability is triggered in burst
    max_event = max(p.event_prob for p in burst_points)
    assert max_event > 0.5


def test_window_energy_and_dead_air(synthetic_audio: Path):
    analyzer = AcousticAnalyzer(frame_interval_s=0.1)
    timeline = analyzer.analyze_wav(synthetic_audio)

    # 1. Burst window [1.4s, 2.6s]
    burst_score = analyzer.evaluate_window(timeline, 1.4, 2.6)
    assert burst_score.energy_score > 0.5
    assert burst_score.max_z_rms > 1.0
    assert burst_score.dead_air_ratio == 0.0  # No 1.2s silence in this window

    # 2. Silence window [2.5s, 4.0s] (1.5s total silence)
    silent_score = analyzer.evaluate_window(timeline, 2.5, 4.0)
    assert silent_score.dead_air_ratio > 0.8  # Almost 100% dead air
