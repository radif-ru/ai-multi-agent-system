"""Тесты маршрутизации вложений MAX в конвейер обработки файлов.

Сеть и доменный слой замоканы: `download_max_file`, `handle_user_task`,
`Vision`, `Transcriber` патчатся. См. спринт 09, задача 4.2.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.adapters.max import adapter as adapter_module
from app.adapters.max.adapter import MaxUpdateDispatcher


def _components(*, vision_model: str | None = "vmodel") -> SimpleNamespace:
    user = SimpleNamespace(id=1)
    settings = SimpleNamespace(
        vision_model=vision_model,
        whisper_model="base",
        whisper_language="ru",
        max_max_file_mb=20,
        tmp_base_dir=Path("/tmp/data"),
    )
    return SimpleNamespace(
        settings=settings,
        user_settings=SimpleNamespace(get_model=lambda uid: "model-x"),
        conversations=object(),
        executor=object(),
        llm=object(),
        semantic_memory=None,
        planner=None,
        critic=None,
        users=AsyncMock(get_or_create=AsyncMock(return_value=(user, True))),
        event_bus=AsyncMock(),
    )


def _attachment_update(attachment: dict, *, caption: str = "") -> dict:
    return {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 1, "name": "Иван"},
            "recipient": {"chat_id": 10},
            "body": {"text": caption, "attachments": [attachment]},
        },
    }


@pytest.fixture
def patched(mocker):
    mocker.patch.object(
        adapter_module, "download_max_file",
        new=AsyncMock(return_value=Path("/tmp/data/1/file.bin")),
    )
    mocker.patch.object(
        adapter_module, "handle_user_task",
        new=AsyncMock(return_value="ответ"),
    )
    mocker.patch.object(
        adapter_module, "get_global_mapper",
        return_value=MagicMock(generate_id=MagicMock(return_value="fid")),
    )
    return mocker


async def test_document_routed_with_read_document_goal(patched) -> None:
    client = AsyncMock()
    dispatcher = MaxUpdateDispatcher(client=client, components=_components())

    await dispatcher.dispatch(_attachment_update(
        {"type": "file", "filename": "a.pdf", "payload": {"url": "u"}},
        caption="разбери",
    ))

    goal = adapter_module.handle_user_task.await_args.args[0]
    assert "read_document" in goal
    assert "file_id=fid" in goal
    client.send_message.assert_awaited_once_with("ответ", chat_id=10)


async def test_image_routed_with_vision_description(patched) -> None:
    vision = MagicMock()
    vision.describe = AsyncMock(return_value="кот на диване")
    patched.patch.object(
        adapter_module, "Vision", return_value=vision
    )
    client = AsyncMock()
    dispatcher = MaxUpdateDispatcher(client=client, components=_components())

    await dispatcher.dispatch(_attachment_update(
        {"type": "image", "payload": {"url": "u"}}, caption="что тут",
    ))

    vision.describe.assert_awaited_once()
    goal = adapter_module.handle_user_task.await_args.args[0]
    assert "кот на диване" in goal
    client.send_message.assert_awaited_once_with("ответ", chat_id=10)


async def test_audio_routed_with_transcription(patched) -> None:
    patched.patch.object(
        adapter_module, "is_transcriber_available", return_value=True
    )
    transcriber = MagicMock()
    transcriber.transcribe = MagicMock(return_value="привет мир")
    patched.patch.object(
        adapter_module, "Transcriber", return_value=transcriber
    )
    client = AsyncMock()
    dispatcher = MaxUpdateDispatcher(client=client, components=_components())

    await dispatcher.dispatch(_attachment_update(
        {"type": "audio", "payload": {"url": "u"}},
    ))

    goal = adapter_module.handle_user_task.await_args.args[0]
    assert "привет мир" in goal
    client.send_message.assert_awaited_once_with("ответ", chat_id=10)


async def test_image_without_vision_model_hint(patched) -> None:
    client = AsyncMock()
    dispatcher = MaxUpdateDispatcher(
        client=client, components=_components(vision_model=None)
    )

    await dispatcher.dispatch(_attachment_update(
        {"type": "image", "payload": {"url": "u"}},
    ))

    adapter_module.handle_user_task.assert_not_awaited()
    client.send_message.assert_awaited_once_with(
        adapter_module.VISION_UNAVAILABLE_REPLY, chat_id=10
    )


async def test_audio_without_transcriber_hint(patched) -> None:
    patched.patch.object(
        adapter_module, "is_transcriber_available", return_value=False
    )
    client = AsyncMock()
    dispatcher = MaxUpdateDispatcher(client=client, components=_components())

    await dispatcher.dispatch(_attachment_update(
        {"type": "audio", "payload": {"url": "u"}},
    ))

    adapter_module.handle_user_task.assert_not_awaited()
    client.send_message.assert_awaited_once_with(
        adapter_module.VOICE_UNAVAILABLE_REPLY, chat_id=10
    )


async def test_file_too_large_hint(patched) -> None:
    patched.patch.object(
        adapter_module, "download_max_file",
        new=AsyncMock(side_effect=adapter_module.FileTooLargeError(30, 20)),
    )
    client = AsyncMock()
    dispatcher = MaxUpdateDispatcher(client=client, components=_components())

    await dispatcher.dispatch(_attachment_update(
        {"type": "file", "payload": {"url": "u"}},
    ))

    adapter_module.handle_user_task.assert_not_awaited()
    client.send_message.assert_awaited_once_with(
        adapter_module.FILE_TOO_LARGE_REPLY, chat_id=10
    )


async def test_unsupported_attachment_hint(patched) -> None:
    client = AsyncMock()
    dispatcher = MaxUpdateDispatcher(client=client, components=_components())

    await dispatcher.dispatch(_attachment_update(
        {"type": "sticker", "payload": {"url": "u"}},
    ))

    adapter_module.handle_user_task.assert_not_awaited()
    client.send_message.assert_awaited_once_with(
        adapter_module.UNSUPPORTED_ATTACHMENT_REPLY, chat_id=10
    )
