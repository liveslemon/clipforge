"""CLI tool for Module 7: Multi-signal highlight scoring and candidate ranking."""
from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path

from .composite_scorer import HighlightScorer
from .models import NichePreset
from ..module_03_transcription.models import Transcript
from ..module_04_audio_signals.models import AudioSignalsTimeline
from ..module_05_chat_analyzer.chat_parser import ChatParser


def main():
    parser = argparse.ArgumentParser(description="ClipForge Multi-Signal Highlight Scorer CLI")
    parser.add_argument("--transcript", required=True, help="Path to transcript JSON")
    parser.add_argument("--audio-signals", required=True, help="Path to audio signals timeline JSON")
    parser.add_argument("--chat", help="Path to chat log (.json or .txt)")
    parser.add_argument("--preset", default="GAMING", choices=[p.value for p in NichePreset])
    parser.add_argument("--limit", type=int, default=5, help="Number of candidates to return")

    args = parser.parse_args()

    # Load transcript
    with open(args.transcript, "r") as f:
        transcript = Transcript.model_validate(json.load(f))

    # Load audio signals
    with open(args.audio_signals, "r") as f:
        audio_timeline = AudioSignalsTimeline.model_validate(json.load(f))

    # Load chat if provided
    chat_msgs = None
    if args.chat:
        chat_msgs = ChatParser.from_file(args.chat)

    scorer = HighlightScorer()
    preset_enum = NichePreset(args.preset)

    candidates = scorer.find_candidates(
        transcript=transcript,
        audio_timeline=audio_timeline,
        chat_messages=chat_msgs,
        preset=preset_enum,
        max_candidates=args.limit,
    )

    print(f"Discovered {len(candidates)} highlight candidates ({args.preset} preset):")
    for i, c in enumerate(candidates, 1):
        print(f"\n[{i}] Score: {c.score}/100 — '{c.title}'")
        print(f"    Window: {c.start_s:.1f}s -> {c.end_s:.1f}s ({c.duration_s}s)")
        print(f"    Reason: {c.reason}")
        print(f"    Components: Hook={c.components.s_hook}, Energy={c.components.s_energy}, Chat={c.components.s_chat}, Narr={c.components.s_narrative}, DeadAir={c.components.p_dead}")
        print(f"    Snippet: \"{c.transcript_snippet}\"")


if __name__ == "__main__":
    main()
