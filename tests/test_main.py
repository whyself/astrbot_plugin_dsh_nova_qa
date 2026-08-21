from __future__ import annotations

import asyncio
import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest


class FakeAt:
    def __init__(self, qq: str, name: str = "") -> None:
        self.qq = qq
        self.name = name


class FakePlain:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeReply:
    def __init__(
        self,
        *,
        id: str,
        chain: list[object] | None = None,
        sender_id: int | str | None = None,
        sender_nickname: str | None = None,
        time: int | None = None,
        message_str: str | None = None,
        text: str | None = None,
        qq: int | None = None,
        seq: int | None = None,
    ) -> None:
        self.id = id
        self.chain = chain
        self.sender_id = sender_id
        self.sender_nickname = sender_nickname
        self.time = time
        self.message_str = message_str
        self.text = text
        self.qq = qq
        self.seq = seq

    def to_onebot_dict(self) -> dict[str, object]:
        data = {key: value for key, value in vars(self).items() if value is not None}
        return {"type": "reply", "data": data}


class FakeNode:
    def __init__(
        self,
        *,
        uin: str | None,
        name: str | None,
        content: list[object],
    ) -> None:
        self.uin = uin
        self.name = name
        self.content = content


class FakeNodes:
    def __init__(self, nodes: list[FakeNode]) -> None:
        self.nodes = nodes


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
        message_id: str = "message-1",
        messages: list[object] | None = None,
    ) -> None:
        self.sender_id = sender_id
        self.text = text
        self.private = private
        self.group_id = group_id
        self.bot_id = bot_id
        self.platform = platform
        self.stopped = False
        self.call_llm = False
        message = messages if messages is not None else [FakePlain(text)]
        if messages is None and not private:
            message.insert(0, FakeAt(bot_id, "Novabot"))
        self.message_obj = SimpleNamespace(
            message=message,
            message_id=message_id,
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

    def should_call_llm(self, call_llm: bool) -> None:
        self.call_llm = call_llm

    def plain_result(self, text: str) -> str:
        return text

    def chain_result(self, chain: list[object]) -> list[object]:
        return chain


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
    components.Node = FakeNode
    components.Nodes = FakeNodes
    components.Plain = FakePlain
    components.Reply = FakeReply
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


async def collect(handler) -> list[object]:
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


async def dispatch_group(
    handlers: list,
    event: FakeEvent,
    group_message_type: object,
) -> list[str]:
    results: list[str] = []
    ordered = sorted(
        handlers,
        key=lambda handler: -int(handler_attribute(handler, "_fake_priority", 0)),
    )
    for handler in ordered:
        if event.stopped:
            break
        if handler_attribute(handler, "_fake_message_type") is group_message_type:
            invocation = handler(event)
            if hasattr(invocation, "__aiter__"):
                results.extend(await collect(invocation))
            else:
                await invocation
    return results


def core_default_llm(event: FakeEvent) -> list[str]:
    return [] if event.call_llm else ["default answer"]


def make_plugin(module, **overrides: object):
    config = {
        "dsh_base_url": "http://dsh-nova:3082",
        "group_whitelist": ["9"],
        "user_whitelist": ["42"],
    }
    config.update(overrides)
    return module.DshNovaQaPlugin(
        object(),
        config,
    )


def assert_group_reply(results: list[object], message_id: str, text: str) -> None:
    assert len(results) == 1
    chain = results[0]
    assert isinstance(chain, list)
    assert len(chain) == 2
    reply, plain = chain
    assert isinstance(reply, FakeReply)
    assert reply.id == message_id
    assert reply.chain is None
    assert reply.to_onebot_dict() == {
        "type": "reply",
        "data": {"id": message_id},
    }
    assert isinstance(plain, FakePlain)
    assert plain.text == text


def assert_forward_record(results: list[object], bot_id: str, text: str) -> None:
    assert len(results) == 1
    chain = results[0]
    assert isinstance(chain, list)
    assert len(chain) == 1
    nodes = chain[0]
    assert isinstance(nodes, FakeNodes)
    assert len(nodes.nodes) == 1
    node = nodes.nodes[0]
    assert isinstance(node, FakeNode)
    assert node.uin == bot_id
    assert node.name == "NovaBot"
    assert len(node.content) == 1
    plain = node.content[0]
    assert isinstance(plain, FakePlain)
    assert plain.text == text


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
async def test_private_long_answer_is_folded_into_forward_record(plugin_module) -> None:
    plugin = make_plugin(plugin_module, fold_response_threshold=10)
    answer = "私聊长回答" * 3

    async def long_ask(*_args: object) -> str:
        return answer

    plugin.dsh.ask = long_ask
    event = FakeEvent(sender_id="42", text="/cac 请详细说明", private=True)

    results = await collect(plugin.on_private_cac(event))

    assert_forward_record(results, "7", answer)
    assert event.stopped


@pytest.mark.asyncio
async def test_private_empty_cac_reports_usage_without_calling_dsh(plugin_module) -> None:
    plugin = make_plugin(plugin_module, fold_response_threshold=0)
    event = FakeEvent(sender_id="42", text="/cac", private=True)

    assert await collect(plugin.on_private_cac(event)) == ["用法: /cac <问题>"]
    assert event.stopped
    assert plugin.dsh.calls == []


@pytest.mark.asyncio
async def test_private_dsh_error_is_not_folded_at_zero_threshold(plugin_module) -> None:
    plugin = make_plugin(plugin_module, fold_response_threshold=0)

    async def failing_ask(*_args: object) -> str:
        raise plugin_module.DshError("failed")

    plugin.dsh.ask = failing_ask
    event = FakeEvent(sender_id="42", text="/cac NOVA 是什么？", private=True)

    assert await collect(plugin.on_private_cac(event)) == ["知识库服务暂时不可用，请稍后再试。"]
    assert event.stopped


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


@pytest.mark.asyncio
async def test_allowlisted_group_tail_guard_blocks_core_default_llm(
    plugin_module,
) -> None:
    plugin = make_plugin(plugin_module)
    event = FakeEvent(
        sender_id="42",
        text="普通群消息",
        private=False,
        group_id="9",
        messages=[FakePlain("普通群消息")],
    )
    group_message_type = plugin_module.filter.EventMessageType.GROUP_MESSAGE

    results = await dispatch_group(
        [
            plugin.suppress_allowlisted_group_default_llm,
            plugin.on_group_message,
        ],
        event,
        group_message_type,
    )

    assert results == []
    assert core_default_llm(event) == []
    assert not event.stopped
    assert plugin.dsh.calls == []


@pytest.mark.asyncio
async def test_allowlisted_group_tail_guard_runs_after_regular_plugins(
    plugin_module,
) -> None:
    plugin = make_plugin(plugin_module)
    event = FakeEvent(
        sender_id="42",
        text="插件消息",
        private=False,
        group_id="9",
        messages=[FakePlain("插件消息")],
    )
    group_message_type = plugin_module.filter.EventMessageType.GROUP_MESSAGE

    async def regular_plugin(_event: FakeEvent):
        yield "plugin answer"

    regular_plugin._fake_message_type = group_message_type
    regular_plugin._fake_priority = 0

    results = await dispatch_group(
        [plugin.suppress_allowlisted_group_default_llm, regular_plugin],
        event,
        group_message_type,
    )

    assert results == ["plugin answer"]
    assert core_default_llm(event) == []
    assert not event.stopped


@pytest.mark.asyncio
async def test_group_tail_guard_releases_non_allowlisted_groups(plugin_module) -> None:
    plugin = make_plugin(plugin_module)
    event = FakeEvent(
        sender_id="42",
        text="其他群消息",
        private=False,
        group_id="10",
        messages=[FakePlain("其他群消息")],
    )
    group_message_type = plugin_module.filter.EventMessageType.GROUP_MESSAGE

    results = await dispatch_group(
        [plugin.suppress_allowlisted_group_default_llm],
        event,
        group_message_type,
    )

    assert results == []
    assert core_default_llm(event) == ["default answer"]
    assert not event.stopped


@pytest.mark.asyncio
async def test_group_priority_claims_allowlisted_mention_before_generic_handler(
    plugin_module,
) -> None:
    plugin = make_plugin(plugin_module)
    event = FakeEvent(
        sender_id="42",
        text="NOVA 是什么？",
        private=False,
        group_id="9",
    )
    group_message_type = plugin_module.filter.EventMessageType.GROUP_MESSAGE

    async def generic_at_handler(generic_event: FakeEvent):
        generic_event.stop_event()
        yield "generic answer"

    generic_at_handler._fake_message_type = group_message_type
    generic_at_handler._fake_priority = 0

    assert handler_attribute(plugin.on_group_message, "_fake_priority") == 50
    results = await dispatch_group(
        [generic_at_handler, plugin.on_group_message],
        event,
        group_message_type,
    )
    assert_group_reply(results, "message-1", "DSH answer")
    assert plugin.dsh.calls[0][0] == "qq-group-7-9"


@pytest.mark.asyncio
async def test_group_metadata_keeps_mentioned_member_but_not_the_bot(
    plugin_module,
) -> None:
    plugin = make_plugin(plugin_module)
    event = FakeEvent(
        sender_id="42",
        text="评价一下这个人",
        private=False,
        group_id="9",
        messages=[
            FakeAt("7", "Novabot"),
            FakePlain("评价一下这个人"),
            FakeAt("24841951", "悉达多"),
        ],
    )

    assert_group_reply(
        await collect(plugin.on_group_message(event)),
        "message-1",
        "DSH answer",
    )
    session_id, metadata, question = plugin.dsh.calls[0]
    assert session_id == "qq-group-7-9"
    assert question == "评价一下这个人"
    assert metadata["mentions"] == [{"user_id": "24841951", "display_name": "悉达多"}]
    assert all(mention["user_id"] != "7" for mention in metadata["mentions"])


@pytest.mark.asyncio
async def test_direct_mention_with_reply_preserves_quote(
    plugin_module,
) -> None:
    plugin = make_plugin(plugin_module)
    event = FakeEvent(
        sender_id="42",
        text="刚才我说了什么。",
        private=False,
        group_id="9",
        messages=[
            FakeAt("7", "Novabot"),
            FakeReply(
                id="quoted-1",
                sender_id="7",
                sender_nickname="Novabot",
                message_str="此前的机器人回答",
            ),
            FakePlain("刚才我说了什么。"),
        ],
    )

    assert_group_reply(
        await collect(plugin.on_group_message(event)),
        "message-1",
        "DSH answer",
    )
    assert event.stopped
    assert plugin.dsh.calls == [
        (
            "qq-group-7-9",
            {
                "source_type": "qq_group",
                "platform": "aiocqhttp",
                "platform_id": "qq-main",
                "bot_id": "7",
                "group_id": "9",
                "message_id": "message-1",
                "timestamp": 1787011200,
                "sender_id": "42",
                "sender_name": "小明",
                "trigger": "at_bot",
                "reply_to": {
                    "message_id": "quoted-1",
                    "sender_id": "7",
                    "sender_name": "Novabot",
                    "sender_role": "assistant",
                    "text": "此前的机器人回答",
                },
            },
            "刚才我说了什么。",
        )
    ]


@pytest.mark.asyncio
async def test_reply_to_group_member_without_bot_mention_is_released(
    plugin_module,
) -> None:
    plugin = make_plugin(plugin_module)
    event = FakeEvent(
        sender_id="42",
        text="这句话是什么意思？",
        private=False,
        group_id="9",
        messages=[
            FakeReply(
                id="quoted-member",
                sender_id="99",
                sender_nickname="小红",
                message_str="普通群员发言",
            ),
            FakePlain("这句话是什么意思？"),
        ],
    )

    assert await collect(plugin.on_group_message(event)) == []
    assert not event.stopped
    assert plugin.dsh.calls == []


@pytest.mark.asyncio
async def test_primary_handler_releases_reply_to_bot_without_direct_mention(
    plugin_module,
) -> None:
    plugin = make_plugin(plugin_module)
    event = FakeEvent(
        sender_id="42",
        text="刚才我说了什么。",
        private=False,
        group_id="9",
        messages=[
            FakeReply(
                id="quoted-bot",
                sender_id="7",
                sender_nickname="Novabot",
                message_str="此前的机器人回答",
            ),
            FakePlain("刚才我说了什么。"),
        ],
    )

    assert await collect(plugin.on_group_message(event)) == []
    assert not event.stopped
    assert plugin.dsh.calls == []


@pytest.mark.asyncio
async def test_reply_to_bot_without_direct_mention_is_blocked_from_default_llm(
    plugin_module,
) -> None:
    plugin = make_plugin(plugin_module)
    event = FakeEvent(
        sender_id="42",
        text="为什么会使用 DSH？",
        private=False,
        group_id="9",
        messages=[
            FakeReply(
                id="quoted-bot",
                sender_id="7",
                sender_nickname="Novabot",
                message_str="此前的机器人回答",
            ),
            FakePlain("为什么会使用 DSH？"),
        ],
    )
    group_message_type = plugin_module.filter.EventMessageType.GROUP_MESSAGE

    results = await dispatch_group(
        [
            plugin.suppress_allowlisted_group_default_llm,
            plugin.on_group_message,
        ],
        event,
        group_message_type,
    )

    assert results == []
    assert core_default_llm(event) == []
    assert not event.stopped
    assert plugin.dsh.calls == []


@pytest.mark.asyncio
async def test_group_response_quotes_the_triggering_message(plugin_module) -> None:
    plugin = make_plugin(plugin_module)
    event = FakeEvent(
        sender_id="42",
        text="NOVA 是什么？",
        private=False,
        group_id="9",
        message_id="question-123",
    )

    results = await collect(plugin.on_group_message(event))

    assert_group_reply(results, "question-123", "DSH answer")


@pytest.mark.asyncio
async def test_empty_group_prompt_is_not_folded_at_zero_threshold(plugin_module) -> None:
    plugin = make_plugin(plugin_module, fold_response_threshold=0)
    event = FakeEvent(
        sender_id="42",
        text="",
        private=False,
        group_id="9",
        message_id="empty-question",
    )

    results = await collect(plugin.on_group_message(event))

    assert_group_reply(results, "empty-question", "请在 @机器人 后写上问题。")
    assert plugin.dsh.calls == []


@pytest.mark.asyncio
async def test_group_long_answer_is_folded_without_reply_component(plugin_module) -> None:
    plugin = make_plugin(plugin_module, fold_response_threshold=10)
    answer = "群聊长回答" * 3

    async def long_ask(*_args: object) -> str:
        return answer

    plugin.dsh.ask = long_ask
    event = FakeEvent(
        sender_id="42",
        text="请详细说明",
        private=False,
        group_id="9",
        message_id="question-long",
    )

    results = await collect(plugin.on_group_message(event))

    assert_forward_record(results, "7", answer)


@pytest.mark.asyncio
async def test_answer_at_fold_threshold_keeps_normal_group_reply(plugin_module) -> None:
    answer = "DSH answer"
    plugin = make_plugin(plugin_module, fold_response_threshold=len(answer))
    event = FakeEvent(sender_id="42", text="问题", private=False, group_id="9")

    results = await collect(plugin.on_group_message(event))

    assert_group_reply(results, "message-1", answer)


@pytest.mark.asyncio
async def test_fold_disabled_keeps_long_group_reply(plugin_module) -> None:
    plugin = make_plugin(
        plugin_module,
        fold_long_responses=False,
        fold_response_threshold=0,
    )
    event = FakeEvent(sender_id="42", text="问题", private=False, group_id="9")

    results = await collect(plugin.on_group_message(event))

    assert_group_reply(results, "message-1", "DSH answer")


@pytest.mark.asyncio
async def test_non_aiocqhttp_long_answer_keeps_normal_group_reply(plugin_module) -> None:
    plugin = make_plugin(plugin_module, fold_response_threshold=0)
    event = FakeEvent(
        sender_id="42",
        text="问题",
        private=False,
        group_id="9",
        platform="qq_official",
    )

    results = await collect(plugin.on_group_message(event))

    assert_group_reply(results, "message-1", "DSH answer")


@pytest.mark.asyncio
async def test_group_stops_propagation_only_after_yielding_its_reply(
    plugin_module,
) -> None:
    plugin = make_plugin(plugin_module)
    event = FakeEvent(
        sender_id="42",
        text="NOVA 是什么？",
        private=False,
        group_id="9",
        message_id="question-123",
    )
    handler = plugin.on_group_message(event)

    reply = await anext(handler)

    assert_group_reply([reply], "question-123", "DSH answer")
    assert event.call_llm
    assert not event.stopped
    with pytest.raises(StopAsyncIteration):
        await anext(handler)
    assert event.stopped


@pytest.mark.asyncio
async def test_group_dsh_error_quotes_the_triggering_message(plugin_module) -> None:
    plugin = make_plugin(plugin_module, fold_response_threshold=0)

    async def failing_ask(*_args: object) -> str:
        raise plugin_module.DshError("failed")

    plugin.dsh.ask = failing_ask
    event = FakeEvent(
        sender_id="42",
        text="NOVA 是什么？",
        private=False,
        group_id="9",
        message_id="failed-question",
    )

    results = await collect(plugin.on_group_message(event))

    assert_group_reply(
        results,
        "failed-question",
        "知识库服务暂时不可用，请稍后再试。",
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("fold_long_responses", "true"),
        ("fold_response_threshold", -1),
        ("fold_response_threshold", True),
    ],
)
def test_fold_configuration_rejects_invalid_values(
    plugin_module,
    key: str,
    value: object,
) -> None:
    with pytest.raises(ValueError):
        make_plugin(plugin_module, **{key: value})


