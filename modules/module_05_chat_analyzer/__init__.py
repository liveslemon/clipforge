"""Live Stream Chat Velocity & Spike Engine for ClipForge."""

from .models import (
    ChatMessage,
    ChatMetricsPoint,
    ChatScore,
)
from .chat_parser import (
    ChatParser,
    parse_timestamp_str,
    KNOWN_EMOTES,
)
from .velocity_engine import (
    ChatVelocityEngine,
    CLIP_KEYWORDS,
)

__all__ = [
    "ChatMessage",
    "ChatMetricsPoint",
    "ChatScore",
    "ChatParser",
    "parse_timestamp_str",
    "KNOWN_EMOTES",
    "ChatVelocityEngine",
    "CLIP_KEYWORDS",
]
