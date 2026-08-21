"""Asynchronous client for the DeepSeek Harness Web RPC used by this plugin."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

import httpx

EXPECTED_PRESET = "nova-qa"
EXPECTED_WORKSPACE_TITLE = "NOVA知识库"
DEFAULT_MODEL_PROVIDER = "deepseek-official"
DEFAULT_MODEL_NAME = "deepseek-v4-flash-vision-exp"


class DshError(RuntimeError):
    """Base error for DSH transport, protocol, configuration, and turn failures."""


class DshTransportError(DshError):
    """The DSH HTTP endpoint could not complete a request."""


class DshProtocolError(DshError):
    """DSH returned an invalid JSON-RPC envelope."""


class DshConfigurationError(DshError):
    """The connected DSH is not the fixed NOVA QA deployment."""


class DshRpcError(DshError):
    """DSH returned a structured RPC failure."""

    def __init__(self, method: str, code: str, message: str) -> None:
        self.method = method
        self.code = code
        self.rpc_message = message
        super().__init__(f"{method} failed: {code}: {message}")

    @classmethod
    def from_result(cls, method: str, result: object) -> DshRpcError:
        """Build an error from the wide RPC error value."""

        error = result.get("error") if isinstance(result, dict) else None
        if isinstance(error, dict):
            code = str(error.get("code", "unknown-error"))
            message = str(error.get("message", "DSH rejected the request"))
        else:
            code = "invalid-error"
            message = "DSH returned an invalid error payload"
        return cls(method, code, message)


class DshTurnError(DshError):
    """A DSH turn ended without a completed text answer."""


class DshTimeoutError(DshTurnError):
    """A DSH turn did not finish before the response deadline."""


class DshClient:
    """Call one fixed-workspace DSH deployment and serialize each Session."""

    def __init__(
        self,
        base_url: str,
        *,
        request_timeout_seconds: float,
        response_timeout_seconds: float,
        poll_interval_seconds: float,
        model_name: str = DEFAULT_MODEL_NAME,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        if response_timeout_seconds <= 0:
            raise ValueError("response_timeout_seconds must be positive")
        if poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds cannot be negative")
        if not model_name.strip():
            raise ValueError("model_name must be a non-empty string")

        self.base_url = base_url.rstrip("/")
        self.response_timeout_seconds = response_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.model_name = model_name.strip()
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(request_timeout_seconds),
            transport=transport,
        )
        self._workspace_id: str | None = None
        self._workspace_lock = asyncio.Lock()
        self._session_locks: dict[str, asyncio.Lock] = {}

    async def close(self) -> None:
        """Close the reusable HTTP connection pool."""

        await self._http.aclose()

    async def rpc(self, method: str, payload: dict[str, object]) -> dict[str, Any]:
        """Call one DSH unary Web RPC and return its value object."""

        rpc_id = f"astrbot-{uuid4()}"
        request_body = {
            "type": "client-request",
            "rpcId": rpc_id,
            "method": method,
            "payload": payload,
        }
        try:
            response = await self._http.post(f"/api/{method}", json=request_body)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise DshTransportError(f"{method} transport failed: {error}") from error

        try:
            envelope = response.json()
        except ValueError as error:
            raise DshProtocolError(f"{method} returned non-JSON data") from error

        if not isinstance(envelope, dict):
            raise DshProtocolError(f"{method} returned a non-object envelope")
        if envelope.get("type") != "server-response" or envelope.get("rpcId") != rpc_id:
            raise DshProtocolError(f"{method} returned an invalid response envelope")

        result = envelope.get("result")
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise DshRpcError.from_result(method, result)
        value = result.get("value")
        if not isinstance(value, dict):
            raise DshProtocolError(f"{method} returned a non-object value")
        return value

    async def resolve_workspace_id(self) -> str:
        """Resolve and cache the Bundle's single fixed NOVA Workspace."""

        async with self._workspace_lock:
            if self._workspace_id is not None:
                return self._workspace_id

            value = await self.rpc("workspace.list", {})
            items = value.get("items")
            if not isinstance(items, list) or len(items) != 1:
                raise DshConfigurationError(
                    "expected exactly one DSH Workspace from the NOVA QA Bundle"
                )
            workspace = items[0]
            if not isinstance(workspace, dict):
                raise DshProtocolError("workspace.list returned an invalid Workspace")
            if workspace.get("title") != EXPECTED_WORKSPACE_TITLE:
                raise DshConfigurationError(
                    f"expected Workspace {EXPECTED_WORKSPACE_TITLE}, got {workspace.get('title')!r}"
                )
            workspace_id = workspace.get("workspaceId")
            if not isinstance(workspace_id, str) or not workspace_id:
                raise DshProtocolError("workspace.list returned an invalid workspaceId")
            self._workspace_id = workspace_id
            return workspace_id

    async def ensure_session(self, session_id: str) -> None:
        """Idempotently create a routed Session with the server-owned default Preset."""

        workspace_id = await self.resolve_workspace_id()
        value = await self.rpc(
            "session.create",
            {"sessionId": session_id, "workspaceId": workspace_id},
        )
        if value.get("sessionId") != session_id:
            raise DshProtocolError("session.create returned a different sessionId")
        if value.get("agentPreset") != EXPECTED_PRESET:
            raise DshConfigurationError(
                f"expected Session Preset {EXPECTED_PRESET}, got {value.get('agentPreset')!r}"
            )
        await self.select_model(session_id)

    async def select_model(self, session_id: str) -> None:
        """Select the configured direct DeepSeek model for this QQ Session."""

        value = await self.rpc(
            "session.selectModel",
            {
                "sessionId": session_id,
                "provider": DEFAULT_MODEL_PROVIDER,
                "model": self.model_name,
            },
        )
        selected = value.get("selected")
        if not isinstance(selected, dict):
            raise DshProtocolError("session.selectModel returned an invalid selection")
        if (
            selected.get("provider") != DEFAULT_MODEL_PROVIDER
            or selected.get("model") != self.model_name
        ):
            raise DshConfigurationError(
                "DSH selected a different model than the configured NOVA model"
            )

    async def ask(
        self,
        session_id: str,
        source_metadata: dict[str, Any],
        question: str,
        *,
        image_parts: list[dict[str, str]] | None = None,
    ) -> str:
        """Queue one routed QQ message and wait for the Session's completed answer."""

        lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            await self.ensure_session(session_id)
            baseline = await self._history(session_id)
            baseline_seq = self._latest_seq(baseline)
            metadata_json = json.dumps(
                source_metadata,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            metadata_tag = (
                "private_message_metadata"
                if source_metadata.get("source_type") == "qq_private"
                else "group_message_metadata"
            )
            content: list[dict[str, str]] = [
                {
                    "type": "text",
                    "text": (f"<{metadata_tag}>\n{metadata_json}\n</{metadata_tag}>"),
                },
                {"type": "text", "text": question},
            ]
            content.extend(dict(part) for part in (image_parts or []))
            await self.rpc(
                "session.prompt",
                {
                    "sessionId": session_id,
                    "mode": "queue",
                    "content": content,
                },
            )
            return await self._wait_for_answer(session_id, baseline_seq)

    async def _history(self, session_id: str) -> list[dict[str, Any]]:
        value = await self.rpc(
            "session.history",
            {"sessionId": session_id, "maxMessages": 20},
        )
        entries = value.get("events")
        if not isinstance(entries, list):
            raise DshProtocolError("session.history returned invalid events")
        return [entry for entry in entries if isinstance(entry, dict)]

    @staticmethod
    def _latest_seq(entries: list[dict[str, Any]]) -> int:
        sequences = [
            event["seq"]
            for entry in entries
            if isinstance((event := entry.get("event")), dict) and isinstance(event.get("seq"), int)
        ]
        return max(sequences, default=-1)

    async def _wait_for_answer(self, session_id: str, baseline_seq: int) -> str:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.response_timeout_seconds

        while True:
            entries = await self._history(session_id)
            events = [
                event
                for entry in entries
                if isinstance((event := entry.get("event")), dict)
                and isinstance(event.get("seq"), int)
                and event["seq"] > baseline_seq
            ]
            events.sort(key=lambda event: event["seq"])
            turn_end = next((event for event in events if event.get("type") == "turn/end"), None)
            if turn_end is not None:
                return self._answer_for_completed_turn(events, turn_end)
            if loop.time() >= deadline:
                raise DshTimeoutError(
                    f"DSH Session {session_id} did not finish within "
                    f"{self.response_timeout_seconds:g} seconds"
                )
            await asyncio.sleep(self.poll_interval_seconds)

    @staticmethod
    def _answer_for_completed_turn(events: list[dict[str, Any]], turn_end: dict[str, Any]) -> str:
        data = turn_end.get("data")
        reason = data.get("reason") if isinstance(data, dict) else None
        kind = reason.get("kind") if isinstance(reason, dict) else "unknown"
        if kind != "completed":
            detail = reason.get("message") if isinstance(reason, dict) else None
            suffix = f": {detail}" if detail else ""
            raise DshTurnError(f"DSH turn ended as {kind}{suffix}")

        end_seq = turn_end["seq"]
        assistants = [
            event
            for event in events
            if event.get("type") == "assistant/message" and event["seq"] <= end_seq
        ]
        if not assistants:
            raise DshTurnError("DSH completed the turn without an assistant message")

        assistant_data = assistants[-1].get("data")
        if not isinstance(assistant_data, dict):
            raise DshProtocolError("assistant/message data is invalid")
        message = assistant_data.get("message", assistant_data)
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            raise DshProtocolError("assistant/message content is invalid")
        texts = [
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
            and block["text"]
        ]
        if not texts:
            raise DshTurnError("DSH completed the turn without a text answer")
        return "\n".join(texts)