@pytest.mark.asyncio
async def test_same_session_questions_wait_and_reply_in_fifo_order(plugin_module) -> None:
    plugin = make_plugin(plugin_module)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()
    completed: list[str] = []

    async def controlled_ask(
        _session_id: str,
        _metadata: dict[str, Any],
        question: str,
    ) -> str:
        if question == "第一问":
            first_started.set()
            await release_first.wait()
        else:
            second_started.set()
        completed.append(question)
        return f"回答: {question}"

    plugin.dsh.ask = controlled_ask
    first_event = FakeEvent(
        sender_id="41",
        text="第一问",
        private=False,
        group_id="9",
        message_id="first",
    )
    second_event = FakeEvent(
        sender_id="42",
        text="第二问",
        private=False,
        group_id="9",
        message_id="second",
    )

    first_task = asyncio.create_task(collect(plugin.on_group_message(first_event)))
    await first_started.wait()
    second_task = asyncio.create_task(collect(plugin.on_group_message(second_event)))
    await asyncio.sleep(0)

    assert not second_started.is_set()
    release_first.set()
    first_results, second_results = await asyncio.gather(first_task, second_task)

    assert completed == ["第一问", "第二问"]
    assert_group_reply(first_results, "first", "回答: 第一问")
    assert_group_reply(second_results, "second", "回答: 第二问")


