"""ClipForge End-to-End Modular Pipeline Demo.

Demonstrates the entire stream clipping loop using all 10 independent modules:
1. Ingestion & Inspection (Module 1)
2. Audio Prep & Waveforms (Module 2)
3. Speech-to-Text & Word Timings (Module 3)
4. Acoustic Signals & Energy (Module 4)
5. Chat Velocity & Spike Engine (Module 5)
6. Vision & Facecam Tracker (Module 6)
7. Multi-Signal Highlight Scorer (Module 7)
8. Video Render Compositor (Module 8)
9. Rights Authorization Engine (Module 9)
10. Social Publishing Adapters (Module 10)
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

# Module Imports
from modules.module_01_stream_ingest import MediaInspector
from modules.module_02_audio_prep import MediaPreprocessor
from modules.module_03_transcription import MockTranscriptionProvider
from modules.module_04_audio_signals import AcousticAnalyzer
from modules.module_05_chat_analyzer import ChatMessage, ChatVelocityEngine
from modules.module_06_vision_analyzer import FacecamTracker, BoundingBox
from modules.module_07_highlight_scorer import HighlightScorer, NichePreset
from modules.module_08_video_render import RenderSpec, RenderLayout, CaptionStyle, VideoCompositor
from modules.module_09_rights_engine import RightsManager, PermittedUse
from modules.module_10_publishing import (
    PublisherService,
    PlatformConnection,
    PostMeta,
    Destination,
    PublishPrivacy,
)


def create_demo_video(out_path: Path):
    """Generates a synthetic 12-second 1080p stream sample with video and audio."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=12:size=1920x1080:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


