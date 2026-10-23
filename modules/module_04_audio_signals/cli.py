"""CLI tool for Module 4: Acoustic signals and energy scoring."""
from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path

from .acoustic_analyzer import AcousticAnalyzer


def main():
    parser = argparse.ArgumentParser(description="ClipForge Acoustic Analyzer CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # analyze
    an_parser = subparsers.add_parser("analyze", help="Extract acoustic timeline from WAV file")
    an_parser.add_argument("wav_file", help="Input 16kHz WAV file")
    an_parser.add_argument("--output-json", help="Save timeline JSON")

    # score-window
    score_parser = subparsers.add_parser("score-window", help="Score S_energy and P_dead for a time window")
    score_parser.add_argument("wav_file", help="Input 16kHz WAV file")
    score_parser.add_argument("start_s", type=float, help="Window start in seconds")
    score_parser.add_argument("end_s", type=float, help="Window end in seconds")

    args = parser.parse_args()

    analyzer = AcousticAnalyzer()

    if args.command == "analyze":
        timeline = analyzer.analyze_wav(args.wav_file)
        print(f"Analyzed {timeline.duration_s}s audio: {len(timeline.points)} points")
        print(f"Baseline RMS: mean={timeline.baseline_rms_mean}, std={timeline.baseline_rms_std}")
        print(f"Baseline Pitch: mean={timeline.baseline_pitch_mean}Hz, std={timeline.baseline_pitch_std}Hz")

        if args.output_json:
            Path(args.output_json).write_text(timeline.model_dump_json(indent=2))
            print(f"Saved: {args.output_json}")

    elif args.command == "score-window":
        timeline = analyzer.analyze_wav(args.wav_file)
        score = analyzer.evaluate_window(timeline, args.start_s, args.end_s)
        print(score.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
