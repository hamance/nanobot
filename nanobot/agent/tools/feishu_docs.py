"""Tools for Feishu doc comments and docx blocks.

These tools reuse the live Feishu channel client (registered at channel
startup), so they work with any channel instance and need no extra config.
They are only enabled while a Feishu channel is running.
"""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

import asyncio
import json
from typing import Any

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import ToolContext, current_request_context
from nanobot.agent.tools.schema import BooleanSchema, StringSchema, tool_parameters_schema


def _client_for_current_channel() -> Any:
    from nanobot.channels.feishu import docapi

    request = current_request_context()
    channel = request.channel if request is not None else None
    client = docapi.get_doc_client(channel)
    if client is None:
        raise RuntimeError(
            "No live Feishu channel client. Enable the Feishu channel first."
        )
    return client


@tool_parameters(
    tool_parameters_schema(
        file_token=StringSchema("The drive file token (document id) of the docx document."),
        block_id=StringSchema("The docx block id, e.g. from a comment anchor block."),
        required=["file_token", "block_id"],
    )
)
class FeishuDocxGetBlockTool(Tool):
    """Read one docx block (type and text content) to inspect before editing."""

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls()

    @property
    def name(self) -> str:
        return "feishu_docx_get_block"

    @property
    def description(self) -> str:
        return (
            "Read one Feishu docx block (block type and text content). "
            "Use before feishu_docx_update_block to confirm the target block."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        try:
            client = _client_for_current_channel()
        except RuntimeError as e:
            return ToolResult.error(str(e))
        from nanobot.channels.feishu import docapi

        block = await asyncio.to_thread(
            docapi.fetch_block, client, kwargs["file_token"], kwargs["block_id"]
        )
        if block is None:
            return ToolResult.error(
                f"Failed to fetch block {kwargs['block_id']} "
                f"(check the app has docx read permission on this document)."
            )
        return ToolResult(json.dumps(block, ensure_ascii=False))


@tool_parameters(
    tool_parameters_schema(
        file_token=StringSchema("The drive file token (document id) of the docx document."),
        block_id=StringSchema("The docx block id to replace, e.g. a comment anchor block."),
        text=StringSchema("The new plain text for the block."),
        required=["file_token", "block_id", "text"],
    )
)
class FeishuDocxUpdateBlockTool(Tool):
    """Replace the text of a docx block."""

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls()

    @property
    def name(self) -> str:
        return "feishu_docx_update_block"

    @property
    def description(self) -> str:
        return (
            "Replace the text content of one Feishu docx block "
            "(paragraph, heading, etc.). Only works on docx documents. "
            "Use feishu_docx_get_block first to confirm the block."
        )

    async def execute(self, **kwargs: Any) -> str:
        try:
            client = _client_for_current_channel()
        except RuntimeError as e:
            return ToolResult.error(str(e))
        from nanobot.channels.feishu import docapi

        result = await asyncio.to_thread(
            docapi.update_block_text,
            client,
            kwargs["file_token"],
            kwargs["block_id"],
            kwargs["text"],
        )
        if result is None:
            return ToolResult.error(
                f"Failed to update block {kwargs['block_id']} "
                f"(check the app has docx edit permission on this document)."
            )
        return ToolResult(f"Updated block {kwargs['block_id']}.")


@tool_parameters(
    tool_parameters_schema(
        file_token=StringSchema("The drive file token of the document."),
        comment_id=StringSchema("The comment thread id to reply to."),
        text=StringSchema("The reply text (plain text)."),
        file_type=StringSchema(
            "The drive file type (e.g. docx, doc, sheet). Defaults to docx."
        ),
        required=["file_token", "comment_id", "text"],
    )
)
class FeishuDocCommentReplyTool(Tool):
    """Reply under a Feishu doc comment thread."""

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls()

    @property
    def name(self) -> str:
        return "feishu_doc_comment_reply"

    @property
    def description(self) -> str:
        return (
            "Reply under a Feishu document comment thread. "
            "The reply appears in the doc and notifies the commenter. "
            "Prefer this over messaging the user when answering a doc comment."
        )

    async def execute(self, **kwargs: Any) -> str:
        try:
            client = _client_for_current_channel()
        except RuntimeError as e:
            return ToolResult.error(str(e))
        from nanobot.channels.feishu import docapi

        file_type = kwargs.get("file_type") or "docx"
        result = await asyncio.to_thread(
            docapi.reply_comment,
            client,
            kwargs["file_token"],
            kwargs["comment_id"],
            kwargs["text"],
            file_type=file_type,
        )
        if result is None:
            return ToolResult.error(
                f"Failed to reply to comment {kwargs['comment_id']} "
                f"(check the app has comment permission on this document)."
            )
        return ToolResult(f"Replied to comment {kwargs['comment_id']}.")


@tool_parameters(
    tool_parameters_schema(
        file_token=StringSchema("The drive file token of the document."),
        comment_id=StringSchema("The comment thread id to resolve."),
        solved=BooleanSchema(
            description="True to mark the comment as solved, false to reopen it.",
            default=True,
        ),
        file_type=StringSchema(
            "Optional drive file type (e.g. docx, sheet) when the API requires it."
        ),
        required=["file_token", "comment_id"],
    )
)
class FeishuDocCommentResolveTool(Tool):
    """Mark a Feishu doc comment thread as solved or reopen it."""

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls()

    @property
    def name(self) -> str:
        return "feishu_doc_comment_resolve"

    @property
    def description(self) -> str:
        return (
            "Mark a Feishu document comment thread as solved (or reopen it). "
            "Use after the requested doc change is done."
        )

    async def execute(self, **kwargs: Any) -> str:
        try:
            client = _client_for_current_channel()
        except RuntimeError as e:
            return ToolResult.error(str(e))
        from nanobot.channels.feishu import docapi

        solved = kwargs.get("solved", True)
        file_type = kwargs.get("file_type") or "docx"
        result = await asyncio.to_thread(
            docapi.set_comment_solved,
            client,
            kwargs["file_token"],
            kwargs["comment_id"],
            bool(solved),
            file_type,
        )
        if result is None:
            return ToolResult.error(
                f"Failed to update comment {kwargs['comment_id']} "
                f"(check the app has comment permission on this document)."
            )
        state = "solved" if solved else "reopened"
        return ToolResult(f"Comment {kwargs['comment_id']} marked as {state}.")
