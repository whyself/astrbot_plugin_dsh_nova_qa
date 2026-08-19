"""Pure routing helpers for QQ group and friend messages."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from typing import Any

DEFAULT_DSH_BASE_URL = "http://127.0.0.1:3081"
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_PRIVATE_CAC = re.compile(r"^/cac(?:\s+(?P<query>.*))?$", re.IGNORECASE | re.DOTALL)


def resolve_base_url(configured: str, environment: Mapping[str, str]) -> str:
    """Resolve the DSH endpoint from WebUI config, environment, then loopback."""

    candidate = configured.strip() or environment.get("DSH_BASE_URL", "").strip()
    return (candidate or DEFAULT_DSH_BASE_URL).rstrip("/")


def _normalize_whitelist(values: Iterable[object]) -> frozenset[str]:
    normalized = {str(value).strip() for value in values if value is not None}
    normalized.discard("")
    return frozenset(normalized)


def normalize_group_whitelist(values: Iterable[object]) -> frozenset[str]:
    """Normalize AstrBot list values into comparable QQ group IDs."""

    return _normalize_whitelist(values)


def normalize_user_whitelist(values: Iterable[object]) -> frozenset[str]:
    """Normalize AstrBot list values into comparable QQ user IDs."""

    return _normalize_whitelist(values)


def _safe_session_part(value: str) -> str:
    normalized = value.strip()
    if normalized and _SAFE_ID.fullmatch(normalized):
        return normalized
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def build_session_id(bot_id: str, group_id: str) -> str:
    """Build one filesystem-safe, stable DSH Session ID per bot/group pair."""

    return f"qq-group-{_safe_session_part(bot_id)}-{_safe_session_part(group_id)}"


def build_private_session_id(bot_id: str, sender_id: str) -> str:
    """Build one filesystem-safe, stable DSH Session ID per bot/friend pair."""

    return f"qq-private-{_safe_session_part(bot_id)}-{_safe_session_part(sender_id)}"


def extract_private_cac_query(text: str) -> str | None:
    """Return an exact private `/cac` command's question or None for non-matches."""

    match = _PRIVATE_CAC.fullmatch(text.strip())
    if match is None:
        return None
    return (match.group("query") or "").strip()


def is_slash_command(text: str) -> bool:
    """Return whether text is reserved for AstrBot's slash-command handlers."""

    return text.lstrip().startswith("/")


def has_direct_mention(messages: Iterable[object], bot_id: str, at_type: type) -> bool:
    """Return whether the message chain contains an At targeting this bot."""

    return any(
        isinstance(component, at_type) and str(getattr(component, "qq", "")) == bot_id
        for component in messages
    )


def _component_text(component: object, attribute: str) -> str:
    value = getattr(component, attribute, "")
    return "" if value is None else str(value).strip()


def extract_mentions(
    messages: Iterable[object],
    bot_id: str,
    at_type: type,
) -> list[dict[str, str]]:
    """Return non-bot QQ mentions with adapter-resolved display names."""

    mentions: list[dict[str, str]] = []
    for component in messages:
        if not isinstance(component, at_type):
            continue
        user_id = _component_text(component, "qq")
        if not user_id or user_id in {bot_id, "all"}:
            continue
        mention = {"user_id": user_id}
        display_name = _component_text(component, "name")
        if display_name:
            mention["display_name"] = display_name
        mentions.append(mention)
    return mentions


def extract_reply_to(
    messages: Iterable[object],
    bot_id: str,
    reply_type: type,
) -> dict[str, str] | None:
    """Return structured context for the first quoted QQ message."""

    reply = next(
        (component for component in messages if isinstance(component, reply_type)),
        None,
    )
    if reply is None:
        return None

    context: dict[str, str] = {
        "message_id": _component_text(reply, "id"),
        "sender_name": _component_text(reply, "sender_nickname"),
        "text": _component_text(reply, "message_str"),
    }
    sender_id = _component_text(reply, "sender_id")
    if sender_id and sender_id != "0":
        context["sender_id"] = sender_id
        context["sender_role"] = "assistant" if sender_id == bot_id else "user"
    return {key: value for key, value in context.items() if value}


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
    trigger: str = "at_bot",
    mentions: list[dict[str, str]] | None = None,
    reply_to: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return the stable sender and source fields passed to the NOVA Persona."""

    metadata: dict[str, Any] = {
        "source_type": "qq_group",
        "platform": platform,
        "platform_id": platform_id,
        "bot_id": bot_id,
        "group_id": group_id,
        "message_id": message_id,
        "timestamp": timestamp,
        "sender_id": sender_id,
        "sender_name": sender_name,
        "trigger": trigger,
    }
    if mentions:
        metadata["mentions"] = mentions
    if reply_to is not None:
        metadata["reply_to"] = reply_to
    return metadata


def build_private_source_metadata(
    *,
    sender_id: str,
    sender_name: str,
    message_id: str,
    timestamp: int,
    bot_id: str,
    platform: str,
    platform_id: str,
) -> dict[str, Any]:
    """Return stable QQ friend fields passed to the NOVA Persona."""

    return {
        "source_type": "qq_private",
        "platform": platform,
        "platform_id": platform_id,
        "bot_id": bot_id,
        "peer_id": sender_id,
        "message_id": message_id,
        "timestamp": timestamp,
        "sender_id": sender_id,
        "sender_name": sender_name,
        "trigger": "slash_cac",
    }
