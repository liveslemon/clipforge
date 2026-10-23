"""Audio event detection with PANNs (Cnn14 sound-event model trained on Google AudioSet, 527 classes).

Replaces the loudness-threshold guess for "shout / laugh / cheer" with a trained classifier, and also reports
how much of the audio has music under it (a strong predictor of transcription difficulty).
~3 s per 100 s of audio on an M2 CPU.
"""
from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

PANNS_DIR = Path.home() / "panns_data"  # where panns_inference expects its files
CHECKPOINT = "Cnn14_DecisionLevelMax_mAP=0.385.pth"
CHECKPOINT_URL = "https://zenodo.org/record/3987831/files/Cnn14_DecisionLevelMax_mAP%3D0.385.pth?download=1"
LABELS_URL = "http://storage.googleapis.com/us_audioset/youtube_corpus/v1/csv/class_labels_indices.csv"
SAMPLE_RATE = 32000
FRAMES_PER_S = 100
CHUNK_S = 60

# AudioSet classes grouped into the reactions that make clips
EVENT_GROUPS: Dict[str, List[str]] = {
    "laughter": ["Laughter", "Giggle", "Chuckle, chortle", "Belly laugh", "Snicker"],
    "cheering": ["Cheering", "Applause", "Crowd", "Clapping"],
    "screaming": ["Screaming", "Shout", "Yell", "Battle cry", "Whoop"],
    "music": ["Music"],
    "speech": ["Speech"],
}
REACTION_GROUPS = ("laughter", "cheering", "screaming")


class AudioEventDetectorError(Exception):
    pass


def ensure_panns_files() -> Path:
    """Downloads the label list and checkpoint with urllib (panns_inference's own downloader needs wget)."""
    PANNS_DIR.mkdir(parents=True, exist_ok=True)
    labels = PANNS_DIR / "class_labels_indices.csv"
    if not labels.exists():
        urllib.request.urlretrieve(LABELS_URL, labels)
    ckpt = PANNS_DIR / CHECKPOINT
    if not ckpt.exists():
        urllib.request.urlretrieve(CHECKPOINT_URL, ckpt)
    return ckpt


class AudioEventDetector:
    def __init__(self, device: str = "cpu"):
        try:
            ckpt = ensure_panns_files()
            from panns_inference import SoundEventDetection, labels
        except ImportError as e:
            raise AudioEventDetectorError("pip install panns-inference librosa") from e
        self.model = SoundEventDetection(checkpoint_path=str(ckpt), device=device)
        self.index = {g: [labels.index(c) for c in classes if c in labels] for g, classes in EVENT_GROUPS.items()}

    def detect(self, wav_path: str | Path, interval_s: float = 0.1) -> Dict[str, np.ndarray]:
        """Per-group probabilities sampled every `interval_s` seconds (max over the group's classes)."""
        import librosa
        audio, _ = librosa.load(str(wav_path), sr=SAMPLE_RATE, mono=True)
        frames = []
        for start in range(0, len(audio), CHUNK_S * SAMPLE_RATE):
            chunk = audio[start:start + CHUNK_S * SAMPLE_RATE]
            if len(chunk) < SAMPLE_RATE // 10:
                continue
            out = self.model.inference(chunk[None, :])[0]
            frames.append(out[: int(len(chunk) / SAMPLE_RATE * FRAMES_PER_S)])
        if not frames:
            return {g: np.zeros(0) for g in EVENT_GROUPS}
        fw = np.concatenate(frames, axis=0)
        step = max(1, int(round(interval_s * FRAMES_PER_S)))
        n = len(fw) // step
        pooled = fw[: n * step].reshape(n, step, -1).max(axis=1)
        return {g: pooled[:, idx].max(axis=1) if idx else np.zeros(n) for g, idx in self.index.items()}


def reaction_probability(events: Dict[str, np.ndarray]) -> np.ndarray:
    return np.max(np.stack([events[g] for g in REACTION_GROUPS]), axis=0)


def strongest_reactions(events: Dict[str, np.ndarray], interval_s: float = 0.1, threshold: float = 0.3,
                        min_gap_s: float = 5.0) -> List[Dict]:
    """Peaks where a reaction class is likely, e.g. [{"t": 12.3, "event": "laughter", "prob": 0.82}]."""
    peaks: List[Dict] = []
    for g in REACTION_GROUPS:
        probs = events[g]
        for i in np.argsort(probs)[::-1]:
            if probs[i] < threshold:
                break
            t = float(i * interval_s)
            if all(abs(t - p["t"]) >= min_gap_s for p in peaks if p["event"] == g):
                peaks.append({"t": round(t, 2), "event": g, "prob": round(float(probs[i]), 3)})
            if sum(p["event"] == g for p in peaks) >= 10:
                break
    return sorted(peaks, key=lambda p: -p["prob"])
