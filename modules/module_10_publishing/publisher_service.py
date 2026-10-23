"""Publishing orchestrator service with idempotency and rights verification."""
from __future__ import annotations

import hashlib
from typing import Dict, Optional, List
from .models import (
    Destination,
    PlatformConnection,
    PostMeta,
    PublishResult,
    PublishJobState,
)
from .protocol import PlatformPublisher
from .adapters.youtube_publisher import YouTubeShortsPublisher
from .adapters.tiktok_publisher import TikTokPublisher
from .adapters.local_packager import LocalExportPackager
from ..module_09_rights_engine.rights_manager import RightsManager
from ..module_09_rights_engine.models import PermittedUse


class PublisherService:
    """Coordinates publishing jobs, idempotency checks, and content rights enforcement."""

    def __init__(self, rights_manager: Optional[RightsManager] = None):
        self.rights_manager = rights_manager or RightsManager()
        self.publishers: Dict[Destination, PlatformPublisher] = {
            Destination.YOUTUBE_SHORTS: YouTubeShortsPublisher(),
            Destination.TIKTOK: TikTokPublisher(),
            Destination.LOCAL_EXPORT: LocalExportPackager(),
        }
        # In-memory idempotency cache (in production backed by DB table)
        self.published_jobs: Dict[str, PublishResult] = {}

    def compute_idempotency_key(self, clip_version_id: str, account_id: str, destination: Destination) -> str:
        """Computes idempotency key matching Blueprint Section 3.7: clip_version_id + account_id + destination."""
        raw = f"{clip_version_id}:{account_id}:{destination.value}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    async def execute_publish(
        self,
        workspace_id: str,
        media_asset_id: str,
        clip_version_id: str,
        media_path: str,
        duration_s: float,
        is_vertical: bool,
        connection: PlatformConnection,
        meta: PostMeta,
    ) -> PublishResult:
        idempotency_key = self.compute_idempotency_key(clip_version_id, connection.id, connection.destination)

        # 1. Idempotency Check (Blueprint Section 3.7)
        if idempotency_key in self.published_jobs:
            existing = self.published_jobs[idempotency_key]
            if existing.status == PublishJobState.PUBLISHED:
                return existing

        # 2. Rights Gate (Blueprint Section 6.1)
        # Skip external publish rights check if exporting locally for personal use
        if connection.destination != Destination.LOCAL_EXPORT:
            rights_check = self.rights_manager.check_permission(workspace_id, media_asset_id, PermittedUse.PUBLISH)
            if not rights_check.allowed:
                return PublishResult(
                    status=PublishJobState.FAILED,
                    destination=connection.destination,
                    idempotency_key=idempotency_key,
                    error_message=f"Rights check failed: {rights_check.reason}",
                )

        # 3. Select Publisher Adapter
        publisher = self.publishers.get(connection.destination)
        if not publisher:
            return PublishResult(
                status=PublishJobState.FAILED,
                destination=connection.destination,
                idempotency_key=idempotency_key,
                error_message=f"No publisher registered for destination '{connection.destination.value}'",
            )

        # 4. Preflight Check
        preflight = await publisher.preflight(connection, media_path, duration_s, is_vertical)
        if not preflight.eligible:
            return PublishResult(
                status=PublishJobState.FAILED,
                destination=connection.destination,
                idempotency_key=idempotency_key,
                error_message="; ".join(preflight.warnings),
            )

        # 5. Execute Publish
        result = await publisher.publish(connection, media_path, meta, idempotency_key)
        self.published_jobs[idempotency_key] = result
        return result
