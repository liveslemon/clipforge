"""CLI entrypoint for testing and executing Module 1 (Stream Ingest & Inspection)."""
from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path

from .inspector import MediaInspector
from .downloader import StreamDownloader, detect_platform_and_type
from .segmenter import VideoSegmenter


def main():
    parser = argparse.ArgumentParser(description="ClipForge Ingest & Stream Inspector CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # probe command
    probe_parser = subparsers.add_parser("probe", help="Inspect a local video or remote stream")
    probe_parser.add_argument("target", help="File path or stream URL")

    # detect command
    detect_parser = subparsers.add_parser("detect", help="Detect stream platform and media type from URL")
    detect_parser.add_argument("url", help="Stream or clip URL")

    # segment command
    seg_parser = subparsers.add_parser("segment", help="Losslessly segment a video file")
    seg_parser.add_argument("video_path", help="Path to input video")
    seg_parser.add_argument("output_dir", help="Output directory for chunks")
    seg_parser.add_argument("--seconds", type=int, default=1800, help="Segment duration in seconds (default: 1800)")

    # resolve-twitch command
    twitch_parser = subparsers.add_parser("resolve-twitch", help="Resolve Twitch clip information")
    twitch_parser.add_argument("clip_url", help="Twitch clip URL or slug")

    args = parser.parse_args()

    if args.command == "probe":
        inspector = MediaInspector()
        meta = inspector.inspect(args.target)
        print(meta.model_dump_json(indent=2))

    elif args.command == "detect":
        platform, media_type = detect_platform_and_type(args.url)
        print(json.dumps({"url": args.url, "platform": platform.value, "media_type": media_type.value}, indent=2))

    elif args.command == "segment":
        segmenter = VideoSegmenter()
        chunks = segmenter.segment_file(args.video_path, args.output_dir, args.seconds)
        print(f"Generated {len(chunks)} chunks:")
        for c in chunks:
            print(f"  Chunk {c.index}: {c.file_path} (Start: {c.start_time_s}s, Dur: {c.duration_s:.2f}s, Size: {c.size_bytes} bytes)")

    elif args.command == "resolve-twitch":
        downloader = StreamDownloader()
        info = downloader.resolve_twitch_clip(args.clip_url)
        print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
