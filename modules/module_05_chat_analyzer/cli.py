"""CLI tool for Module 5: Chat parsing and velocity spike analysis."""
from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path

from .chat_parser import ChatParser
from .velocity_engine import ChatVelocityEngine


def main():
    parser = argparse.ArgumentParser(description="ClipForge Chat Analyzer CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # parse
    parse_parser = subparsers.add_parser("parse", help="Parse a chat log file")
    parse_parser.add_argument("chat_file", help="Path to chat file (.json or .txt)")
    parse_parser.add_argument("--limit", type=int, default=10, help="Number of messages to display")

    # score-window
    score_parser = subparsers.add_parser("score-window", help="Compute S_chat for on-stream time window")
    score_parser.add_argument("chat_file", help="Path to chat file")
    score_parser.add_argument("start_s", type=float, help="On-stream start time in seconds")
    score_parser.add_argument("end_s", type=float, help="On-stream end time in seconds")

    args = parser.parse_args()

    if args.command == "parse":
        msgs = ChatParser.from_file(args.chat_file)
        print(f"Parsed {len(msgs)} messages. First {min(len(msgs), args.limit)}:")
        for m in msgs[: args.limit]:
            print(f"[{m.timestamp_s:.1f}s] {m.author}: {m.text} (emotes: {m.emotes})")

    elif args.command == "score-window":
        msgs = ChatParser.from_file(args.chat_file)
        engine = ChatVelocityEngine()
        score = engine.score_window(msgs, args.start_s, args.end_s)
        print(score.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
