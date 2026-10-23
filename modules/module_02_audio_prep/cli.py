"""CLI tool for Module 2: Audio extraction, waveform generation, and proxy transcoding."""
from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path

from .audio_extractor import AudioExtractor
from .waveform_generator import WaveformGenerator
from .proxy_transcoder import MediaPreprocessor


def main():
    parser = argparse.ArgumentParser(description="ClipForge Audio Prep & Transcoder CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # extract-audio
    audio_parser = subparsers.add_parser("extract-audio", help="Extract 16kHz mono WAV from media")
    audio_parser.add_argument("media_file", help="Input media file")
    audio_parser.add_argument("output_wav", help="Output WAV path")

    # waveform
    wf_parser = subparsers.add_parser("waveform", help="Generate waveform JSON from WAV")
    wf_parser.add_argument("wav_file", help="Input WAV file")
    wf_parser.add_argument("output_json", help="Output JSON path")
    wf_parser.add_argument("--interval", type=float, default=0.1, help="Bucket interval in seconds (default: 0.1)")

    # proxy
    proxy_parser = subparsers.add_parser("proxy", help="Generate 720p proxy MP4")
    proxy_parser.add_argument("media_file", help="Input media file")
    proxy_parser.add_argument("output_proxy", help="Output MP4 path")

    # prep-all
    prep_parser = subparsers.add_parser("prep-all", help="Perform full media prep (audio, proxy, waveform, thumbs)")
    prep_parser.add_argument("media_file", help="Input media file")
    prep_parser.add_argument("output_dir", help="Output directory for generated assets")

    args = parser.parse_args()

    if args.command == "extract-audio":
        extractor = AudioExtractor()
        out = extractor.extract_stt_audio(args.media_file, args.output_wav)
        print(f"Extracted STT audio: {out}")

    elif args.command == "waveform":
        generator = WaveformGenerator(bucket_interval_s=args.interval)
        data = generator.generate(args.wav_file, args.output_json)
        print(f"Generated waveform with {len(data.points)} points (duration: {data.duration_s}s)")

    elif args.command == "proxy":
        prep = MediaPreprocessor()
        out = prep.generate_proxy_video(args.media_file, args.output_proxy)
        print(f"Generated 720p proxy: {out}")

    elif args.command == "prep-all":
        prep = MediaPreprocessor()
        res = prep.process_all(args.media_file, args.output_dir)
        print("Media preparation complete:")
        print(res.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
