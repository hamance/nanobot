# ruff: noqa: E402

"""Feishu defaults context-compaction notices to quiet (mobile IM)."""

import pytest

pytest.importorskip("lark_oapi")

from nanobot.channels.feishu.runtime import FeishuChannel


def test_feishu_opts_out_of_compaction_notices_by_default() -> None:
    assert FeishuChannel.send_compaction is False
