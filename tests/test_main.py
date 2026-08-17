from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest


class FakeAt:
    def __init__(self, qq: str) -> None:
        self.qq = qq


class FakePlain:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeDshClient:
    instances: ClassVar[list[FakeDshClient]] = []

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.calls: list[tuple[str, dict[str, Any], str]] = []
        self.closed = False
        self.instances.append(self)

    async def ask(
        self,
        session_id: str,
        metadata: dict[str, Any],
        question: str,
    ) -> str:
        self.calls.append((session_id, metadata, question))
        return "DSH answer"

    async def close(self) -> None:
        self.closed = True


class FakeEvent:
    def __init__(
        self,
        *,
        sender_id: str,
        text: str,
        private: bool,
        group_id: str = "",
        bot_id: str = "7",
        platform: str = "aiocqhttp",
    ) -> None:
        self.sender_id = sender_id
        self.text = text
        self.private = private
        self.group_id = group_id
        self.bot_id = bot_id
        self.platform = platform
        self.stopped = False
        message = [FakePlain(text)]
        if not private:
            message.insert(0, FakeAt(bot_id))
        self.message_obj = SimpleNamespace(
            message=message,
            message_id="message-1",
            timestamp=1787011200,
        )

    def get_platform_name(self) -> str:
        return self.platform

    def get_platform_id(self) -> str:
        return "qq-main"

    def get_group_id(self) -> str:
        return self.group_id

    def get_self_id(self) -> str:
        return self.bot_id

    def get_sender_id(self) -> str:
        return self.sender_id

    def get_sender_name(self) -> str:
        return "小明"

    def get_messages(self) -> list[object]:
        return self.message_obj.message

    def get_message_str(self) -> str:
        return self.text.removeprefix("/") if self.private else self.text

    def stop_event(self) -> None:
        self.stopped = True

    def plain_result(self, text: str) -> str:
        return text


def _install_astrbot_stubs() -> None:
    class AstrBotConfig(dict):
        pass

    class Context:
        pass

    class Star:
        def __init__(self, context: object) -> None:
            self.context = context

    class EventMessageType:
        GROUP_MESSAGE = object()
        PRIVATE_MESSAGE = object()

    class Filter:
        @staticmethod
        def event_message_type(message_type: object, **kwargs: object):
            def decorator(function):
                function._fake_message_type = message_type
                if "priority" in kwargs:
                    function._fake_priority = kwargs["priority"]
                return function

            return decorator

        @staticmethod
        def command(name: str, **kwargs: object):
            def decorator(function):
                function._fake_command = name
                function._fake_priority = kwargs.get(
                    "priority", getattr(function, "_fake_priority", 0)
                )
                return function

            return decorator

    Filter.EventMessageType = EventMessageType

    def register(*_args: object, **_kwargs: object):
        return lambda cls: cls

    api = types.ModuleType("astrbot.api")
    api.AstrBotConfig = AstrBotConfig
    api.logger = SimpleNamespace(info=lambda *_a, **_k: None, exception=lambda *_a, **_k: None)
    event = types.ModuleType("astrbot.api.event")
    event.AstrMessageEvent = object
    event.filter = Filter
    components = types.ModuleType("astrbot.api.message_components")
    components.At = FakeAt
    components.Plain = FakePlain
    star = types.ModuleType("astrbot.api.star")
    star.Context = Context
    star.Star = Star
    star.register = register
    astrbot = types.ModuleType("astrbot")
    astrbot.api = api
    sys.modules.update(
        {
            "astrbot": astrbot,
            "astrbot.api": api,
            "astrbot.api.event": event,
            "astrbot.api.message_components": components,
            "astrbot.api.star": star,
        }
    )


@pytest.fixture
def plugin_module(monkeypatch: pytest.MonkeyPatch):
    _install_astrbot_stubs()
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    module_name = "astrbot_plugin_dsh_nova_qa.main"
    sys.modules.pop(module_name, None)
    module = importlib.import_module(module_name)
    FakeDshClient.instances.clear()
    monkeypatch.setattr(module, "DshClient", FakeDshClient)
    return module


async def collect(handler) -> list[str]:
    return [item async for item in handler]


def handler_attribute(handler, name: str, default: object = None) -> object:
    function = getattr(handler, "__func__", handler)
    return getattr(function, name, default)


def handler_matches(handler, event: FakeEvent, private_message_type: object) -> bool:
    if handler_attribute(handler, "_fake_message_type") is not private_message_type:
        return False
    command = handler_attribute(handler, "_fake_command")
    if command is None:
        return True
    raw = event.text.strip().removeprefix("/")
    return raw == command or raw.startswith(f"{command} ")


