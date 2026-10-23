"""Acoustic feature analyzer implementing blueprint section 3.4 energy and dead-air formulation."""
from __future__ import annotations

import wave
import numpy as np
from pathlib import Path
from typing import List, Optional, Tuple

from .models import (
    AudioSignalPoint,
    AudioSignalsTimeline,
    EnergyScore,
)


def sigmoid(x: float) -> float:
    return float(1.0 / (1.0 + np.exp(-np.clip(x, -10.0, 10.0))))


def estimate_pitch_autocorr(frame: np.ndarray, sample_rate: int = 16000) -> float:
    """Estimates fundamental frequency F0 (Hz) using normalized autocorrelation.

    Focuses on human vocal range (80 Hz to 600 Hz).
    """
    if len(frame) < 256 or np.all(frame == 0):
        return 0.0

    min_lag = int(sample_rate / 600)  # 600 Hz max
    max_lag = int(sample_rate / 80)   # 80 Hz min

    if len(frame) <= max_lag:
        return 0.0

    # Subtract mean
    frame_norm = frame - np.mean(frame)
    var = np.sum(frame_norm**2)
    if var < 1e-6:
        return 0.0

    # Fast autocorrelation
    corr = np.correlate(frame_norm, frame_norm, mode="full")
    corr = corr[len(frame_norm) - 1 :]

    if len(corr) <= max_lag:
        return 0.0

    peak_lag = min_lag + int(np.argmax(corr[min_lag:max_lag]))
    peak_val = corr[peak_lag] / var

    # Voice threshold check
    if peak_val > 0.35:
        return float(sample_rate / peak_lag)
    return 0.0


