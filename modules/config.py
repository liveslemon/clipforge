"""Central ClipForge configuration: every API key / external setting, loaded from environment or `.env`.

Copy `.env.example` to `.env` at the project root and fill in what you have. Every key is optional —
each feature falls back to a local/offline path when its key is missing (see `capability_report()`).
"""
from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models"


class ClipForgeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # Speech-to-text (Module 3)
    assemblyai_api_key: str = ""

    # LLM: clip selection, titles, caption proofreading (Modules 3 & 7)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    clipforge_llm_model: str = "claude-opus-5-5"

    # Twitch (Module 1): official Helix API
    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    twitch_user_access_token: str = ""  # needed only for clip downloads (editor:manage:clips / channel:manage:clips)

    # YouTube (Module 10): OAuth "Desktop app" client from Google Cloud Console
    youtube_client_secrets_file: str = ""
    youtube_token_file: str = str(PROJECT_ROOT / ".youtube_token.json")

    # TikTok (Module 10): Content Posting API user token with video.publish scope
    tiktok_access_token: str = ""

    # Hugging Face token (optional: faster/unthrottled model downloads)
    hf_token: str = ""


@lru_cache(maxsize=1)
def get_settings() -> ClipForgeSettings:
    return ClipForgeSettings()


def reload_settings() -> ClipForgeSettings:
    get_settings.cache_clear()
    return get_settings()


def ffmpeg_has_filter(name: str, ffmpeg_bin: str = "ffmpeg") -> bool:
    try:
        res = subprocess.run([ffmpeg_bin, "-hide_banner", "-h", f"filter={name}"], capture_output=True, text=True)
        return "Unknown filter" not in res.stdout + res.stderr
    except FileNotFoundError:
        return False


def _importable(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:
        return False


def capability_report() -> List[Dict[str, str]]:
    """What is set up, what each item unlocks, and how to fix it. status: ok | missing | optional."""
    s = get_settings()
    yt_secrets = Path(s.youtube_client_secrets_file) if s.youtube_client_secrets_file else None

    def row(name, ok, unlocks, fix, required=True):
        return {"name": name, "status": "ok" if ok else ("missing" if required else "optional"),
                "unlocks": unlocks, "fix": "" if ok else fix}

    return [
        row("FFmpeg", bool(shutil.which("ffmpeg")), "All media processing",
            "brew install ffmpeg-full"),
        row("FFmpeg with libass (burned-in captions)", ffmpeg_has_filter("ass"),
            "Captions burned into the MP4 — required for TikTok/Shorts/Reels",
            "brew uninstall ffmpeg && brew install ffmpeg-full"),
        row("FFmpeg loudnorm filter", ffmpeg_has_filter("loudnorm"), "EBU R128 loudness normalisation to -14 LUFS",
            "brew install ffmpeg-full"),
        row("AssemblyAI API key", bool(s.assemblyai_api_key),
            "Universal-3.5 Pro transcription with context prompt (best caption accuracy)",
            "Get a key at assemblyai.com/dashboard → set ASSEMBLYAI_API_KEY in .env"),
        row("LLM API key (OpenAI / Anthropic)", bool(s.openai_api_key or s.anthropic_api_key),
            f"AI picks self-contained, hooky clips, writes titles, proofreads captions ({s.openai_model if s.openai_api_key else s.clipforge_llm_model})",
            "Set OPENAI_API_KEY (or ANTHROPIC_API_KEY) in .env"),
        row("Local Whisper (fallback STT)", _importable("mlx_whisper") or _importable("faster_whisper"),
            "Offline transcription when no AssemblyAI key", "pip install mlx-whisper (Apple Silicon) or faster-whisper",
            required=False),
        row("YuNet face model", (MODELS_DIR / "face_detection_yunet_2023mar.onnx").exists(),
            "Face detection for facecam split + face-tracked reframing",
            "Downloads automatically on first use (needs internet once)"),
        row("PySceneDetect", _importable("scenedetect"), "Scene-cut detection", "pip install scenedetect"),
        row("PANNs audio-event model", _importable("panns_inference"),
            "Laughter / cheering / screaming detection for highlight scoring",
            "pip install panns-inference (downloads ~330 MB model on first run)", required=False),
        row("Twitch app credentials", bool(s.twitch_client_id and s.twitch_client_secret),
            "Import Twitch clips/VOD metadata via the official Helix API",
            "dev.twitch.tv/console → register app → TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET", required=False),
        row("YouTube OAuth client", bool(yt_secrets and yt_secrets.exists()),
            "Real YouTube Shorts uploads (private until Google's API audit passes)",
            "Google Cloud Console → enable YouTube Data API v3 → OAuth Desktop client → YOUTUBE_CLIENT_SECRETS_FILE",
            required=False),
        row("TikTok access token", bool(s.tiktok_access_token),
            "Real TikTok uploads (private/inbox-only until TikTok's audit passes)",
            "developers.tiktok.com → app with Content Posting API + Login Kit → TIKTOK_ACCESS_TOKEN", required=False),
    ]
