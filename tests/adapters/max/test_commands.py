"""Тесты обработчика команд MAX-адаптера (`_handle_command`).

Команды проходят через реальный общий `CommandRegistry`; транспорт
(`MaxClient`) — `AsyncMock`. См. спринт 09, задача 3.2.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.adapters.max.adapter import MaxUpdateDispatcher


def _components() -> SimpleNamespace:
    user = SimpleNamespace(id=1)
    user_settings = SimpleNamespace(
        get_model=lambda uid: "model-x",
        get_prompt=lambda uid: None,
        get_reflection_mode=lambda uid: None,
        set_reflection_mode=MagicMock(),
    )
    return SimpleNamespace(
        settings=SimpleNamespace(
            agent_reflection_mode="OFF",
            tmp_base_dir="/tmp/max-test-nonexistent",
        ),
        user_settings=user_settings,
        prompts=SimpleNamespace(agent_system_template="PROMPT"),
        tools=SimpleNamespace(list_descriptions=lambda: []),
        skills=SimpleNamespace(list_descriptions=lambda: []),
        conversations=MagicMock(),
        archiver=AsyncMock(),
        users=AsyncMock(get_or_create=AsyncMock(return_value=(user, True))),
        dialog_journal=None,
    )


def _command_update(text: str) -> dict:
    return {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 1, "name": "Иван"},
            "recipient": {"chat_id": 10},
            "body": {"text": text},
        },
    }


async def test_help_returns_reply() -> None:
    client = AsyncMock()
    dispatcher = MaxUpdateDispatcher(client=client, components=_components())

    await dispatcher.dispatch(_command_update("/help"))

    client.send_message.assert_awaited_once()
    sent = client.send_message.await_args.args[0]
    assert "Команды:" in sent
    assert client.send_message.await_args.kwargs["chat_id"] == 10


async def test_mode_switches_and_replies() -> None:
    client = AsyncMock()
    c = _components()
    dispatcher = MaxUpdateDispatcher(client=client, components=c)

    await dispatcher.dispatch(_command_update("/mode deep"))

    c.user_settings.set_reflection_mode.assert_called_once_with(1, "DEEP")
    sent = client.send_message.await_args.args[0]
    assert "DEEP" in sent


async def test_unknown_command_hint() -> None:
    client = AsyncMock()
    dispatcher = MaxUpdateDispatcher(client=client, components=_components())

    await dispatcher.dispatch(_command_update("/nope"))

    sent = client.send_message.await_args.args[0]
    assert "Неизвестная команда" in sent


async def test_new_calls_archive_with_progress_callback() -> None:
    client = AsyncMock()
    c = _components()
    c.conversations.get_session_log.return_value = [
        {"role": "user", "content": "привет"}
    ]
    c.conversations.current_conversation_id.return_value = "conv-1"
    c.archiver.archive = AsyncMock(return_value=3)
    dispatcher = MaxUpdateDispatcher(client=client, components=c)

    await dispatcher.dispatch(_command_update("/new"))

    c.archiver.archive.assert_awaited_once()
    assert c.archiver.archive.await_args.kwargs["progress_callback"] is not None
    assert c.archiver.archive.await_args.kwargs["channel"] == "max"
    sent = client.send_message.await_args.args[0]
    assert "3" in sent
