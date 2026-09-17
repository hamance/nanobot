# ruff: noqa: E402

"""Tests for im.message.recalled_v1 handling (user message recall)."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("lark_oapi")

from nanobot.bus.events import (
    INBOUND_META_RUNTIME_CONTROL,
    RUNTIME_CONTROL_REDACT_MESSAGE_ID,
    RUNTIME_CONTROL_SESSION_REDACT,
)
from nanobot.bus.queue import MessageBus
from nanobot.channels.feishu.runtime import FeishuChannel, FeishuConfig


def _make_channel() -> FeishuChannel:
    config = FeishuConfig(
        enabled=True,
        app_id="cli_test",
        app_secret="secret",
        allow_from=["*"],
    )
    ch = FeishuChannel(config, MessageBus())
    ch._running = True
    ch._client = MagicMock()
    ch._loop = None
    return ch


def _make_recall_event(message_id: str | None = "om_1") -> SimpleNamespace:
    return SimpleNamespace(event=SimpleNamespace(message_id=message_id))


def _make_message_event(message_id: str = "om_1", sender_open_id: str = "ou_alice") -> SimpleNamespace:
    message = SimpleNamespace(
        message_id=message_id,
        chat_id="oc_abc",
        chat_type="p2p",
        message_type="text",
        content='{"text": "hello"}',
        parent_id=None,
        root_id=None,
        mentions=[],
    )
    sender = SimpleNamespace(
        sender_type="user",
        sender_id=SimpleNamespace(open_id=sender_open_id),
    )
    return SimpleNamespace(event=SimpleNamespace(message=message, sender=sender))


# ── _on_message_recall ──────────────────────────────────────────────────────


class TestOnMessageRecall:
    async def test_publishes_control_message_for_known_recall(self):
        ch = _make_channel()
        ch._recall_index["om_1"] = "feishu:ou_alice"
        await ch._on_message_recall(_make_recall_event("om_1"))

        msg = await asyncio.wait_for(ch.bus.inbound.get(), timeout=1)
        assert msg.channel == "system"
        assert msg.session_key_override == "feishu:ou_alice"
        assert msg.metadata[INBOUND_META_RUNTIME_CONTROL] == RUNTIME_CONTROL_SESSION_REDACT
        assert msg.metadata[RUNTIME_CONTROL_REDACT_MESSAGE_ID] == "om_1"
        # Index entry is consumed; a duplicate recall is ignored.
        await ch._on_message_recall(_make_recall_event("om_1"))
        assert ch.bus.inbound.empty()

    async def test_ignores_unknown_message_id(self):
        ch = _make_channel()
        await ch._on_message_recall(_make_recall_event("om_unknown"))
        assert ch.bus.inbound.empty()
        assert "om_unknown" in ch._recalled_message_ids

    async def test_ignores_missing_message_id(self):
        ch = _make_channel()
        await ch._on_message_recall(_make_recall_event(None))
        assert ch.bus.inbound.empty()


# ── recall index population and race in _on_message ──────────────────────────


class TestRecallIndex:
    async def test_add_reaction_skips_recalled_message(self):
        ch = _make_channel()
        ch._recalled_message_ids.add("om_1")
        assert await ch._add_reaction("om_1", "THUMBSUP") is None
        ch._client.im.v1.message_reaction.create.assert_not_called()

    async def test_on_message_records_session_mapping(self):
        ch = _make_channel()
        ch._handle_message = AsyncMock()
        with patch.object(ch, "_add_reaction", return_value=None):
            await ch._on_message(_make_message_event("om_1"))

        assert ch._recall_index["om_1"] == "feishu:ou_alice"
        # group topic isolation style keys are honored too
        ch._handle_message = AsyncMock()
        group_msg = SimpleNamespace(
            message_id="om_2",
            chat_id="oc_grp",
            chat_type="group",
            message_type="text",
            content='{"text": "@bot hi"}',
            parent_id=None,
            root_id="om_root",
            mentions=[SimpleNamespace(key="@_user_1", name="bot", id=SimpleNamespace(open_id="ou_bot"))],
        )
        sender = SimpleNamespace(
            sender_type="user",
            sender_id=SimpleNamespace(open_id="ou_alice"),
        )
        ch._bot_open_id = "ou_bot"
        with patch.object(ch, "_add_reaction", return_value=None):
            await ch._on_message(SimpleNamespace(event=SimpleNamespace(message=group_msg, sender=sender)))
        assert ch._recall_index["om_2"] == "feishu:oc_grp:om_root"

    async def test_recall_racing_ahead_drops_message(self):
        ch = _make_channel()
        ch._handle_message = AsyncMock()
        ch._recalled_message_ids.add("om_1")
        with patch.object(ch, "_add_reaction", return_value=None):
            await ch._on_message(_make_message_event("om_1"))
        ch._handle_message.assert_not_awaited()
        assert "om_1" not in ch._recalled_message_ids
