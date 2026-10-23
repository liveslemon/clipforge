"""Stream and clip downloader / scraper module for Twitch, Kick, YouTube, and direct URLs."""
from __future__ import annotations

import re
import os
import time
import requests
from pathlib import Path
from typing import Optional, Callable, Dict, Any, Tuple
from urllib.parse import urlparse

from .models import StreamPlatform, MediaType


class DownloaderError(Exception):
    pass


def detect_platform_and_type(url: str) -> Tuple[StreamPlatform, MediaType]:
    """Classifies a URL into a StreamPlatform and MediaType."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()

    if "twitch.tv" in domain:
        if "/clip/" in path or "clips.twitch.tv" in domain:
            return StreamPlatform.TWITCH, MediaType.CLIP
        elif "/videos/" in path:
            return StreamPlatform.TWITCH, MediaType.VOD
        else:
            return StreamPlatform.TWITCH, MediaType.LIVESTREAM

    elif "youtube.com" in domain or "youtu.be" in domain:
        if "/shorts/" in path:
            return StreamPlatform.YOUTUBE, MediaType.CLIP
        elif "/live" in path:
            return StreamPlatform.YOUTUBE, MediaType.LIVESTREAM
        else:
            return StreamPlatform.YOUTUBE, MediaType.VOD

    elif "kick.com" in domain:
        if "/videos/" in path:
            return StreamPlatform.KICK, MediaType.VOD
        elif "/clips/" in path:
            return StreamPlatform.KICK, MediaType.CLIP
        else:
            return StreamPlatform.KICK, MediaType.LIVESTREAM

    return StreamPlatform.DIRECT_URL, MediaType.RAW_UPLOAD


class StreamDownloader:
    """Handles downloading and scraping stream media from web sources."""

    def __init__(self, output_dir: str | Path = "./downloads", user_agent: Optional[str] = None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent or "ClipForge-Ingest/1.0 (+https://clipforge.app)"
        })

    def download_direct_file(
        self,
        url: str,
        dest_filename: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        chunk_size: int = 1024 * 1024,
    ) -> Path:
        """Downloads a direct video/media URL with streaming chunks and progress tracking."""
        if not dest_filename:
            dest_filename = os.path.basename(urlparse(url).path) or f"download_{int(time.time())}.mp4"
            if not any(dest_filename.endswith(ext) for ext in [".mp4", ".mov", ".mkv", ".ts"]):
                dest_filename += ".mp4"

        dest_path = self.output_dir / dest_filename

        try:
            with self.session.get(url, stream=True, timeout=30) as r:
                r.raise_for_status()
                total_bytes = int(r.headers.get("Content-Length", 0))
                downloaded_bytes = 0

                with open(dest_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            downloaded_bytes += len(chunk)
                            if progress_callback:
                                progress_callback(downloaded_bytes, total_bytes)

        except requests.RequestException as e:
            if dest_path.exists():
                dest_path.unlink()
            raise DownloaderError(f"Failed to download media from {url}: {e}") from e

        return dest_path

    def resolve_twitch_clip(
        self,
        clip_url_or_id: str,
        client_id: Optional[str] = None,
        auth_token: Optional[str] = None,
        editor_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resolves a Twitch clip through the official Helix API (Get Clips + Get Clips Download).

        A download URL is only returned when a broadcaster/editor user token is available (auth_token or
        TWITCH_USER_ACCESS_TOKEN) — Twitch does not allow third parties to download other people's clips.
        """
        from .twitch_client import TwitchAPIError, TwitchClient, clip_slug

        slug = clip_slug(clip_url_or_id)
        client = TwitchClient(client_id=client_id, user_access_token=auth_token, session=self.session)
        if not client.configured:
            return {"slug": slug, "title": f"Twitch Clip {slug}", "source_url": clip_url_or_id,
                    "resolved_at": time.time(), "note": "Set TWITCH_CLIENT_ID/TWITCH_CLIENT_SECRET to resolve metadata."}
        try:
            clip = client.get_clip(slug)
        except TwitchAPIError as e:
            raise DownloaderError(str(e)) from e
        info = {
            "slug": slug,
            "title": clip.get("title"),
            "broadcaster_id": clip.get("broadcaster_id"),
            "broadcaster_name": clip.get("broadcaster_name"),
            "creator_name": clip.get("creator_name"),
            "video_id": clip.get("video_id"),
            "vod_offset": clip.get("vod_offset"),
            "game_id": clip.get("game_id"),
            "duration": clip.get("duration"),
            "thumbnail_url": clip.get("thumbnail_url"),
            "download_url": None,
        }
        if client.user_token:
            try:
                urls = client.get_clip_download_urls([slug], clip["broadcaster_id"], editor_id or clip["broadcaster_id"])
                if urls:
                    info["download_url"] = urls[0].get("landscape_download_url") or urls[0].get("portrait_download_url")
            except TwitchAPIError as e:
                info["download_error"] = str(e)
        return info
