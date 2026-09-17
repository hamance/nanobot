"""Feishu Drive/docx API helpers shared by the channel runtime and agent tools.

This module is intentionally dependency-free at import time (no lark_oapi):
the channel registers its live client at startup and agent tools resolve it
by channel name, so credentials never need to be duplicated into tool config.
"""

from __future__ import annotations

import json
from typing import Any, cast

from loguru import logger

# Channel name (e.g. "feishu", "feishu.work") -> lark client.
_CLIENTS: dict[str, Any] = {}


def register_doc_client(channel_name: str, client: Any) -> None:
    """Expose a live Feishu client to agent tools for this channel instance."""
    _CLIENTS[channel_name] = client


def unregister_doc_client(channel_name: str) -> None:
    _CLIENTS.pop(channel_name, None)


def get_doc_client(channel_name: str | None) -> Any | None:
    """Resolve a registered client, preferring an exact channel name match."""
    if channel_name and channel_name in _CLIENTS:
        return _CLIENTS[channel_name]
    if len(_CLIENTS) == 1:
        return next(iter(_CLIENTS.values()))
    return _CLIENTS.get("feishu")


def _json_object(value: Any) -> dict[str, Any] | None:
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _request(client: Any, method: str, uri: str, body: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Run one authenticated REST call via the SDK's generic BaseRequest."""
    import lark_oapi as lark

    builder = (
        lark.BaseRequest.builder()
        .http_method(getattr(lark.HttpMethod, method))
        .uri(uri)
        .token_types({lark.AccessTokenType.APP})
    )
    if body is not None:
        # The SDK transport marshals the body itself (JSON.marshal); passing a
        # pre-encoded string gets double-serialized and fails with 9499.
        builder = builder.body(body).headers(
            {"Content-Type": "application/json; charset=utf-8"}
        )
    response = client.request(builder.build())
    if not response.success():
        logger.warning(
            "Feishu doc API {} {} failed: code={}, msg={}",
            method,
            uri,
            response.code,
            response.msg,
        )
        return None
    raw = _json_object(json.loads(response.raw.content)) or {}
    return _json_object(raw.get("data")) or raw


def batch_query_comments(
    client: Any,
    file_token: str,
    comment_id: str,
    *,
    file_type: str = "docx",
    with_relation: bool = True,
) -> dict[str, Any] | None:
    """Batch-query one comment; ``need_relation`` asks for its docx anchor.

    Relation data (positionInfo.blockID) is only returned for docx documents.
    """
    suffix = f"?file_type={file_type}" if file_type else ""
    return _request(
        client,
        "POST",
        f"/open-apis/drive/v1/files/{file_token}/comments/batch_query{suffix}",
        {"comment_ids": [comment_id], "need_relation": with_relation},
    )


def get_comment(
    client: Any,
    file_token: str,
    comment_id: str,
    *,
    file_type: str = "",
) -> dict[str, Any] | None:
    """Fetch one comment thread via GET (no anchor relation)."""
    suffix = f"?file_type={file_type}" if file_type else ""
    return _request(
        client,
        "GET",
        f"/open-apis/drive/v1/files/{file_token}/comments/{comment_id}{suffix}",
    )


def fetch_block(client: Any, document_id: str, block_id: str) -> dict[str, Any] | None:
    """GET one docx block (type, text content, children)."""
    return _request(
        client,
        "GET",
        f"/open-apis/docx/v1/documents/{document_id}/blocks/{block_id}",
    )


def update_block_text(client: Any, document_id: str, block_id: str, text: str) -> dict[str, Any] | None:
    """Replace the text elements of a docx text block (paragraph/heading/etc.)."""
    return _request(
        client,
        "PATCH",
        f"/open-apis/docx/v1/documents/{document_id}/blocks/{block_id}",
        {"update_text_elements": {"elements": [{"text_run": {"content": text}}]}},
    )


def reply_comment(
    client: Any,
    file_token: str,
    comment_id: str,
    text: str,
    *,
    file_type: str = "docx",
) -> dict[str, Any] | None:
    """Post a reply under a drive comment thread (notifies the commenter).

    ``file_type`` is a required query parameter on comment endpoints.
    """
    suffix = f"?file_type={file_type}" if file_type else ""
    return _request(
        client,
        "POST",
        f"/open-apis/drive/v1/files/{file_token}/comments/{comment_id}/replies{suffix}",
        {"content": {"elements": [{"type": "text_run", "text_run": {"text": text}}]}},
    )


def set_comment_solved(
    client: Any,
    file_token: str,
    comment_id: str,
    solved: bool,
    file_type: str = "docx",
) -> dict[str, Any] | None:
    """Mark a drive comment thread as solved (or reopen it)."""
    suffix = f"?file_type={file_type}" if file_type else ""
    return _request(
        client,
        "PATCH",
        f"/open-apis/drive/v1/files/{file_token}/comments/{comment_id}{suffix}",
        {"is_solved": solved},
    )
