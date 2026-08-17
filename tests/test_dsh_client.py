import json
from typing import Any

import httpx
import pytest

from dsh_client import (
    DshClient,
    DshConfigurationError,
    DshRpcError,
    DshTurnError,
)


def rpc_response(request: httpx.Request, value: dict[str, Any]) -> httpx.Response:
    body = json.loads(request.content)
    return httpx.Response(
        200,
        request=request,
        json={
            "type": "server-response",
            "rpcId": body["rpcId"],
            "result": {"ok": True, "value": value},
        },
    )


def method_of(request: httpx.Request) -> str:
    return json.loads(request.content)["method"]


@pytest.mark.asyncio
async def test_ask_creates_fixed_session_and_returns_completed_answer() -> None:
    methods: list[str] = []
    prompt_payload: dict[str, Any] = {}
    history_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal history_calls, prompt_payload
        body = json.loads(request.content)
        method = body["method"]
        methods.append(method)
        if method == "workspace.list":
            return rpc_response(
                request,
                {
                    "items": [
                        {
                            "workspaceId": "workspace-1",
                            "title": "NOVA知识库",
                            "path": "/srv/nova/knowledge",
                            "sessionIds": [],
                            "createdAt": "2026-08-17T00:00:00Z",
                            "updatedAt": "2026-08-17T00:00:00Z",
                        }
                    ],
                    "archivedSessionIds": [],
                },
            )
        if method == "session.create":
            assert body["payload"] == {
                "sessionId": "qq-group-7-9",
                "workspaceId": "workspace-1",
            }
            return rpc_response(
                request,
                {"sessionId": "qq-group-7-9", "agentPreset": "nova-qa"},
            )
        if method == "session.history":
            history_calls += 1
            if history_calls == 1:
                return rpc_response(request, {"events": [], "hasMore": False})
            if history_calls == 2:
                return rpc_response(
                    request,
                    {
                        "events": [
                            {
                                "event": {
                                    "type": "turn/start",
                                    "seq": 0,
                                    "time": 1,
                                    "data": {"turn": 1},
                                }
                            }
                        ],
                        "hasMore": False,
                    },
                )
            return rpc_response(
                request,
                {
                    "events": [
                        {
                            "event": {
                                "type": "turn/start",
                                "seq": 0,
                                "time": 1,
                                "data": {"turn": 1},
                            }
                        },
                        {
                            "event": {
                                "type": "assistant/message",
                                "seq": 1,
                                "time": 2,
                                "data": {
                                    "turn": 1,
                                    "step": 1,
                                    "message": {
                                        "role": "assistant",
                                        "content": [
                                            {"type": "text", "text": "NOVA 是一个学习共同体。"},
                                            {"type": "text", "text": "欢迎继续提问。"},
                                        ],
                                        "source": {"kind": "model"},
                                    },
                                },
                            }
                        },
                        {
                            "event": {
                                "type": "turn/end",
                                "seq": 2,
                                "time": 3,
                                "data": {"turn": 1, "reason": {"kind": "completed"}},
                            }
                        },
                    ],
                    "hasMore": False,
                },
            )
        if method == "session.prompt":
            prompt_payload = body["payload"]
            return rpc_response(request, {"accepted": True})
        raise AssertionError(f"unexpected method {method}")

    client = DshClient(
        "http://dsh.test",
        request_timeout_seconds=1,
        response_timeout_seconds=1,
        poll_interval_seconds=0,
        transport=httpx.MockTransport(handler),
    )
    metadata = {"sender_id": "42", "sender_name": "小明", "group_id": "9"}
    try:
        answer = await client.ask("qq-group-7-9", metadata, "NOVA 是什么？")
    finally:
        await client.close()

    assert answer == "NOVA 是一个学习共同体。\n欢迎继续提问。"
    assert methods == [
        "workspace.list",
        "session.create",
        "session.history",
        "session.prompt",
        "session.history",
        "session.history",
    ]
    assert prompt_payload["sessionId"] == "qq-group-7-9"
    assert prompt_payload["mode"] == "queue"
    metadata_block, question_block = prompt_payload["content"]
    assert question_block == {"type": "text", "text": "NOVA 是什么？"}
    assert metadata_block["type"] == "text"
    assert metadata_block["text"].startswith("<group_message_metadata>\n")
    assert '"sender_name":"小明"' in metadata_block["text"]


