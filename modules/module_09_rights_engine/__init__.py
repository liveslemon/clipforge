"""Rights & Creator Authorization Module for ClipForge."""

from .models import (
    PermittedUse,
    GrantorType,
    ContentRights,
    CreatorGrant,
    RightsCheckResult,
)
from .rights_manager import RightsManager, RightsError

__all__ = [
    "PermittedUse",
    "GrantorType",
    "ContentRights",
    "CreatorGrant",
    "RightsCheckResult",
    "RightsManager",
    "RightsError",
]
