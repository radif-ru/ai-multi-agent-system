"""Тесты диспетчера апдейтов MAX (`MaxUpdateDispatcher`)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.adapters.max.adapter import MaxUpdateDispatcher


@pytest.fixture
def dispatcher() -> MaxUpdateDispatcher:
    return MaxUpdateDispatcher(client=AsyncMock())


def _message_update(*, text: str = "", attachments=None) -> dict:
    body: dict = {"text": text}
    if attachments is not None:
        body["attachments"] = attachments
    return {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 1},
            "recipient": {"chat_id": 10},
            "body": body,
        },
    }


async def test_text_routed_to_text_handler(
    dispatcher: MaxUpdateDispatcher, mocker
) -> None:
    text_h = mocker.patch.object(dispatcher, "_handle_text", new=AsyncMock())
    cmd_h = mocker.patch.object(dispatcher, "_handle_command", new=AsyncMock())

    await dispatcher.dispatch(_message_update(text="привет"))

    text_h.assert_awaited_once()
    cmd_h.assert_not_awaited()


async def test_command_routed_to_command_handler(
    dispatcher: MaxUpdateDispatcher, mocker
) -> None:
    text_h = mocker.patch.object(dispatcher, "_handle_text", new=AsyncMock())
    cmd_h = mocker.patch.object(dispatcher, "_handle_command", new=AsyncMock())

    await dispatcher.dispatch(_message_update(text="/help"))

    cmd_h.assert_awaited_once()
    text_h.assert_not_awaited()


async def test_attachment_routed_to_attachment_handler(
    dispatcher: MaxUpdateDispatcher, mocker
) -> None:
    files_h = mocker.patch.object(
        dispatcher, "_handle_attachments", new=AsyncMock()
    )
    text_h = mocker.patch.object(dispatcher, "_handle_text", new=AsyncMock())

    await dispatcher.dispatch(
        _message_update(text="подпись", attachments=[{"type": "file"}])
    )

    files_h.assert_awaited_once()
    text_h.assert_not_awaited()


async def test_non_message_update_ignored(
    dispatcher: MaxUpdateDispatcher, mocker
) -> None:
    text_h = mocker.patch.object(dispatcher, "_handle_text", new=AsyncMock())

    await dispatcher.dispatch({"update_type": "bot_added", "chat_id": 1})

    text_h.assert_not_awaited()


async def test_empty_message_ignored(
    dispatcher: MaxUpdateDispatcher, mocker
) -> None:
    text_h = mocker.patch.object(dispatcher, "_handle_text", new=AsyncMock())
    cmd_h = mocker.patch.object(dispatcher, "_handle_command", new=AsyncMock())

    await dispatcher.dispatch(_message_update(text="   "))

    text_h.assert_not_awaited()
    cmd_h.assert_not_awaited()
