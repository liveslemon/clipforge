"""YouTube Shorts publisher: YouTube Data API v3 videos.insert (resumable upload) via google-api-python-client.

Live mode (conn.dry_run=False) uses OAuth credentials saved by `python -m modules.module_10_publishing.youtube_auth`
(or conn.access_token/refresh_token). Projects that have not passed Google's API compliance audit can only upload
private videos — enforced here. A vertical video ≤ 3 minutes is classified as a Short automatically.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Optional

from ...config import get_settings
from ..models import (
    Destination,
    PlatformConnection,
    PostMeta,
    PreflightResult,
    PublishJobState,
    PublishPrivacy,
    PublishResult,
)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
GAMING_CATEGORY_ID = "20"


class YouTubeAPIError(Exception):
    pass


def load_credentials(conn: Optional[PlatformConnection] = None):
    """OAuth credentials from the saved token file (refreshed and re-saved when expired)."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    s = get_settings()
    token_file = Path(s.youtube_token_file)
    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    elif conn and conn.access_token and conn.access_token != "simulated":
        creds = Credentials(token=conn.access_token, refresh_token=conn.refresh_token,
                            token_uri="https://oauth2.googleapis.com/token", scopes=SCOPES)
    if creds is None:
        raise YouTubeAPIError("No YouTube credentials. Run: python -m modules.module_10_publishing.youtube_auth")
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        if token_file.exists():
            token_file.write_text(creds.to_json())
    return creds


class YouTubeShortsPublisher:
    destination: Destination = Destination.YOUTUBE_SHORTS

    async def preflight(
        self,
        conn: PlatformConnection,
        media_path: str,
        duration_s: float,
        is_vertical: bool,
    ) -> PreflightResult:
        warnings = []
        forced_privacy = None

        if not is_vertical:
            warnings.append("Video is not vertical (9:16) — YouTube may not classify it as a Short.")

        if duration_s > 180.0:
            return PreflightResult(
                eligible=False,
                warnings=["YouTube Shorts must be <= 3 minutes (180 seconds)."],
                error_code="duration_exceeded",
            )

        if not conn.is_audited:
            warnings.append("Project is awaiting YouTube API compliance audit. Upload will be locked to PRIVATE.")
            forced_privacy = PublishPrivacy.PRIVATE

        if conn.daily_posts_remaining <= 0:
            return PreflightResult(
                eligible=False,
                warnings=["Daily YouTube upload quota exceeded."],
                error_code="quota_exceeded",
            )

        return PreflightResult(
            eligible=True,
            warnings=warnings,
            forced_privacy=forced_privacy,
        )

    @staticmethod
    def build_body(conn: PlatformConnection, meta: PostMeta) -> dict:
        privacy = PublishPrivacy.PRIVATE if not conn.is_audited else meta.privacy
        if privacy == PublishPrivacy.INBOX_DRAFT:
            privacy = PublishPrivacy.PRIVATE
        return {
            "snippet": {
                "title": meta.title[:100],
                "description": meta.full_caption_text[:5000],
                "tags": [t.lstrip("#") for t in meta.hashtags][:30],
                "categoryId": GAMING_CATEGORY_ID,
            },
            "status": {
                "privacyStatus": privacy.value,
                "selfDeclaredMadeForKids": False,
                "containsSyntheticMedia": False,
                **({"publishAt": meta.scheduled_at.isoformat()} if meta.scheduled_at and privacy == PublishPrivacy.PRIVATE else {}),
            },
        }

    async def publish(
        self,
        conn: PlatformConnection,
        media_path: str,
        meta: PostMeta,
        idempotency_key: str,
    ) -> PublishResult:
        body = self.build_body(conn, meta)
        if conn.dry_run:
            fake_video_id = f"yt_{uuid.uuid4().hex[:11]}"
            return PublishResult(
                status=PublishJobState.PUBLISHED,
                destination=self.destination,
                idempotency_key=idempotency_key,
                external_post_id=fake_video_id,
                post_url=f"https://youtube.com/shorts/{fake_video_id}",
                raw_response={"id": fake_video_id, "dry_run": True, **body},
            )
        try:
            video = await asyncio.to_thread(self._upload_live, conn, media_path, body)
        except Exception as e:  # googleapiclient HttpError, auth errors, network errors
            return PublishResult(status=PublishJobState.FAILED, destination=self.destination,
                                 idempotency_key=idempotency_key, error_message=f"{type(e).__name__}: {e}")
        return PublishResult(
            status=PublishJobState.PUBLISHED,
            destination=self.destination,
            idempotency_key=idempotency_key,
            external_post_id=video["id"],
            post_url=f"https://youtube.com/shorts/{video['id']}",
            raw_response={"id": video["id"], "status": video.get("status", {}), "dry_run": False},
        )

    def _upload_live(self, conn: PlatformConnection, media_path: str, body: dict) -> dict:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        youtube = build("youtube", "v3", credentials=load_credentials(conn), cache_discovery=False)
        media = MediaFileUpload(media_path, mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            _, response = request.next_chunk()
        return response

    async def check_status(self, conn: PlatformConnection, external_id: str) -> PublishJobState:
        if conn.dry_run:
            return PublishJobState.PUBLISHED

        def fetch():
            from googleapiclient.discovery import build
            youtube = build("youtube", "v3", credentials=load_credentials(conn), cache_discovery=False)
            items = youtube.videos().list(part="status,processingDetails", id=external_id).execute().get("items", [])
            return items[0] if items else None

        item = await asyncio.to_thread(fetch)
        if not item:
            return PublishJobState.FAILED
        upload = item.get("status", {}).get("uploadStatus")
        return {"processed": PublishJobState.PUBLISHED, "uploaded": PublishJobState.PROCESSING,
                "failed": PublishJobState.FAILED, "rejected": PublishJobState.FAILED}.get(upload, PublishJobState.PROCESSING)
