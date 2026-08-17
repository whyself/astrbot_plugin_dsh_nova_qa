"""Pure routing helpers for QQ group messages."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from typing import Any

DEFAULT_DSH_BASE_URL = "http://127.0.0.1:3081"
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def resolve_base_url(configured: str, environment: Mapping[str, str]) -> str:
    """Resolve the DSH endpoint from WebUI config, environment, then loopback."""

    candidate = configured.strip() or environment.get("DSH_BASE_URL", "").strip()
    return (candidate or DEFAULT_DSH_BASE_URL).rstrip("/")


def normalize_group_whitelist(values: Iterable[object]) -> frozenset[str]:
    """Normalize AstrBot list values into comparable QQ group IDs."""

    normalized = {str(value).strip() for value in values if value is not None}
    normalized.discard("")
    return frozenset(normalized)


def _safe_session_part(value: str) -> str:
    normalized = value.strip()
    if normalized and _SAFE_ID.fullmatch(normalized):
        return normalized
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def build_session_id(bot_id: str, group_id: str) -> str:
    """Build one filesystem-safe, stable DSH Session ID per bot/group pair."""

    return f"qq-group-{_safe_session_part(bot_id)}-{_safe_session_part(group_id)}"


def has_direct_mention(messages: Iterable[object], bot_id: str, at_type: type) -> bool:
    """Return whether the message chain contains an At targeting this bot."""

    return any(
        isinstance(component, at_type) and str(getattr(component, "qq", "")) == bot_id
        for component in messages
    )


def build_source_metadata(
    *,
    sender_id: str,
    sender_name: str,
    group_id: str,
    message_id: str,
    timestamp: int,
    bot_id: str,
    platform: str,
    platform_id: str,
) -> dict[str, Any]:
    """Return the stable sender and source fields passed to the NOVA Persona."""

    return {
        "source_type": "qq_group",
        "platform": platform,
        "platform_id": platform_id,
        "bot_id": bot_id,
        "group_id": group_id,
        "message_id": message_id,
        "timestamp": timestamp,
        "sender_id": sender_id,
        "sender_name": sender_name,
        "trigger": "at_bot",
    }