async def main():
    print("=" * 70)
    print("🚀 CLIPFORGE MODULAR STREAM CLIPPING PIPELINE DEMO")
    print("=" * 70)

    work_dir = Path("./demo_output")
    work_dir.mkdir(exist_ok=True)
    raw_video = work_dir / "stream_vod_sample.mp4"

    # Step 0: Ensure sample video exists
    print("\n[Step 0] Synthesizing 12s 1080p stream sample with FFmpeg...")
    create_demo_video(raw_video)
    print(f"  ✓ Created: {raw_video}")

    # Module 1: Stream Ingestion & Inspection
    print("\n[Module 1] Inspecting stream metadata with ffprobe...")
    inspector = MediaInspector()
    meta = inspector.inspect(raw_video)
    print(f"  ✓ Format: {meta.format_name}, Duration: {meta.duration_seconds:.2f}s")
    print(f"  ✓ Video: {meta.primary_video.width}x{meta.primary_video.height} @ {meta.primary_video.fps} fps")
    print(f"  ✓ Audio: {meta.primary_audio.codec_name} ({meta.primary_audio.sample_rate} Hz, {meta.primary_audio.channels} ch)")
    print(f"  ✓ Fast SHA-256: {meta.sha256_hash[:16]}...")

    # Module 2: Audio Prep & Proxy Transcoding
    print("\n[Module 2] Extracting 16kHz mono audio, generating waveform & 720p proxy...")
    preprocessor = MediaPreprocessor()
    prep_res = preprocessor.process_all(raw_video, work_dir, extract_thumbnails_flag=True)
    print(f"  ✓ 16kHz Mono WAV: {Path(prep_res.audio_wav_path).name}")
    print(f"  ✓ 720p Web Proxy: {Path(prep_res.proxy_video_path).name}")
    print(f"  ✓ Waveform JSON: {Path(prep_res.waveform_json_path).name}")

    # Module 3: Speech-to-Text & Word Timings
    print("\n[Module 3] Running STT to extract word-level timestamps...")
    stt_provider = MockTranscriptionProvider(sample_script=[
        {"speaker": "Streamer", "text": "Wait did you see that incredible shot?!", "start_ms": 1000},
        {"speaker": "Streamer", "text": "Oh my god no way! Clip that right now!", "start_ms": 5000},
        {"speaker": "Streamer", "text": "That was the best clutch of the night.", "start_ms": 8500},
    ])
    transcript = await stt_provider.transcribe(prep_res.audio_wav_path)
    print(f"  ✓ Transcribed {len(transcript.segments)} segments, {len(transcript.all_words)} timed words.")
    print(f"  ✓ Sample snippet: \"{transcript.full_text}\"")

    # Module 4: Acoustic Signals & Energy Spikes
    print("\n[Module 4] Extracting acoustic loudness Z-scores and speech density...")
    acoustic_analyzer = AcousticAnalyzer()
    audio_timeline = acoustic_analyzer.analyze_wav(prep_res.audio_wav_path)
    print(f"  ✓ Analyzed {audio_timeline.duration_s}s timeline ({len(audio_timeline.points)} points)")
    print(f"  ✓ Baseline RMS mean: {audio_timeline.baseline_rms_mean}, std: {audio_timeline.baseline_rms_std}")

    # Module 5: Live Stream Chat Velocity
    print("\n[Module 5] Ingesting stream chat and calculating reaction velocity...")
    chat_engine = ChatVelocityEngine(lag_compensation_s=4.0)
    chat_msgs = [
        ChatMessage(timestamp_s=2.0, author="mod", text="let's go"),
        ChatMessage(timestamp_s=5.5, author="viewer1", text="OMG KEKW CLIP IT", emotes=["kekw"]),
        ChatMessage(timestamp_s=5.8, author="viewer2", text="CLIP IT BRO THAT WAS INSANE KEKW", emotes=["kekw"]),
        ChatMessage(timestamp_s=6.0, author="viewer3", text="POGGERS KEKW", emotes=["pog"]),
        ChatMessage(timestamp_s=6.2, author="viewer4", text="NO WAY KEKW", emotes=["kekw"]),
    ]
    chat_score = chat_engine.score_window(chat_msgs, 1.0, 5.0)
    print(f"  ✓ Chat Spike Peak Rate: {chat_score.peak_msg_rate:.1f} msg/s")
    print(f"  ✓ 'CLIP IT' Trigger Detected: {chat_score.has_clip_it_trigger}")
    print(f"  ✓ S_chat Score: {chat_score.score}")

    # Module 6: Vision & Facecam Tracker
    print("\n[Module 6] Tracking facecam overlay and determining stream layout...")
    vision_tracker = FacecamTracker(frame_width=1920, frame_height=1080)
    raw_faces = [
        (0.0, BoundingBox(x=1500, y=50, width=350, height=350), 0.95),
        (2.0, BoundingBox(x=1510, y=55, width=350, height=350), 0.95),
    ]
    smoothed_faces = vision_tracker.smooth_face_tracks(raw_faces)
    layout, face_box = vision_tracker.detect_stream_layout(smoothed_faces)
    print(f"  ✓ Detected Stream Layout: {layout.value}")
    print(f"  ✓ Facecam Box: {face_box}")

    # Module 7: Multi-Signal Highlight Scoring
    print("\n[Module 7] Computing composite C_score(w) and ranking candidates...")
    scorer = HighlightScorer(acoustic_analyzer=acoustic_analyzer, chat_engine=chat_engine)
    candidates = scorer.find_candidates(
        transcript=transcript,
        audio_timeline=audio_timeline,
        chat_messages=chat_msgs,
        preset=NichePreset.GAMING,
        min_duration_s=4.0,
        max_duration_s=10.0,
        stride_s=2.0,
        max_candidates=3,
    )
    print(f"  ✓ Found {len(candidates)} ranked highlight candidates:")
    top_cand = candidates[0]
    for idx, c in enumerate(candidates, 1):
        print(f"    #{idx}: [{c.start_s:.1f}s -> {c.end_s:.1f}s] Score: {c.score}/100 — \"{c.title}\"")
        print(f"        Reason: {c.reason}")

    # Module 9: Rights & Creator Authorization Engine
    print("\n[Module 9] Verifying creator authorization & rights attestation...")
    rights_mgr = RightsManager()
    rights_mgr.register_owner_attestation("workspace_alpha", "asset_101", "streamer_user")
    rights_check = rights_mgr.check_permission("workspace_alpha", "asset_101", PermittedUse.PUBLISH)
    print(f"  ✓ Rights Status: {'ALLOWED' if rights_check.allowed else 'BLOCKED'}")
    print(f"  ✓ Details: {rights_check.reason}")

    # Module 8: Render Spec Engine & Video Compositor
    print(f"\n[Module 8] Rendering top highlight #{top_cand.id} to 9:16 vertical split-screen MP4...")
    output_clip = work_dir / "highlight_clip_vertical.mp4"
    spec = RenderSpec(
        source_media_path=str(raw_video),
        in_s=top_cand.start_s,
        out_s=top_cand.end_s,
        layout=RenderLayout.SPLIT,
        face_region=(1500, 50, 350, 350),
        game_region=(0, 0, 1920, 1080),
    )
    spec.captions.style = CaptionStyle.WORD_HIGHLIGHT
    spec.captions.enabled = True

    compositor = VideoCompositor()
    render_res = compositor.render(spec, output_clip, words=transcript.all_words)
    print(f"  ✓ Rendered Vertical Short: {render_res.output_path}")
    print(f"  ✓ Resolution: {render_res.width}x{render_res.height} (9:16)")
    print(f"  ✓ Size: {render_res.file_size_bytes} bytes, Duration: {render_res.duration_s:.2f}s")

    # Module 10: Social Publishing & Packaging
    print("\n[Module 10] Executing publishing preflight & generating export bundle...")
    pub_service = PublisherService(rights_manager=rights_mgr)
    conn = PlatformConnection(
        id="conn_local",
        destination=Destination.LOCAL_EXPORT,
        account_name="clipforge_user",
        access_token="none",
    )
    meta = PostMeta(
        title=top_cand.title,
        caption=f"{top_cand.title}! Highlight scored {top_cand.score}/100 by ClipForge AI.",
        hashtags=["twitch", "streamer", "highlight", "gaming", "shorts"],
        privacy=PublishPrivacy.PUBLIC,
    )
    pub_res = await pub_service.execute_publish(
        workspace_id="workspace_alpha",
        media_asset_id="asset_101",
        clip_version_id="ver_final",
        media_path=str(output_clip),
        duration_s=render_res.duration_s,
        is_vertical=True,
        connection=conn,
        meta=meta,
    )
    print(f"  ✓ Status: {pub_res.status.value.upper()}")
    print(f"  ✓ Export Package: {pub_res.post_url}")
    print(f"  ✓ Idempotency Key: {pub_res.idempotency_key}")

    print("\n" + "=" * 70)
    print("🎉 CLIPFORGE DEMO COMPLETED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
