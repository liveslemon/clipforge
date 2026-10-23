"""CLI tool for Module 6: Scene detection and camera deadband analysis."""
from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path

from .scene_detector import SceneDetector
from .facecam_tracker import FacecamTracker
from .models import BoundingBox


def main():
    parser = argparse.ArgumentParser(description="ClipForge Vision & Scene Analyzer CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # detect-scenes
    scenes_parser = subparsers.add_parser("detect-scenes", help="Detect scene changes in video")
    scenes_parser.add_argument("video_path", help="Path to video file")
    scenes_parser.add_argument("--threshold", type=float, default=0.35)

    # test-deadband
    deadband_parser = subparsers.add_parser("test-deadband", help="Simulate facecam deadband smoothing")
    deadband_parser.add_argument("--jitter", type=float, default=20.0, help="Simulated pixel jitter")

    args = parser.parse_args()

    if args.command == "detect-scenes":
        detector = SceneDetector(threshold=args.threshold)
        cuts = detector.detect_scenes(args.video_path)
        print(f"Detected {len(cuts)} scene transitions:")
        for c in cuts:
            print(f"  Scene {c.scene_index}: at {c.timestamp_s:.2f}s (score: {c.score})")

    elif args.command == "test-deadband":
        tracker = FacecamTracker(frame_width=1920, frame_height=1080)
        # Create simulated raw detections
        raw = [
            (0.0, BoundingBox(x=1500, y=100, width=300, height=300), 0.95),
            (0.5, BoundingBox(x=1505, y=102, width=300, height=300), 0.95),  # Micro jitter
            (1.0, BoundingBox(x=1498, y=98, width=300, height=300), 0.95),   # Micro jitter
            (1.5, BoundingBox(x=1800, y=200, width=300, height=300), 0.95),  # Major shift outside deadband
        ]
        smoothed = tracker.smooth_face_tracks(raw)
        print(f"Processed {len(smoothed)} points with deadband camera smoother:")
        for p in smoothed:
            print(f"  t={p.timestamp_s}s: Raw Center=({p.bbox.center_x}, {p.bbox.center_y}) -> Smoothed=({p.smoothed_center_x}, {p.smoothed_center_y})")


if __name__ == "__main__":
    main()
