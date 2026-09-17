"""Tests for redact_message_in_session (chat recall support)."""
from nanobot.session.manager import (
    REDACTED_MESSAGE_TEXT,
    Session,
    redact_message_in_session,
)


def _session_with_messages(*messages: dict) -> Session:
    session = Session(key="feishu:ou_1")
    for message in messages:
        session.add_message(message.pop("role"), message.pop("content"), **message)
    return session


def test_redacts_matching_user_message() -> None:
    session = _session_with_messages(
        {"role": "user", "content": "secret", "message_id": "m1"},
        {"role": "assistant", "content": "reply"},
    )

    assert redact_message_in_session(session, "m1") is True
    assert session.messages[0]["content"] == REDACTED_MESSAGE_TEXT
    assert session.messages[1]["content"] == "reply"


def test_clears_media_on_redact() -> None:
    session = _session_with_messages(
        {"role": "user", "content": "secret", "message_id": "m1", "media": ["/tmp/a.png"]},
    )

    assert redact_message_in_session(session, "m1") is True
    assert session.messages[0]["media"] == []


def test_ignores_other_messages_and_roles() -> None:
    session = _session_with_messages(
        {"role": "user", "content": "keep", "message_id": "m2"},
        {"role": "assistant", "content": "m1", "message_id": "m1"},
    )

    assert redact_message_in_session(session, "m1") is False
    assert session.messages[0]["content"] == "keep"


def test_second_redact_is_noop() -> None:
    session = _session_with_messages(
        {"role": "user", "content": "secret", "message_id": "m1"},
    )
    assert redact_message_in_session(session, "m1") is True
    assert redact_message_in_session(session, "m1") is False