@pytest.mark.asyncio
async def test_empty_group_mention_waits_for_prior_session_answer(plugin_module) -> None:
    plugin = make_plugin(plugin_module)
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def controlled_ask(*_args: object) -> str:
        first_started.set()
        await release_first.wait()
        return "第一问回答"

    plugin.dsh.ask = controlled_ask
    first_event = FakeEvent(
        sender_id="41",
        text="第一问",
        private=False,
        group_id="9",
        message_id="first",
    )
    empty_event = FakeEvent(
        sender_id="42",
        text="",
        private=False,
        group_id="9",
        message_id="empty",
    )

    first_task = asyncio.create_task(collect(plugin.on_group_message(first_event)))
    await first_started.wait()
    empty_task = asyncio.create_task(collect(plugin.on_group_message(empty_event)))
    await asyncio.sleep(0)

    assert not empty_task.done()
    release_first.set()
    first_results, empty_results = await asyncio.gather(first_task, empty_task)

    assert_group_reply(first_results, "first", "第一问回答")
    assert_group_reply(empty_results, "empty", "请在 @机器人 后写上问题。")


@pytest.mark.asyncio
async def test_different_sessions_can_run_concurrently(plugin_module) -> None:
    plugin = make_plugin(plugin_module, group_whitelist=["9", "10"])
    both_started = asyncio.Event()
    started: set[str] = set()

    async def controlled_ask(
        session_id: str,
        _metadata: dict[str, Any],
        _question: str,
    ) -> str:
        started.add(session_id)
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        return session_id

    plugin.dsh.ask = controlled_ask
    events = [
        FakeEvent(sender_id="41", text="群九", private=False, group_id="9"),
        FakeEvent(sender_id="42", text="群十", private=False, group_id="10"),
    ]

    await asyncio.gather(*(collect(plugin.on_group_message(event)) for event in events))

    assert started == {"qq-group-7-9", "qq-group-7-10"}