class AcousticAnalyzer:
    """Extracts RMS loudness z-scores, pitch variance, and calculates S_energy and P_dead."""

    def __init__(
        self,
        frame_interval_s: float = 0.1,  # 100ms analysis steps
        alpha_1: float = 0.5,           # Loudness Z-score weight
        alpha_2: float = 0.3,           # Pitch Z-score weight
        alpha_3: float = 0.8,           # Audio event probability weight
    ):
        self.interval_s = frame_interval_s
        self.alpha_1 = alpha_1
        self.alpha_2 = alpha_2
        self.alpha_3 = alpha_3

    def analyze_wav(self, wav_path: str | Path, event_detector=None) -> AudioSignalsTimeline:
        """event_detector: optional AudioEventDetector (PANNs). When given, event_prob comes from the trained
        laughter/cheering/screaming classifier instead of the loudness heuristic."""
        """Processes 16kHz mono WAV file into a complete AudioSignalsTimeline."""
        wpath = Path(wav_path)
        if not wpath.exists():
            raise FileNotFoundError(f"WAV file not found: {wav_path}")

        with wave.open(str(wpath), "rb") as wf:
            sample_rate = wf.getframerate()
            num_channels = wf.getnchannels()
            num_frames = wf.getnframes()
            duration_s = num_frames / float(sample_rate)
            raw = wf.readframes(num_frames)

        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if num_channels > 1:
            samples = samples.reshape(-1, num_channels).mean(axis=1)

        frame_size = int(sample_rate * self.interval_s)
        if frame_size <= 0:
            frame_size = 1

        total_frames = int(len(samples) // frame_size)

        raw_rms_list = []
        raw_pitch_list = []
        raw_event_list = []
        is_speech_list = []

        # Pass 1: Raw extraction
        for i in range(total_frames):
            start = i * frame_size
            end = min(start + frame_size, len(samples))
            frame = samples[start:end]

            # RMS
            rms = float(np.sqrt(np.mean(frame**2))) if len(frame) > 0 else 0.0
            raw_rms_list.append(rms)

            # Pitch
            pitch = estimate_pitch_autocorr(frame, sample_rate)
            raw_pitch_list.append(pitch)

            # High energy / high frequency burst heuristic (shouts/cheers/laughter)
            # High RMS (> 0.25) combined with pitch variance or rapid energy change
            is_speech = rms > 0.015
            is_speech_list.append(is_speech)

            # Probability of scream/cheer/laugh
            event_p = 0.0
            if rms > 0.30:
                event_p = min(1.0, (rms - 0.2) * 2.5)
            elif pitch > 300 and rms > 0.15:
                event_p = min(1.0, (pitch - 300) / 200.0)

            raw_event_list.append(float(event_p))

        rms_arr = np.array(raw_rms_list)
        pitch_arr = np.array(raw_pitch_list)

        rms_mean = float(np.mean(rms_arr)) if len(rms_arr) > 0 else 0.0
        rms_std = float(np.std(rms_arr)) if len(rms_arr) > 0 else 1.0
        if rms_std < 1e-4:
            rms_std = 1.0

        # Non-zero pitch baseline
        voiced_pitches = pitch_arr[pitch_arr > 0]
        pitch_mean = float(np.mean(voiced_pitches)) if len(voiced_pitches) > 0 else 150.0
        pitch_std = float(np.std(voiced_pitches)) if len(voiced_pitches) > 0 else 30.0
        if pitch_std < 1e-4:
            pitch_std = 30.0

        event_source, music_ratio, reaction_peaks = "heuristic", 0.0, []
        if event_detector is not None:
            from .audio_event_detector import reaction_probability, strongest_reactions
            events = event_detector.detect(wpath, interval_s=self.interval_s)
            reactions = reaction_probability(events)
            for i in range(min(total_frames, len(reactions))):
                raw_event_list[i] = float(reactions[i])
            music_ratio = float((events["music"] > 0.5).mean()) if len(events["music"]) else 0.0
            reaction_peaks = strongest_reactions(events, interval_s=self.interval_s)
            event_source = "panns"

        points: List[AudioSignalPoint] = []
        for i in range(total_frames):
            t = round(i * self.interval_s, 2)
            rms = raw_rms_list[i]
            z_rms = float((rms - rms_mean) / rms_std)

            pitch = raw_pitch_list[i]
            z_pitch = float((pitch - pitch_mean) / pitch_std) if pitch > 0 else 0.0

            points.append(
                AudioSignalPoint(
                    timestamp_s=t,
                    rms=round(rms, 4),
                    z_rms=round(z_rms, 2),
                    pitch_hz=round(pitch, 1),
                    z_pitch=round(z_pitch, 2),
                    event_prob=round(raw_event_list[i], 2),
                    is_speech=is_speech_list[i],
                )
            )

        return AudioSignalsTimeline(
            event_source=event_source,
            music_ratio=round(music_ratio, 3),
            reaction_peaks=reaction_peaks,
            duration_s=round(duration_s, 2),
            interval_s=self.interval_s,
            baseline_rms_mean=round(rms_mean, 4),
            baseline_rms_std=round(rms_std, 4),
            baseline_pitch_mean=round(pitch_mean, 1),
            baseline_pitch_std=round(pitch_std, 1),
            points=points,
        )

    def evaluate_window(
        self,
        timeline: AudioSignalsTimeline,
        start_s: float,
        end_s: float,
    ) -> EnergyScore:
        """Evaluates S_energy(w) and P_dead(w) for candidate window w = [start_s, end_s]."""
        pts = [p for p in timeline.points if start_s <= p.timestamp_s <= end_s]

        if not pts:
            return EnergyScore(
                energy_score=0.0,
                max_z_rms=0.0,
                max_z_pitch=0.0,
                event_prob=0.0,
                dead_air_ratio=0.0,
            )

        max_z_rms = max(p.z_rms for p in pts)
        max_z_pitch = max(p.z_pitch for p in pts)
        max_event_prob = max(p.event_prob for p in pts)

        # Calibrated Sigmoid for S_energy:
        # S_energy(w) = sigma(alpha_1 * max(Z_RMS) + alpha_2 * max(Z_F0) + alpha_3 * P_event - bias)
        raw_activation = (
            self.alpha_1 * max_z_rms
            + self.alpha_2 * max_z_pitch
            + self.alpha_3 * max_event_prob
            - 1.0  # Center sigmoid around slightly above-average events
        )
        s_energy = sigmoid(raw_activation)

        # Dead-air penalty P_dead:
        # Share of clip's duration in silent stretches longer than 1.2s
        silence_stretch = 0.0
        total_dead_air = 0.0
        for p in pts:
            if not p.is_speech:
                silence_stretch += timeline.interval_s
            else:
                if silence_stretch >= 1.2:
                    total_dead_air += silence_stretch
                silence_stretch = 0.0

        if silence_stretch >= 1.2:
            total_dead_air += silence_stretch

        window_duration = max(0.1, end_s - start_s)
        dead_air_ratio = min(1.0, total_dead_air / window_duration)

        return EnergyScore(
            energy_score=round(s_energy, 3),
            max_z_rms=round(max_z_rms, 2),
            max_z_pitch=round(max_z_pitch, 2),
            event_prob=round(max_event_prob, 2),
            dead_air_ratio=round(dead_air_ratio, 3),
        )
