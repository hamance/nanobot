"""Tests for the Feishu doc comment / docx block tools."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("lark_oapi")

from nanobot.agent.tools.feishu_docs import (
    FeishuDocCommentReplyTool,
    FeishuDocCommentResolveTool,
    FeishuDocxGetBlockTool,
    FeishuDocxUpdateBlockTool,
)
from nanobot.channels.feishu import docapi


class _FakeResponse:
    def __init__(self, payload: dict, success: bool = True):
        self._success = success
        self.code = 0 if success else 99999
        self.msg = "ok" if success else "error"
        self.raw = SimpleNamespace(content=json.dumps(payload).encode("utf-8"))

    def success(self) -> bool:
        return self._success


class _CapturingClient:
    """Stand-in for the lark client: records requests, returns canned responses."""

    def __init__(self, payload: dict, success: bool = True):
        self.requests: list = []
        self._response = _FakeResponse(payload, success)

    def request(self, request):
        self.requests.append(request)
        return self._response


@pytest.fixture(autouse=True)
def _clear_registry():
    docapi._CLIENTS.clear()
    yield
    docapi._CLIENTS.clear()


# ── registry ─────────────────────────────────────────────────────────────────


class TestRegistry:
    def test_register_get_unregister(self):
        client = object()
        docapi.register_doc_client("feishu", client)
        assert docapi.get_doc_client("feishu") is client
        assert docapi.get_doc_client(None) is client  # single-client fallback
        docapi.unregister_doc_client("feishu")
        assert docapi.get_doc_client("feishu") is None

    def test_exact_match_preferred_over_fallback(self):
        default, other = object(), object()
        docapi.register_doc_client("feishu", default)
        docapi.register_doc_client("feishu.work", other)
        assert docapi.get_doc_client("feishu.work") is other
        assert docapi.get_doc_client("feishu") is default
        # ambiguous without a channel hint -> default instance
        assert docapi.get_doc_client(None) is default


# ── docapi helpers ───────────────────────────────────────────────────────────


class TestDocApi:
    def test_fetch_block_builds_get_request(self):
        client = _CapturingClient({"block": {"block_id": "b1"}})
        result = docapi.fetch_block(client, "doc_1", "b1")
        assert result == {"block": {"block_id": "b1"}}
        req = client.requests[0]
        assert req.uri == "/open-apis/docx/v1/documents/doc_1/blocks/b1"

    def test_update_block_text_builds_patch_request(self):
        client = _CapturingClient({"block": {}})
        result = docapi.update_block_text(client, "doc_1", "b1", "new text")
        assert result == {"block": {}}
        req = client.requests[0]
        assert req.uri == "/open-apis/docx/v1/documents/doc_1/blocks/b1"
        assert req.body == {
            "update_text_elements": {"elements": [{"text_run": {"content": "new text"}}]}
        }
        assert req.headers["Content-Type"].startswith("application/json")

    def test_reply_comment_builds_post_request(self):
        client = _CapturingClient({"reply": {"reply_id": "r9"}})
        result = docapi.reply_comment(client, "ft_1", "c1", "done")
        assert result == {"reply": {"reply_id": "r9"}}
        req = client.requests[0]
        assert req.uri == "/open-apis/drive/v1/files/ft_1/comments/c1/replies?file_type=docx"
        assert req.body == {
            "content": {"elements": [{"type": "text_run", "text_run": {"text": "done"}}]}
        }

    def test_reply_comment_honors_file_type(self):
        client = _CapturingClient({"reply": {}})
        docapi.reply_comment(client, "ft_1", "c1", "done", file_type="sheet")
        assert client.requests[0].uri.endswith("/replies?file_type=sheet")

    def test_batch_query_comments_requests_relation(self):
        client = _CapturingClient({"items": []})
        docapi.batch_query_comments(client, "ft_1", "c1")
        req = client.requests[0]
        assert req.uri == "/open-apis/drive/v1/files/ft_1/comments/batch_query?file_type=docx"
        assert req.body == {"comment_ids": ["c1"], "need_relation": True}

    def test_get_comment_uses_get_without_relation(self):
        client = _CapturingClient({"items": []})
        docapi.get_comment(client, "ft_1", "c1", file_type="sheet")
        req = client.requests[0]
        assert req.uri == "/open-apis/drive/v1/files/ft_1/comments/c1?file_type=sheet"
        assert req.body is None

    def test_set_comment_solved_with_and_without_file_type(self):
        client = _CapturingClient({"comment": {}})
        docapi.set_comment_solved(client, "ft_1", "c1", True, file_type="")
        docapi.set_comment_solved(client, "ft_1", "c1", False, "docx")
        first, second = client.requests
        assert first.uri == "/open-apis/drive/v1/files/ft_1/comments/c1"
        assert first.body == {"is_solved": True}
        assert second.uri == "/open-apis/drive/v1/files/ft_1/comments/c1?file_type=docx"
        assert second.body == {"is_solved": False}

    def test_set_comment_solved_defaults_to_docx(self):
        client = _CapturingClient({"comment": {}})
        docapi.set_comment_solved(client, "ft_1", "c1", True)
        assert client.requests[0].uri.endswith("/comments/c1?file_type=docx")

    def test_failed_request_returns_none(self):
        client = _CapturingClient({}, success=False)
        assert docapi.fetch_block(client, "doc_1", "b1") is None


# ── tools ────────────────────────────────────────────────────────────────────


class TestTools:
    def test_tools_are_discoverable(self):
        from nanobot.agent.tools.loader import ToolLoader

        discovered = set(ToolLoader().discover())
        assert FeishuDocxGetBlockTool in discovered
        assert FeishuDocxUpdateBlockTool in discovered
        assert FeishuDocCommentReplyTool in discovered
        assert FeishuDocCommentResolveTool in discovered

    async def test_get_block_success(self, monkeypatch):
        docapi.register_doc_client("feishu", object())
        monkeypatch.setattr(
            docapi, "fetch_block", lambda client, doc, blk: {"block_id": blk, "block_type": 2}
        )
        tool = FeishuDocxGetBlockTool.create(MagicMock())
        result = await tool.execute(file_token="doc_1", block_id="b1")
        assert result.is_error is False
        assert '"block_id": "b1"' in result

    async def test_update_block_success(self, monkeypatch):
        docapi.register_doc_client("feishu", object())
        monkeypatch.setattr(docapi, "update_block_text", lambda *a, **k: {"ok": True})
        tool = FeishuDocxUpdateBlockTool.create(MagicMock())
        result = await tool.execute(file_token="doc_1", block_id="b1", text="hi")
        assert result.is_error is False
        assert "Updated block b1" in result

    async def test_reply_success(self, monkeypatch):
        docapi.register_doc_client("feishu", object())
        calls = []
        monkeypatch.setattr(docapi, "reply_comment", lambda *a, **k: calls.append(k) or {"ok": True})
        tool = FeishuDocCommentReplyTool.create(MagicMock())
        result = await tool.execute(file_token="ft_1", comment_id="c1", text="done")
        assert result.is_error is False
        assert "Replied to comment c1" in result
        assert calls[0]["file_type"] == "docx"

    async def test_resolve_defaults_to_solved(self, monkeypatch):
        docapi.register_doc_client("feishu", object())
        calls: list = []
        monkeypatch.setattr(
            docapi,
            "set_comment_solved",
            lambda client, ft, cid, solved, ft_type="": calls.append((cid, solved, ft_type)) or {"ok": True},
        )
        tool = FeishuDocCommentResolveTool.create(MagicMock())
        result = await tool.execute(file_token="ft_1", comment_id="c1")
        assert result.is_error is False
        assert calls == [("c1", True, "docx")]

    async def test_error_without_client(self):
        tool = FeishuDocxGetBlockTool.create(MagicMock())
        result = await tool.execute(file_token="doc_1", block_id="b1")
        assert result.is_error is True
        assert "No live Feishu channel" in result

    async def test_error_when_api_fails(self, monkeypatch):
        docapi.register_doc_client("feishu", object())
        monkeypatch.setattr(docapi, "fetch_block", lambda *a, **k: None)
        tool = FeishuDocxGetBlockTool.create(MagicMock())
        result = await tool.execute(file_token="doc_1", block_id="b1")
        assert result.is_error is True