@pytest.mark.asyncio
async def test_hourly_limit_is_queued_and_quotes_the_rejected_question(
    plugin_module,
) -> None:
    plugin = make_plugin(
        plugin_module,
        session_hourly_limit=1,
        fold_response_threshold=0,
    )
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    asked: list[str] = []

    async def controlled_ask(
        _session_id: str,
        _metadata: dict[str, Any],
        question: str,
    ) -> str:
        asked.append(question)
        first_started.set()
        await release_first.wait()
        return f"回答: {question}"

    plugin.dsh.ask = controlled_ask
    first_event = FakeEvent(
        sender_id="41",
        text="第一问",
        private=False,
        group_id="9",
        message_id="first",
    )
    limited_event = FakeEvent(
        sender_id="42",
        text="第二问",
        private=False,
        group_id="9",
        message_id="limited",
    )

    first_task = asyncio.create_task(collect(plugin.on_group_message(first_event)))
    await first_started.wait()
    limited_task = asyncio.create_task(collect(plugin.on_group_message(limited_event)))
    await asyncio.sleep(0)

    assert not limited_task.done()
    release_first.set()
    first_results, limited_results = await asyncio.gather(first_task, limited_task)

    assert_forward_record(first_results, "7", "回答: 第一问")
    assert_group_reply(limited_results, "limited", plugin_module.HOURLY_LIMIT_MESSAGE)
    assert asked == ["第一问"]


