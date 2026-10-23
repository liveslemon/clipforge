"""CLI tool for Module 8: Video rendering and subtitle burning from RenderSpec."""
from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path

from .models import RenderSpec, RenderLayout, CaptionStyle
from .ffmpeg_compositor import VideoCompositor
from ..module_03_transcription.models import Transcript


def main():
    parser = argparse.ArgumentParser(description="ClipForge Video Render Compositor CLI")
    parser.add_argument("source_video", help="Source media file path")
    parser.add_argument("output_mp4", help="Output vertical MP4 file path")
    parser.add_argument("--in-s", type=float, default=0.0, help="Start time in seconds")
    parser.add_argument("--out-s", type=float, default=15.0, help="End time in seconds")
    parser.add_argument("--layout", default="split", choices=["split", "crop", "fit"], help="Layout preset")
    parser.add_argument("--transcript", help="Optional transcript JSON for animated captions")
    parser.add_argument("--style", default="word_highlight", choices=["word_highlight", "bold_pop", "clean"])

    args = parser.parse_args()

    words = None
    if args.transcript:
        with open(args.transcript, "r") as f:
            data = json.load(f)
        tr = Transcript.model_validate(data)
        words = tr.all_words

    spec = RenderSpec(
        source_media_path=args.source_video,
        in_s=args.in_s,
        out_s=args.out_s,
        layout=RenderLayout(args.layout),
    )
    spec.captions.style = CaptionStyle(args.style)
    spec.captions.enabled = bool(words)

    compositor = VideoCompositor()
    print(f"Rendering {args.layout} clip [{args.in_s}s -> {args.out_s}s]...")
    res = compositor.render(spec, args.output_mp4, words=words)
    print(f"Render complete: {res.output_path}")
    print(f"Dimensions: {res.width}x{res.height}, Size: {res.file_size_bytes} bytes")


if __name__ == "__main__":
    main()
