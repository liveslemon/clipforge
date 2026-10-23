"""Scene-cut detection: PySceneDetect AdaptiveDetector (industry standard), FFmpeg scene filter as fallback."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import List, Optional

from .models import SceneCut


class SceneDetector:
    """Detects visual scene cuts (hard cuts, OBS scene switches) in a video file."""

    def __init__(self, ffmpeg_bin: str = "ffmpeg", threshold: float = 0.35, backend: str = "auto",
                 adaptive_threshold: float = 3.0, min_content_val: float = 15.0):
        """
        backend: "pyscenedetect", "ffmpeg", or "auto" (PySceneDetect when installed).
        threshold: FFmpeg scene-score threshold (0-1), used by the ffmpeg backend.
        adaptive_threshold / min_content_val: PySceneDetect AdaptiveDetector tuning (its defaults).
        """
        self.ffmpeg_bin = ffmpeg_bin
        self.threshold = threshold
        self.adaptive_threshold = adaptive_threshold
        self.min_content_val = min_content_val
        if backend == "auto":
            try:
                import scenedetect  # noqa: F401
                backend = "pyscenedetect"
            except ImportError:
                backend = "ffmpeg"
        self.backend = backend

    def detect_scenes(self, video_path: str | Path) -> List[SceneCut]:
        vpath = Path(video_path)
        if not vpath.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")
        if self.backend == "pyscenedetect":
            return self._detect_pyscenedetect(vpath)
        return self._detect_ffmpeg(vpath)

    def _detect_pyscenedetect(self, vpath: Path) -> List[SceneCut]:
        from scenedetect import AdaptiveDetector, SceneManager, StatsManager, open_video

        video = open_video(str(vpath))
        manager = SceneManager(StatsManager())
        detector = AdaptiveDetector(adaptive_threshold=self.adaptive_threshold, min_content_val=self.min_content_val)
        manager.add_detector(detector)
        manager.detect_scenes(video)
        cuts: List[SceneCut] = []
        for idx, (start, _end) in enumerate(manager.get_scene_list()[1:], start=1):
            content = manager.stats_manager.get_metrics(start.frame_num, ["content_val"])[0] or 0.0
            cuts.append(SceneCut(timestamp_s=round(float(start.seconds), 2),
                                 score=round(min(1.0, float(content) / 100.0), 3), scene_index=idx))
        return cuts

    def _detect_ffmpeg(self, vpath: Path) -> List[SceneCut]:
        cmd = [
            self.ffmpeg_bin, "-i", str(vpath),
            "-vf", f"select='gt(scene,{self.threshold})',metadata=print",
            "-f", "null", "-",
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            output = res.stderr + "\n" + res.stdout
        except subprocess.CalledProcessError as e:
            output = (e.stderr or "") + "\n" + (e.stdout or "")

        cuts: List[SceneCut] = []
        scene_idx = 1
        score_pattern = re.compile(r"lavfi\.scene_score=([0-9.]+)")
        pts_pattern = re.compile(r"pts_time:([0-9.]+)")
        curr_pts: Optional[float] = None
        curr_score: Optional[float] = None

        def commit_cut():
            nonlocal curr_pts, curr_score, scene_idx
            if curr_pts is not None and curr_score is not None:
                cuts.append(SceneCut(timestamp_s=round(curr_pts, 2), score=round(curr_score, 3), scene_index=scene_idx))
                scene_idx += 1
                curr_pts = None
                curr_score = None

        for line in output.splitlines():
            if "frame:" in line:
                commit_cut()
            p_match = pts_pattern.search(line)
            if p_match:
                curr_pts = float(p_match.group(1))
            s_match = score_pattern.search(line)
            if s_match:
                curr_score = float(s_match.group(1))
        commit_cut()
        return cuts
