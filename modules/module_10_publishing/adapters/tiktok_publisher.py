"""TikTok Content Posting API publisher adapter (developers.tiktok.com/doc/content-posting-api-*).

Live flow (conn.dry_run=False):
  1. POST /v2/post/publish/creator_info/query/   privacy options + max duration for this creator
  2. POST /v2/post/publish/video/init/            Direct Post (scope video.publish), or
     POST /v2/post/publish/inbox/video/init/      upload as a draft to the creator's inbox (scope video.upload)
  3. PUT  upload_url                              file in 5-64 MB chunks with Content-Range
  4. POST /v2/post/publish/status/fetch/          poll via check_status()
Unaudited TikTok apps may only post SELF_ONLY (private) — enforced here.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests

from ..models import (
    Destination,
    PlatformConnection,
    PostMeta,
    PreflightResult,
    PublishJobState,
    PublishPrivacy,
    PublishResult,
)

API = "https://open.tiktokapis.com/v2/post/publish"
MIN_CHUNK = 5_000_000
MAX_SINGLE_CHUNK = 64_000_000
CHUNK = 10_000_000


class TikTokAPIError(Exception):
    pass


def chunk_plan(video_size: int) -> Tuple[int, int]:
    """(chunk_size, total_chunk_count) per TikTok's media transfer rules: ≤64 MB in one piece, else 10 MB chunks
    with the remainder merged into the last chunk."""
    if video_size <= MAX_SINGLE_CHUNK:
        return video_size, 1
    return CHUNK, video_size // CHUNK


class TikTokPublisher:
    destination: Destination = Destination.TIKTOK

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()

    async def preflight(
        self,
        conn: PlatformConnection,
        media_path: str,
        duration_s: float,
        is_vertical: bool,
    ) -> PreflightResult:
        warnings = []
        forced_privacy = None

        if duration_s < 3.0 or duration_s > 600.0:
            return PreflightResult(
                eligible=False,
                warnings=["TikTok videos must be between 3 seconds and 10 minutes."],
                error_code="duration_invalid",
            )

        if not conn.is_audited:
            warnings.append("TikTok App Review pending. Upload forced to PRIVATE / INBOX_DRAFT.")
            forced_privacy = PublishPrivacy.INBOX_DRAFT

        if conn.daily_posts_remaining <= 0:
            return PreflightResult(
                eligible=False,
                warnings=["Daily TikTok post limit (~15 posts/creator/day) reached."],
                error_code="rate_limit_exceeded",
            )

        return PreflightResult(
            eligible=True,
            warnings=warnings,
            forced_privacy=forced_privacy,
        )

    async def publish(
        self,
        conn: PlatformConnection,
        media_path: str,
        meta: PostMeta,
        idempotency_key: str,
    ) -> PublishResult:
        inbox = meta.privacy == PublishPrivacy.INBOX_DRAFT
        if conn.dry_run:
            publish_id = f"tt_pub_{uuid.uuid4().hex[:12]}"
            mode = "UPLOAD_TO_INBOX" if (not conn.is_audited or inbox) else "DIRECT_POST"
            return PublishResult(
                status=PublishJobState.PUBLISHED,
                destination=self.destination,
                idempotency_key=idempotency_key,
                external_post_id=publish_id,
                post_url=f"https://www.tiktok.com/@{conn.account_name}/video/{publish_id}" if mode == "DIRECT_POST" else None,
                raw_response={"publish_id": publish_id, "mode": mode, "dry_run": True,
                              "commercial_disclosure": meta.commercial_content_disclosure},
            )
        try:
            return await asyncio.to_thread(self._publish_live, conn, Path(media_path), meta, idempotency_key, inbox)
        except (TikTokAPIError, requests.RequestException, OSError) as e:
            return PublishResult(status=PublishJobState.FAILED, destination=self.destination,
                                 idempotency_key=idempotency_key, error_message=str(e))

    # -- live API ---------------------------------------------------------------

    def _call(self, conn: PlatformConnection, path: str, body: Dict) -> Dict:
        res = self.session.post(f"{API}{path}", json=body, timeout=30, headers={
            "Authorization": f"Bearer {conn.access_token}", "Content-Type": "application/json; charset=UTF-8"})
        data = res.json() if res.content else {}
        err = data.get("error", {})
        if res.status_code != 200 or err.get("code", "ok") != "ok":
            raise TikTokAPIError(f"TikTok {path} failed ({res.status_code}): {err.get('code')} {err.get('message')}")
        return data.get("data", {})

    def choose_privacy(self, conn: PlatformConnection, meta: PostMeta, options: list) -> str:
        if not conn.is_audited or meta.privacy == PublishPrivacy.PRIVATE:
            return "SELF_ONLY"  # unaudited apps can only post privately
        if meta.privacy == PublishPrivacy.PUBLIC and "PUBLIC_TO_EVERYONE" in options:
            return "PUBLIC_TO_EVERYONE"
        for fallback in ("FOLLOWER_OF_CREATOR", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY"):
            if fallback in options:
                return fallback
        return "SELF_ONLY"

    def _publish_live(self, conn: PlatformConnection, path: Path, meta: PostMeta, key: str, inbox: bool) -> PublishResult:
        size = path.stat().st_size
        chunk_size, count = chunk_plan(size)
        source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk_size, "total_chunk_count": count}

        if inbox:
            init = self._call(conn, "/inbox/video/init/", {"source_info": source})
            mode = "UPLOAD_TO_INBOX"
        else:
            creator = self._call(conn, "/creator_info/query/", {})
            privacy = self.choose_privacy(conn, meta, creator.get("privacy_level_options", []))
            init = self._call(conn, "/video/init/", {
                "post_info": {
                    "title": meta.full_caption_text[:2200],
                    "privacy_level": privacy,
                    "disable_comment": bool(creator.get("comment_disabled")),
                    "disable_duet": bool(creator.get("duet_disabled")),
                    "disable_stitch": bool(creator.get("stitch_disabled")),
                    "brand_content_toggle": meta.commercial_content_disclosure,
                    "brand_organic_toggle": False,
                },
                "source_info": source,
            })
            mode = f"DIRECT_POST:{privacy}"

        upload_url = init["upload_url"]
        with open(path, "rb") as f:
            for i in range(count):
                start = i * chunk_size
                end = size - 1 if i == count - 1 else start + chunk_size - 1
                f.seek(start)
                body = f.read(end - start + 1)
                res = self.session.put(upload_url, data=body, timeout=300, headers={
                    "Content-Type": "video/mp4", "Content-Length": str(len(body)),
                    "Content-Range": f"bytes {start}-{end}/{size}"})
                if res.status_code not in (200, 201, 206):
                    raise TikTokAPIError(f"TikTok chunk {i + 1}/{count} upload failed ({res.status_code}): {res.text[:300]}")

        return PublishResult(
            status=PublishJobState.PROCESSING,
            destination=self.destination,
            idempotency_key=key,
            external_post_id=init["publish_id"],
            raw_response={"publish_id": init["publish_id"], "mode": mode, "chunks": count, "dry_run": False},
        )

    async def check_status(self, conn: PlatformConnection, external_id: str) -> PublishJobState:
        if conn.dry_run:
            return PublishJobState.PUBLISHED
        data = await asyncio.to_thread(self._call, conn, "/status/fetch/", {"publish_id": external_id})
        return {
            "PUBLISH_COMPLETE": PublishJobState.PUBLISHED,
            "FAILED": PublishJobState.FAILED,
            "SEND_TO_USER_INBOX": PublishJobState.NEEDS_USER_ACTION,
        }.get(data.get("status", ""), PublishJobState.PROCESSING)
