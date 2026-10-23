"""Waveform generator computing RMS and peak amplitude points for UI scrubbing."""
from __future__ import annotations

import json
import wave
import numpy as np
from pathlib import Path
from typing import List

from .models import WaveformData, WaveformPoint


class WaveformGenerator:
    """Computes downsampled waveform data from a WAV audio file."""

    def __init__(self, bucket_interval_s: float = 0.1):  # 100ms buckets
        self.bucket_interval_s = bucket_interval_s

    def generate(self, wav_path: str | Path, output_json: str | Path | None = None) -> WaveformData:
        wav_file = Path(wav_path)
        if not wav_file.exists():
            raise FileNotFoundError(f"WAV file not found: {wav_path}")

        with wave.open(str(wav_file), "rb") as wf:
            sample_rate = wf.getframerate()
            num_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            num_frames = wf.getnframes()
            duration_s = num_frames / float(sample_rate)

            raw_bytes = wf.readframes(num_frames)

        # Parse audio samples
        if sample_width == 2:  # 16-bit PCM
            dtype = np.int16
            max_val = 32768.0
        elif sample_width == 1:  # 8-bit unsigned
            dtype = np.uint8
            max_val = 255.0
        elif sample_width == 4:  # 32-bit float or int
            dtype = np.float32
            max_val = 1.0
        else:
            dtype = np.int16
            max_val = 32768.0

        samples = np.frombuffer(raw_bytes, dtype=dtype)
        if num_channels > 1:
            samples = samples.reshape(-1, num_channels).mean(axis=1)

        # Normalize to [-1.0, 1.0]
        if sample_width == 1:
            norm_samples = (samples.astype(np.float32) - 128.0) / 128.0
        elif sample_width == 2:
            norm_samples = samples.astype(np.float32) / 32768.0
        else:
            norm_samples = samples.astype(np.float32)

        # Bucket samples
        bucket_size = int(sample_rate * self.bucket_interval_s)
        if bucket_size <= 0:
            bucket_size = 1

        points: List[WaveformPoint] = []
        num_buckets = int(np.ceil(len(norm_samples) / bucket_size))

        for b in range(num_buckets):
            start_idx = b * bucket_size
            end_idx = min((b + 1) * bucket_size, len(norm_samples))
            chunk = norm_samples[start_idx:end_idx]

            if len(chunk) == 0:
                continue

            peak = float(np.max(np.abs(chunk)))
            rms = float(np.sqrt(np.mean(chunk**2)))
            time_point = round(b * self.bucket_interval_s, 2)

            points.append(
                WaveformPoint(
                    time_s=time_point,
                    peak=round(min(1.0, peak), 4),
                    rms=round(min(1.0, rms), 4),
                )
            )

        waveform = WaveformData(
            duration_s=round(duration_s, 2),
            bucket_interval_s=self.bucket_interval_s,
            points=points,
        )

        if output_json:
            out_p = Path(output_json)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            with open(out_p, "w") as f:
                json.dump(waveform.model_dump(), f, indent=2)

        return waveform