async def dispatch_private(
    handlers: list,
    event: FakeEvent,
    private_message_type: object,
) -> list[str]:
    results: list[str] = []
    ordered = sorted(
        handlers,
        key=lambda handler: -int(handler_attribute(handler, "_fake_priority", 0)),
    )
    for handler in ordered:
        if event.stopped:
            break
        if handler_matches(handler, event, private_message_type):
            results.extend(await collect(handler(event)))
    return results


def make_plugin(module):
    return module.DshNovaQaPlugin(
        object(),
        {
            "dsh_base_url": "http://dsh-nova:3082",
            "group_whitelist": ["9"],
            "user_whitelist": ["42"],
        },
    )


@pytest.mark.asyncio
async def test_private_plain_message_is_released(plugin_module) -> None:
    plugin = make_plugin(plugin_module)
    event = FakeEvent(sender_id="42", text="普通私聊", private=True)

    assert await collect(plugin.on_private_cac(event)) == []
    assert not event.stopped
    assert plugin.dsh.calls == []


@pytest.mark.asyncio
async def test_private_cac_without_literal_slash_is_released(plugin_module) -> None:
    plugin = make_plugin(plugin_module)
    event = FakeEvent(sender_id="42", text="cac NOVA 是什么？", private=True)

    assert await collect(plugin.on_private_cac(event)) == []
    assert not event.stopped
    assert plugin.dsh.calls == []


@pytest.mark.asyncio
async def test_private_cac_requires_allowlisted_friend(plugin_module) -> None:
    plugin = make_plugin(plugin_module)
    event = FakeEvent(sender_id="99", text="/cac NOVA 是什么？", private=True)

    assert await collect(plugin.on_private_cac(event)) == []
    assert not event.stopped
    assert plugin.dsh.calls == []


@pytest.mark.asyncio
async def test_private_cac_routes_to_private_session_and_stops_event(plugin_module) -> None:
    plugin = make_plugin(plugin_module)
    event = FakeEvent(sender_id="42", text="/cac NOVA 是什么？", private=True)

    assert await collect(plugin.on_private_cac(event)) == ["DSH answer"]
    assert event.stopped
    assert plugin.dsh.calls == [
        (
            "qq-private-7-42",
            {
                "source_type": "qq_private",
                "platform": "aiocqhttp",
                "platform_id": "qq-main",
                "bot_id": "7",
                "peer_id": "42",
                "message_id": "message-1",
                "timestamp": 1787011200,
                "sender_id": "42",
                "sender_name": "小明",
                "trigger": "slash_cac",
            },
            "NOVA 是什么？",
        )
    ]


@pytest.mark.asyncio
async def test_private_empty_cac_reports_usage_without_calling_dsh(plugin_module) -> None:
    plugin = make_plugin(plugin_module)
    event = FakeEvent(sender_id="42", text="/cac", private=True)

    assert await collect(plugin.on_private_cac(event)) == ["用法: /cac <问题>"]
    assert event.stopped
    assert plugin.dsh.calls == []


@pytest.mark.asyncio
async def test_private_cac_priority_prevents_legacy_handler_from_stealing_message(
    plugin_module,
) -> None:
    plugin = make_plugin(plugin_module)
    event = FakeEvent(sender_id="42", text="/cac NOVA 是什么？", private=True)
    private_message_type = plugin_module.filter.EventMessageType.PRIVATE_MESSAGE

    async def legacy_cac(legacy_event: FakeEvent):
        legacy_event.stop_event()
        yield "legacy answer"

    legacy_cac._fake_message_type = private_message_type
    legacy_cac._fake_command = "cac"
    legacy_cac._fake_priority = 0

    assert handler_attribute(plugin.on_private_cac, "_fake_priority") == 100
    assert await dispatch_private(
        [legacy_cac, plugin.on_private_cac],
        event,
        private_message_type,
    ) == ["DSH answer"]
    assert plugin.dsh.calls[0][0] == "qq-private-7-42"


@pytest.mark.asyncio
async def test_group_slash_command_is_released_to_existing_plugins(plugin_module) -> None:
    plugin = make_plugin(plugin_module)
    event = FakeEvent(sender_id="42", text="/audit status", private=False, group_id="9")

    assert await collect(plugin.on_group_message(event)) == []
    assert not event.stopped
    assert plugin.dsh.calls == []