def one_method_transport(
    method: str,
    value: dict[str, Any] | None = None,
    *,
    error: dict[str, Any] | None = None,
) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert method_of(request) == method
        body = json.loads(request.content)
        result = {"ok": False, "error": error} if error else {"ok": True, "value": value}
        return httpx.Response(
            200,
            request=request,
            json={"type": "server-response", "rpcId": body["rpcId"], "result": result},
        )

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_rpc_surfaces_dsh_error_code_and_message() -> None:
    client = DshClient(
        "http://dsh.test",
        request_timeout_seconds=1,
        response_timeout_seconds=1,
        poll_interval_seconds=0,
        transport=one_method_transport(
            "session.prompt",
            error={"code": "model-unavailable", "message": "provider is missing"},
        ),
    )
    try:
        with pytest.raises(DshRpcError, match=r"model-unavailable.*provider is missing"):
            await client.rpc("session.prompt", {})
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("items", "message"),
    [
        ([], "exactly one"),
        ([{"workspaceId": "w", "title": "Other"}], "NOVA知识库"),
        (
            [
                {"workspaceId": "w1", "title": "NOVA知识库"},
                {"workspaceId": "w2", "title": "NOVA知识库"},
            ],
            "exactly one",
        ),
    ],
)
async def test_workspace_must_be_the_single_nova_workspace(
    items: list[dict[str, Any]], message: str
) -> None:
    client = DshClient(
        "http://dsh.test",
        request_timeout_seconds=1,
        response_timeout_seconds=1,
        poll_interval_seconds=0,
        transport=one_method_transport(
            "workspace.list", {"items": items, "archivedSessionIds": []}
        ),
    )
    try:
        with pytest.raises(DshConfigurationError, match=message):
            await client.resolve_workspace_id()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_session_must_resolve_nova_preset() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return rpc_response(
                request,
                {
                    "items": [{"workspaceId": "w", "title": "NOVA知识库"}],
                    "archivedSessionIds": [],
                },
            )
        return rpc_response(request, {"sessionId": "s", "agentPreset": "coding"})

    client = DshClient(
        "http://dsh.test",
        request_timeout_seconds=1,
        response_timeout_seconds=1,
        poll_interval_seconds=0,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(DshConfigurationError, match="nova-qa"):
            await client.ensure_session("s")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_failed_turn_does_not_return_stale_assistant_message() -> None:
    history_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal history_calls
        method = method_of(request)
        if method == "workspace.list":
            return rpc_response(
                request,
                {
                    "items": [{"workspaceId": "w", "title": "NOVA知识库"}],
                    "archivedSessionIds": [],
                },
            )
        if method == "session.create":
            return rpc_response(request, {"sessionId": "s", "agentPreset": "nova-qa"})
        if method == "session.prompt":
            return rpc_response(request, {"accepted": True})
        if method == "session.history":
            history_calls += 1
            if history_calls == 1:
                return rpc_response(request, {"events": [], "hasMore": False})
            return rpc_response(
                request,
                {
                    "events": [
                        {
                            "event": {
                                "type": "turn/end",
                                "seq": 1,
                                "time": 1,
                                "data": {
                                    "turn": 1,
                                    "reason": {"kind": "failed", "message": "provider failed"},
                                },
                            }
                        }
                    ],
                    "hasMore": False,
                },
            )
        raise AssertionError(method)

    client = DshClient(
        "http://dsh.test",
        request_timeout_seconds=1,
        response_timeout_seconds=1,
        poll_interval_seconds=0,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(DshTurnError, match=r"failed.*provider failed"):
            await client.ask("s", {"sender_id": "1"}, "问题")
    finally:
        await client.close()