@pytest.mark.asyncio
async def test_private_hourly_limit_is_not_folded_at_zero_threshold(plugin_module) -> None:
    plugin = make_plugin(
        plugin_module,
        session_hourly_limit=1,
        fold_response_threshold=0,
    )
    first = FakeEvent(sender_id="42", text="/cac 第一问", private=True)
    limited = FakeEvent(sender_id="42", text="/cac 第二问", private=True)

    first_results = await collect(plugin.on_private_cac(first))
    limited_results = await collect(plugin.on_private_cac(limited))

    assert_forward_record(first_results, "7", "DSH answer")
    assert limited_results == [plugin_module.HOURLY_LIMIT_MESSAGE]


@pytest.mark.asyncio
async def test_private_empty_cac_waits_for_prior_session_answer(plugin_module) -> None:
    plugin = make_plugin(plugin_module)
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def controlled_ask(*_args: object) -> str:
        first_started.set()
        await release_first.wait()
        return "第一问回答"

    plugin.dsh.ask = controlled_ask
    first_event = FakeEvent(
        sender_id="42",
        text="/cac 第一问",
        private=True,
    )
    empty_event = FakeEvent(sender_id="42", text="/cac", private=True)

    first_task = asyncio.create_task(collect(plugin.on_private_cac(first_event)))
    await first_started.wait()
    empty_task = asyncio.create_task(collect(plugin.on_private_cac(empty_event)))
    await asyncio.sleep(0)

    assert not empty_task.done()
    release_first.set()

    assert await first_task == ["第一问回答"]
    assert await empty_task == ["用法: /cac <问题>"]


