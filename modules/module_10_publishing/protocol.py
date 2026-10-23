"""Protocol definition for social platform publishers."""
from __future__ import annotations

from typing import Protocol
from .models import (
    Destination,
    PlatformConnection,
    PostMeta,
    PreflightResult,
    PublishResult,
    PublishJobState,
)


class PlatformPublisher(Protocol):
    """Protocol matching Blueprint Section 9.3 for platform publishing adapters."""

    destination: Destination

    async def preflight(
        self,
        conn: PlatformConnection,
        media_path: str,
        duration_s: float,
        is_vertical: bool,
    ) -> PreflightResult:
        """Validates format restrictions, daily quotas, account type, and audit gates."""
        ...

    async def publish(
        self,
        conn: PlatformConnection,
        media_path: str,
        meta: PostMeta,
        idempotency_key: str,
    ) -> PublishResult:
        """Executes the publish or upload operation with idempotency."""
        ...

    async def check_status(
        self,
        conn: PlatformConnection,
        external_id: str,
    ) -> PublishJobState:
        """Checks asynchronous processing status on the platform."""
        ...
