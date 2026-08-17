from routing import (
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


def test_user_whitelist_normalizes_ids() -> None:
    assert normalize_user_whitelist([42, " 99 ", "", None, 42]) == frozenset({"42", "99"})


def test_session_id_is_stable_per_bot_and_group() -> None:
    assert build_session_id("10001", "20002") == "qq-group-10001-20002"
    assert build_session_id("10001", "20002") == build_session_id("10001", "20002")
    assert build_session_id("bot:one", "group/two").startswith("qq-group-")


def test_private_session_is_stable_and_isolated_from_group_session() -> None:
    assert build_private_session_id("7", "42") == "qq-private-7-42"
    assert build_private_session_id("7", "42") != build_session_id("7", "42")
    assert build_private_session_id("bot:one", "user/two").startswith("qq-private-")


def test_private_cac_requires_literal_slash_prefix() -> None:
    assert extract_private_cac_query("/cac NOVA 是什么？") == "NOVA 是什么？"
    assert extract_private_cac_query(" /CAC\n第二行问题 ") == "第二行问题"
    assert extract_private_cac_query("/cac") == ""
    assert extract_private_cac_query("cac NOVA 是什么？") is None
    assert extract_private_cac_query("/caching") is None
    assert extract_private_cac_query("hello /cac question") is None


def test_slash_command_detection_ignores_leading_space() -> None:
    assert is_slash_command(" /audit status")
    assert not is_slash_command("NOVA 是什么？")


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


def test_private_metadata_preserves_friend_identity_without_group_fields() -> None:
    metadata = build_private_source_metadata(
        sender_id="42",
        sender_name="小明",
        message_id="m2",
        timestamp=11,
        bot_id="7",
        platform="aiocqhttp",
        platform_id="qq-main",
    )

    assert metadata == {
        "source_type": "qq_private",
        "platform": "aiocqhttp",
        "platform_id": "qq-main",
        "bot_id": "7",
        "peer_id": "42",
        "message_id": "m2",
        "timestamp": 11,
        "sender_id": "42",
        "sender_name": "小明",
        "trigger": "slash_cac",
    }
