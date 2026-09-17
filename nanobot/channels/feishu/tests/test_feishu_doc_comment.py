# ruff: noqa: E402

"""Tests for drive.notice.comment_add_v1 handling (doc comments)."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("lark_oapi")

from nanobot.bus.queue import MessageBus
from nanobot.channels.feishu.runtime import (
    FeishuChannel,
    FeishuConfig,
    _comment_reply_text,
    _extract_block_text,
    _extract_comment_block_id,
    _extract_comment_quote,
    _extract_comment_text,
)

# batch_query response: relation is a nested JSON string per the real API shape.
_COMMENT_BODY = {
    "items": [
        {
            "quote": "some quoted text",
            "relation": json.dumps({"positionInfo": {"blockID": "blk_abc123"}}),
            "reply_list": {
                "replies": [
                    {
                        "reply_id": "r1",
                        "content": {"elements": [{"text_run": {"text": "hello from the doc"}}]},
                    }
                ]
            },
        }
    ]
}


def _make_channel(**config_overrides) -> FeishuChannel:
    config_kwargs: dict = {
        "enabled": True,
        "app_id": "cli_test",
        "app_secret": "secret",
        "allow_from": ["*"],
        "doc_comment_enabled": True,
    }
    config_kwargs.update(config_overrides)
    config = FeishuConfig(**config_kwargs)
    ch = FeishuChannel(config, MessageBus())
    ch._running = True
    ch._client = MagicMock()
    ch._loop = None
    ch._fetch_doc_comment_sync = MagicMock(return_value=_COMMENT_BODY)
    ch._fetch_doc_block_sync = MagicMock(
        return_value={"block_id": "blk_abc123", "block_type": 2,
                      "text": {"elements": [{"text_run": {"content": "paragraph body"}}]}}
    )
    return ch


def _make_event(
    *,
    is_mentioned: bool = True,
    open_id: str = "ou_1",
    file_token: str = "ft_1",
    file_type: str = "docx",
    comment_id: str = "c1",
    reply_id: str | None = "r1",
) -> SimpleNamespace:
    return SimpleNamespace(
        event=SimpleNamespace(
            is_mentioned=is_mentioned,
            notice_meta=SimpleNamespace(
                from_user_id=SimpleNamespace(open_id=open_id),
                file_token=file_token,
                file_type=file_type,
            ),
            comment_id=comment_id,
            reply_id=reply_id,
        )
    )


# ── _extract_comment_text / _comment_reply_text ─────────────────────────────


class TestExtractCommentText:
    def test_picks_reply_matching_reply_id(self):
        data = {
            "comment_list": [
                {
                    "reply_list": {
                        "replies": [
                            {"reply_id": "r1", "content": {"elements": [{"text_run": {"text": "first"}}]}},
                            {"reply_id": "r2", "content": {"elements": [{"text_run": {"text": "second"}}]}},
                        ]
                    }
                }
            ]
        }
        assert _extract_comment_text(data, "r2") == "second"

    def test_joins_all_replies_without_reply_id(self):
        data = {
            "comment_list": [
                {
                    "reply_list": {
                        "replies": [
                            {"reply_id": "r1", "content": {"elements": [{"text_run": {"text": "aa"}}]}},
                            {"reply_id": "r2", "content": {"elements": [{"text_run": {"text": "bb"}}]}},
                        ]
                    }
                }
            ]
        }
        assert _extract_comment_text(data, None) == "aa\nbb"

    def test_returns_none_for_missing_comment_list(self):
        assert _extract_comment_text({}, None) is None

    def test_extracts_docs_link_title(self):
        reply = {"content": {"elements": [{"docs_link": {"title": "Some Doc"}}]}}
        assert _comment_reply_text(reply) == "Some Doc"

    def test_returns_none_when_no_text(self):
        assert _comment_reply_text({"content": {"elements": []}}) is None


class TestExtractCommentQuote:
    def test_returns_first_non_empty_quote(self):
        data = {"comment_list": [{"quote": "  anchored text  "}, {"quote": "other"}]}
        assert _extract_comment_quote(data) == "anchored text"

    def test_returns_none_when_no_quote(self):
        assert _extract_comment_quote({"comment_list": [{}]}) is None

    def test_returns_none_for_missing_comment_list(self):
        assert _extract_comment_quote({}) is None


class TestExtractCommentBlockId:
    def test_reads_camel_case_position_info(self):
        data = {"relation": {"positionInfo": {"blockID": "blk_1"}}}
        assert _extract_comment_block_id(data) == "blk_1"

    def test_reads_relation_inside_comment_item(self):
        data = {"items": [{"relation": {"positionInfo": {"blockID": "blk_3"}}}]}
        assert _extract_comment_block_id(data) == "blk_3"

    def test_reads_snake_case_position_info(self):
        data = {"relation": {"position_info": {"block_id": "blk_2"}}}
        assert _extract_comment_block_id(data) == "blk_2"

    def test_reads_relation_as_json_string(self):
        data = {"items": [{"relation": json.dumps({"positionInfo": {"blockID": "blk_4"}})}]}
        assert _extract_comment_block_id(data) == "blk_4"

    def test_reads_nested_relation_string(self):
        data = {
            "items": [
                {"relation": json.dumps({"relation": json.dumps({"positionInfo": {"blockID": "blk_5"}})})}
            ]
        }
        assert _extract_comment_block_id(data) == "blk_5"

    def test_returns_none_without_relation(self):
        assert _extract_comment_block_id({}) is None
        assert _extract_comment_block_id({"relation": {}}) is None


class TestExtractBlockText:
    def test_collects_text_run_contents(self):
        block = {
            "block_type": 2,
            "text": {"elements": [
                {"text_run": {"content": "hello "}},
                {"text_run": {"content": "world"}},
            ]},
        }
        assert _extract_block_text(block) == "hello world"

    def test_returns_none_without_text(self):
        assert _extract_block_text({"block_type": 1}) is None


# ── _on_doc_comment filtering ────────────────────────────────────────────────


class TestOnDocComment:
    async def test_happy_path_forwards_to_bus(self):
        ch = _make_channel()
        ch._handle_message = AsyncMock()
        await ch._on_doc_comment(_make_event())

        ch._handle_message.assert_awaited_once()
        kwargs = ch._handle_message.await_args.kwargs
        assert kwargs["sender_id"] == "ou_1"
        assert kwargs["chat_id"] == "ou_1"
        assert kwargs["session_key"] == "feishu:doc:ft_1"
        assert kwargs["is_dm"] is True
        assert "hello from the doc" in kwargs["content"]
        assert "Quoted text: some quoted text" in kwargs["content"]
        assert "Comment anchor block: blk_abc123 (type 2)" in kwargs["content"]
        assert "Block content: paragraph body" in kwargs["content"]
        assert kwargs["metadata"]["comment_id"] == "c1"
        assert kwargs["metadata"]["file_token"] == "ft_1"
        assert kwargs["metadata"]["block_id"] == "blk_abc123"
        assert kwargs["metadata"]["block_type"] == 2
        assert kwargs["metadata"]["event_type"] == "drive.notice.comment_add_v1"
        ch._fetch_doc_block_sync.assert_called_once_with("ft_1", "blk_abc123")

    async def test_non_docx_comment_skips_block_fetch(self):
        ch = _make_channel()
        ch._handle_message = AsyncMock()
        await ch._on_doc_comment(_make_event(file_type="sheet"))
        kwargs = ch._handle_message.await_args.kwargs
        assert "Block content:" not in kwargs["content"]
        assert kwargs["metadata"]["block_type"] is None
        ch._fetch_doc_block_sync.assert_not_called()

    async def test_skips_when_not_mentioned(self):
        ch = _make_channel()
        ch._handle_message = AsyncMock()
        await ch._on_doc_comment(_make_event(is_mentioned=False))
        ch._handle_message.assert_not_awaited()

    async def test_allows_non_mention_when_mention_only_disabled(self):
        ch = _make_channel(doc_comment_mention_only=False)
        ch._handle_message = AsyncMock()
        await ch._on_doc_comment(_make_event(is_mentioned=False))
        ch._handle_message.assert_awaited_once()

    async def test_skips_sender_not_in_from_users(self):
        ch = _make_channel(doc_comment_from_users=["ou_2"])
        ch._handle_message = AsyncMock()
        await ch._on_doc_comment(_make_event(open_id="ou_1"))
        ch._handle_message.assert_not_awaited()

    async def test_allows_listed_sender(self):
        ch = _make_channel(doc_comment_from_users=["ou_1"])
        ch._handle_message = AsyncMock()
        await ch._on_doc_comment(_make_event(open_id="ou_1"))
        ch._handle_message.assert_awaited_once()

    async def test_skips_missing_routing_fields(self):
        ch = _make_channel()
        ch._handle_message = AsyncMock()
        await ch._on_doc_comment(SimpleNamespace(event=SimpleNamespace(is_mentioned=True)))
        ch._handle_message.assert_not_awaited()

    async def test_skips_disallowed_sender(self):
        ch = _make_channel(allow_from=["ou_other"])
        ch._handle_message = AsyncMock()
        await ch._on_doc_comment(_make_event())
        ch._handle_message.assert_not_awaited()

    async def test_deduplicates_repeat_events(self):
        ch = _make_channel()
        ch._handle_message = AsyncMock()
        event = _make_event()
        await ch._on_doc_comment(event)
        await ch._on_doc_comment(event)
        ch._handle_message.assert_awaited_once()

    async def test_falls_back_when_comment_fetch_fails(self):
        ch = _make_channel()
        ch._fetch_doc_comment_sync = MagicMock(return_value=None)
        ch._handle_message = AsyncMock()
        await ch._on_doc_comment(_make_event(reply_id=None))
        kwargs = ch._handle_message.await_args.kwargs
        assert "content unavailable" in kwargs["content"]