@pytest.mark.asyncio
async def test_different_private_sessions_can_run_concurrently(plugin_module) -> None:
    plugin = make_plugin(plugin_module, user_whitelist=["42", "43"])
    both_started = asyncio.Event()
    started: set[str] = set()

    async def controlled_ask(
        session_id: str,
        _metadata: dict[str, Any],
        _question: str,
    ) -> str:
        started.add(session_id)
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        return session_id

    plugin.dsh.ask = controlled_ask
    events = [
        FakeEvent(sender_id="42", text="/cac 第一问", private=True),
        FakeEvent(sender_id="43", text="/cac 第二问", private=True),
    ]

    await asyncio.gather(*(collect(plugin.on_private_cac(event)) for event in events))

    assert started == {"qq-private-7-42", "qq-private-7-43"}


@pytest.mark.asyncio
async def test_hourly_limit_is_independent_for_group_and_private_sessions(
    plugin_module,
) -> None:
    plugin = make_plugin(
        plugin_module,
        session_hourly_limit=1,
        user_whitelist=["42", "43"],
    )
    group_first = FakeEvent(sender_id="42", text="群第一问", private=False, group_id="9")
    private_first = FakeEvent(sender_id="42", text="/cac 私聊第一问", private=True)
    other_private = FakeEvent(sender_id="43", text="/cac 另一好友", private=True)
    group_limited = FakeEvent(
        sender_id="43",
        text="群第二问",
        private=False,
        group_id="9",
        message_id="group-limited",
    )
    private_limited = FakeEvent(sender_id="42", text="/cac 私聊第二问", private=True)

    assert_group_reply(
        await collect(plugin.on_group_message(group_first)),
        "message-1",
        "DSH answer",
    )
    assert await collect(plugin.on_private_cac(private_first)) == ["DSH answer"]
    assert await collect(plugin.on_private_cac(other_private)) == ["DSH answer"]
    assert_group_reply(
        await collect(plugin.on_group_message(group_limited)),
        "group-limited",
        plugin_module.HOURLY_LIMIT_MESSAGE,
    )
    assert await collect(plugin.on_private_cac(private_limited)) == [
        plugin_module.HOURLY_LIMIT_MESSAGE
    ]
    assert [call[0] for call in plugin.dsh.calls] == [
        "qq-group-7-9",
        "qq-private-7-42",
        "qq-private-7-43",
    ]


@pytest.mark.asyncio
async def test_zero_hourly_limit_disables_handler_limiting(plugin_module) -> None:
    plugin = make_plugin(plugin_module, session_hourly_limit=0)
    events = [
        FakeEvent(sender_id="42", text="/cac 第一问", private=True),
        FakeEvent(sender_id="42", text="/cac 第二问", private=True),
    ]

    results = [await collect(plugin.on_private_cac(event)) for event in events]

    assert results == [["DSH answer"], ["DSH answer"]]
    assert [call[2] for call in plugin.dsh.calls] == ["第一问", "第二问"]
