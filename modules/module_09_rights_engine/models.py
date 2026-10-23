"""Data models for content rights, creator grants, and permissions."""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, Set
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class PermittedUse(str, Enum):
    EDIT = "edit"
    DOWNLOAD = "download"
    PUBLISH = "publish"
    COMMERCIAL = "commercial"
    WHITE_LABEL = "white_label"
    MONETIZE = "monetize"


class GrantorType(str, Enum):
    OWNER = "owner"
    CREATOR_GRANT = "creator_grant"
    LICENSE = "license"
    TWITCH_ROLE = "twitch_role"


class ContentRights(BaseModel):
    id: str
    workspace_id: str
    media_asset_id: str
    grantor_type: GrantorType
    grantor_user_id: Optional[str] = None
    permitted_uses: Set[PermittedUse] = Field(default_factory=set)
    attestation_text_version: str = "v1.0"
    attested_ip: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and datetime.now(timezone.utc) > self.expires_at:
            return False
        return True


class CreatorGrant(BaseModel):
    id: str
    creator_user_id: str
    grantee_workspace_id: str
    channels: List[str] = Field(default_factory=list)  # Twitch/YouTube/Kick channel names or IDs
    permitted_uses: Set[PermittedUse] = Field(default_factory=set)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and datetime.now(timezone.utc) > self.expires_at:
            return False
        return True


class RightsCheckResult(BaseModel):
    allowed: bool
    requested_use: PermittedUse
    media_asset_id: str
    workspace_id: str
    reason: str
    active_rights_id: Optional[str] = None
