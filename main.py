"""Route allowlisted QQ group mentions and private `/cac` commands to DSH."""

from __future__ import annotations

import os
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import At, Plain
from astrbot.api.star import Context, Star, register

from .dsh_client import DshClient, DshError
from .routing import (
    build_private_session_id,
    build_private_source_metadata,
    build_session_id,
    build_source_metadata,
    extract_private_cac_query,
    has_direct_mention,
    is_slash_command,
    normalize_group_whitelist,
    normalize_user_whitelist,
    resolve_base_url,
)

SUPPORTED_QQ_PLATFORMS = frozenset({"aiocqhttp", "qq_official", "qq_official_webhook"})
GROUP_HANDLER_PRIORITY = 50


def _config_number(config: AstrBotConfig, key: str, default: float) -> float:
    value: Any = config.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number")
    return float(value)


def _raw_plain_text(event: AstrMessageEvent) -> str:
    """Return original Plain components before AstrBot command normalization."""

    text = "".join(
        component.text for component in event.get_messages() if isinstance(component, Plain)
    ).strip()
    return text or event.get_message_str().strip()


def _message_timestamp(event: AstrMessageEvent) -> int:
    """Return the source timestamp or zero when the adapter value is invalid."""

    timestamp = getattr(event.message_obj, "timestamp", 0)
    if isinstance(timestamp, int):
        return timestamp
    try:
        return int(timestamp)
    except (TypeError, ValueError):
        return 0


@register(
    "astrbot_plugin_dsh_nova_qa",
    "whyself",
    "把白名单 QQ 群 @提问及白名单好友 /cac 私聊转发给 DSH NOVA 知识库",
    "1.1.1",
)
class DshNovaQaPlugin(Star):
    """Route each allowlisted QQ group or friend to a stable NOVA QA Session."""

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        raw_groups = config.get("group_whitelist", [])
        if not isinstance(raw_groups, list):
            raise ValueError("group_whitelist must be a list")
        raw_users = config.get("user_whitelist", [])
        if not isinstance(raw_users, list):
            raise ValueError("user_whitelist must be a list")

        self.group_whitelist = normalize_group_whitelist(raw_groups)
        self.user_whitelist = normalize_user_whitelist(raw_users)
        self.dsh_base_url = resolve_base_url(str(config.get("dsh_base_url", "")), os.environ)
        self.dsh = DshClient(
            self.dsh_base_url,
            request_timeout_seconds=_config_number(config, "request_timeout_seconds", 15),
            response_timeout_seconds=_config_number(config, "response_timeout_seconds", 180),
            poll_interval_seconds=_config_number(config, "poll_interval_seconds", 0.5),
        )

    async def initialize(self) -> None:
        """Report non-sensitive routing configuration after plugin load."""

        logger.info(
            "DSH NOVA QA plugin loaded: endpoint=%s, allowlisted_groups=%d, allowlisted_users=%d",
            self.dsh_base_url,
            len(self.group_whitelist),
            len(self.user_whitelist),
        )

    @filter.event_message_type(
        filter.EventMessageType.GROUP_MESSAGE,
        priority=GROUP_HANDLER_PRIORITY,
    )
    async def on_group_message(self, event: AstrMessageEvent):
        """Answer direct bot mentions from configured QQ groups."""

        if event.get_platform_name() not in SUPPORTED_QQ_PLATFORMS:
            return
        group_id = str(event.get_group_id()).strip()
        if group_id not in self.group_whitelist:
            return

        bot_id = str(event.get_self_id()).strip()
        if not bot_id or event.get_sender_id() == bot_id:
            return
        if not has_direct_mention(event.get_messages(), bot_id, At):
            return

        question = _raw_plain_text(event)
        if is_slash_command(question):
            return

        event.stop_event()
        if not question:
            yield event.plain_result("请在 @机器人 后写上问题。")
            return

        message = event.message_obj
        metadata = build_source_metadata(
            sender_id=event.get_sender_id(),
            sender_name=event.get_sender_name(),
            group_id=group_id,
            message_id=str(getattr(message, "message_id", "")),
            timestamp=_message_timestamp(event),
            bot_id=bot_id,
            platform=event.get_platform_name(),
            platform_id=event.get_platform_id(),
        )
        session_id = build_session_id(bot_id, group_id)

        try:
            answer = await self.dsh.ask(session_id, metadata, question)
        except DshError:
            logger.exception("DSH NOVA QA request failed")
            yield event.plain_result("知识库服务暂时不可用，请稍后再试。")
            return

        yield event.plain_result(answer)

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    @filter.command("cac", priority=100)
    async def on_private_cac(self, event: AstrMessageEvent):
        """Answer literal `/cac` questions from configured QQ friends."""

        if event.get_platform_name() not in SUPPORTED_QQ_PLATFORMS:
            return
        sender_id = str(event.get_sender_id()).strip()
        if not sender_id or sender_id not in self.user_whitelist:
            return

        bot_id = str(event.get_self_id()).strip()
        if not bot_id or sender_id == bot_id:
            return

        question = extract_private_cac_query(_raw_plain_text(event))
        if question is None:
            return

        event.stop_event()
        if not question:
            yield event.plain_result("用法: /cac <问题>")
            return

        message = event.message_obj
        metadata = build_private_source_metadata(
            sender_id=sender_id,
            sender_name=event.get_sender_name(),
            message_id=str(getattr(message, "message_id", "")),
            timestamp=_message_timestamp(event),
            bot_id=bot_id,
            platform=event.get_platform_name(),
            platform_id=event.get_platform_id(),
        )
        session_id = build_private_session_id(bot_id, sender_id)

        try:
            answer = await self.dsh.ask(session_id, metadata, question)
        except DshError:
            logger.exception("DSH NOVA QA private request failed")
            yield event.plain_result("知识库服务暂时不可用，请稍后再试。")
            return

        yield event.plain_result(answer)

    async def terminate(self) -> None:
        """Close outbound HTTP connections during unload or update."""

        await self.dsh.close()
