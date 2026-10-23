"""Data models for social publishing, platform connections, and job states."""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class Destination(str, Enum):
    YOUTUBE_SHORTS = "youtube_shorts"
    TIKTOK = "tiktok"
    INSTAGRAM_REELS = "instagram_reels"
    LOCAL_EXPORT = "local_export"


class PublishPrivacy(str, Enum):
    PUBLIC = "public"
    UNLISTED = "unlisted"
    PRIVATE = "private"
    INBOX_DRAFT = "inbox_draft"


class PublishJobState(str, Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"
    NEEDS_USER_ACTION = "needs_user_action"


class PlatformConnection(BaseModel):
    id: str
    destination: Destination
    account_name: str
    avatar_url: Optional[str] = None
    access_token: str
    is_audited: bool = False             # Unaudited TikTok/YouTube apps lock uploads to private
    is_professional_account: bool = True # Required for Instagram Reels
    daily_posts_remaining: int = 15
    token_expires_at: Optional[datetime] = None
    refresh_token: Optional[str] = None
    # Safety default: adapters simulate the platform call. Set False (with real credentials) to actually post.
    dry_run: bool = True


class PostMeta(BaseModel):
    title: str
    caption: str
    hashtags: List[str] = Field(default_factory=list)
    privacy: PublishPrivacy = PublishPrivacy.PUBLIC
    commercial_content_disclosure: bool = False
    scheduled_at: Optional[datetime] = None

    @property
    def full_caption_text(self) -> str:
        tags = " ".join(f"#{tag.lstrip('#')}" for tag in self.hashtags)
        return f"{self.caption}\n\n{tags}".strip()


class PreflightResult(BaseModel):
    eligible: bool
    warnings: List[str] = Field(default_factory=list)
    forced_privacy: Optional[PublishPrivacy] = None
    error_code: Optional[str] = None


class PublishResult(BaseModel):
    status: PublishJobState
    destination: Destination
    idempotency_key: str
    external_post_id: Optional[str] = None
    post_url: Optional[str] = None
    error_message: Optional[str] = None
    raw_response: Dict[str, Any] = Field(default_factory=dict)
