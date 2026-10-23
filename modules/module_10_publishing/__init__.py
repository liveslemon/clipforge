"""Social Publishing & Platform Adapters Module for ClipForge."""

from .models import (
    Destination,
    PublishPrivacy,
    PublishJobState,
    PlatformConnection,
    PostMeta,
    PreflightResult,
    PublishResult,
)
from .protocol import PlatformPublisher
from .adapters.youtube_publisher import YouTubeShortsPublisher
from .adapters.tiktok_publisher import TikTokPublisher
from .adapters.local_packager import LocalExportPackager
from .publisher_service import PublisherService

__all__ = [
    "Destination",
    "PublishPrivacy",
    "PublishJobState",
    "PlatformConnection",
    "PostMeta",
    "PreflightResult",
    "PublishResult",
    "PlatformPublisher",
    "YouTubeShortsPublisher",
    "TikTokPublisher",
    "LocalExportPackager",
    "PublisherService",
]
