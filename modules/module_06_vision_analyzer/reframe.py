"""Face-tracked vertical reframing ("AI reframe"): a smooth 9:16 crop window that follows the main face.

Raw face boxes jitter and briefly disappear; the camera must not. The path is built in three stages:
1. deadband: the window only moves once the face leaves the central ~15% of the crop window,
2. gap fill: when no face is seen, hold the last position (reset at scene cuts),
3. smoothing: exponential easing sampled every 0.1 s, so pans are gentle and never step.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from .models import BoundingBox, SceneCut


def build_crop_path(
    detections: Sequence[Tuple[float, BoundingBox, float]],
    frame_w: int,
    frame_h: int,
    in_s: float,
    out_s: float,
    scene_cuts: Optional[Sequence[SceneCut]] = None,
    step_s: float = 0.1,
    deadband_ratio: float = 0.15,
    ease: float = 0.12,
) -> Optional[List[Tuple[float, float]]]:
    """Returns [(t_relative_to_clip_start_s, crop_left_x_px)] or None when no reframing is needed/possible.

    The crop window is the widest 9:16 region of the frame (width = frame_h * 9/16).
    """
    crop_w = min(frame_w, frame_h * 9 / 16)
    if frame_w - crop_w < 2:  # already vertical: nothing to pan
        return None
    max_x = frame_w - crop_w
    window = [(t, b) for t, b, _ in detections if in_s - 1.0 <= t <= out_s + 1.0]
    if not window:
        return None

    cut_times = sorted(c.timestamp_s for c in (scene_cuts or []) if in_s < c.timestamp_s < out_s)
    deadband = crop_w * deadband_ratio
    path: List[Tuple[float, float]] = []
    target = window[0][1].center_x
    camera = target
    det_i = 0
    snap_until = -1.0
    n_steps = int(round((out_s - in_s) / step_s))
    for k in range(n_steps + 1):
        t = in_s + k * step_s  # integer stepping: no float drift
        # newest detection at or before t
        while det_i + 1 < len(window) and window[det_i + 1][0] <= t + 1e-6:
            det_i += 1
        face = window[det_i][1]
        if abs(face.center_x - target) > deadband:
            target = face.center_x
        # hard cut: for 0.5 s after it, jump straight to the new framing instead of panning across the cut
        while cut_times and cut_times[0] <= t + 1e-6:
            snap_until = cut_times.pop(0) + 0.5
        if t <= snap_until:
            camera = target
        else:
            camera += ease * (target - camera)
        left = min(max_x, max(0.0, camera - crop_w / 2))
        path.append((round(t - in_s, 3), round(left, 1)))
    return path


def sendcmd_script(path: List[Tuple[float, float]]) -> str:
    """FFmpeg sendcmd script driving `crop`'s x option along the path (one command per step)."""
    return "\n".join(f"{t:.3f} crop x {x:.1f};" for t, x in path) + "\n"
