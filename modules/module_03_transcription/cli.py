"""CLI tool for Module 3: Speech-to-Text, aligner, and subtitle exporter."""
from __future__ import annotations

import sys
import json
import asyncio
import argparse
from pathlib import Path

from .models import Transcript
from .providers.mock_provider import MockTranscriptionProvider
from .providers.assemblyai_provider import AssemblyAIProvider
from .segmenter_aligner import TranscriptAligner
from .exporters import SubtitleExporter


async def run_transcription(audio_file: str, provider_name: str, language: str) -> Transcript:
    if provider_name == "assemblyai":
        provider = AssemblyAIProvider()
    else:
        provider = MockTranscriptionProvider()

    return await provider.transcribe(audio_file, language=language)


def main():
    parser = argparse.ArgumentParser(description="ClipForge STT & Subtitle CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # transcribe
    tr_parser = subparsers.add_parser("transcribe", help="Transcribe audio file")
    tr_parser.add_argument("audio_file", help="Input audio WAV/MP3")
    tr_parser.add_argument("--provider", default="mock", choices=["mock", "assemblyai"])
    tr_parser.add_argument("--language", default="en")
    tr_parser.add_argument("--output-json", help="Save transcript JSON")
    tr_parser.add_argument("--output-srt", help="Save subtitles SRT")

    # snap-boundary
    snap_parser = subparsers.add_parser("snap-boundary", help="Snap timestamp to sentence start and end")
    snap_parser.add_argument("transcript_json", help="Path to transcript JSON")
    snap_parser.add_argument("target_ms", type=int, help="Target timestamp in ms")

    args = parser.parse_args()

    if args.command == "transcribe":
        transcript = asyncio.run(run_transcription(args.audio_file, args.provider, args.language))
        print(f"Transcription complete: {len(transcript.segments)} segments, {len(transcript.all_words)} words.")
        print(f"Duration: {transcript.duration_seconds:.2f}s")
        print(f"Sample: {transcript.full_text[:120]}...")

        if args.output_json:
            SubtitleExporter.to_json(transcript, args.output_json)
            print(f"Saved JSON: {args.output_json}")

        if args.output_srt:
            SubtitleExporter.to_srt(transcript, args.output_srt)
            print(f"Saved SRT: {args.output_srt}")

    elif args.command == "snap-boundary":
        with open(args.transcript_json, "r") as f:
            data = json.load(f)
        transcript = Transcript.model_validate(data)
        aligner = TranscriptAligner(transcript)

        start_ms = aligner.snap_start_boundary(args.target_ms)
        end_ms = aligner.snap_end_boundary(args.target_ms + 15000)
        print(f"Target: {args.target_ms}ms")
        print(f"Snapped Start: {start_ms}ms (diff: {args.target_ms - start_ms}ms)")
        print(f"Snapped End: {end_ms}ms (diff: {end_ms - (args.target_ms + 15000)}ms)")


if __name__ == "__main__":
    main()
