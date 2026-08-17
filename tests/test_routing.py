from routing import (
    build_session_id,
    build_source_metadata,
    has_direct_mention,
    normalize_group_whitelist,
    resolve_base_url,
)


def test_resolve_base_url_prefers_control_panel_value() -> None:
    assert (
        resolve_base_url(" http://dsh.internal:3081/ ", {"DSH_BASE_URL": "http://env:3081"})
        == "http://dsh.internal:3081"
    )


def test_resolve_base_url_uses_environment_then_loopback_default() -> None:
    assert resolve_base_url("", {"DSH_BASE_URL": "http://env:3081/"}) == "http://env:3081"
    assert resolve_base_url("", {}) == "http://127.0.0.1:3081"


def test_group_whitelist_normalizes_ids() -> None:
    assert normalize_group_whitelist([123, " 456 ", "", None, 123]) == frozenset({"123", "456"})


def test_session_id_is_stable_per_bot_and_group() -> None:
    assert build_session_id("10001", "20002") == "qq-group-10001-20002"
    assert build_session_id("10001", "20002") == build_session_id("10001", "20002")
    assert build_session_id("bot:one", "group/two").startswith("qq-group-")


def test_direct_mention_requires_at_component_targeting_this_bot() -> None:
    class FakeAt:
        def __init__(self, qq: str) -> None:
            self.qq = qq

    assert has_direct_mention([object(), FakeAt("7")], "7", FakeAt)
    assert not has_direct_mention([FakeAt("8")], "7", FakeAt)
    assert not has_direct_mention([object()], "7", FakeAt)


def test_metadata_preserves_sender_and_message_identity() -> None:
    metadata = build_source_metadata(
        sender_id="42",
        sender_name="小明",
        group_id="9",
        message_id="m1",
        timestamp=10,
        bot_id="7",
        platform="aiocqhttp",
        platform_id="qq-main",
    )

    assert metadata == {
        "source_type": "qq_group",
        "platform": "aiocqhttp",
        "platform_id": "qq-main",
        "bot_id": "7",
        "group_id": "9",
        "message_id": "m1",
        "timestamp": 10,
        "sender_id": "42",
        "sender_name": "小明",
        "trigger": "at_bot",
    }
