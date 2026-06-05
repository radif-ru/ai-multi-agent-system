"""Тесты обработчика текста MAX-адаптера (`MaxUpdateDispatcher._handle_text`).

Сеть и доменный слой замоканы: `handle_user_task` патчится, `MaxClient` —
`AsyncMock`. См. спринт 09, задача 3.1.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.adapters.max import adapter as adapter_module
from app.adapters.max.adapter import MaxUpdateDispatcher
from app.adapters.max.client import MAX_MESSAGE_TEXT_LEN
from app.core.events import MessageReceived, ResponseGenerated
from app.services.llm import LLMBadResponse, LLMTimeout, LLMUnavailable


def _components() -> SimpleNamespace:
    user = SimpleNamespace(id=1)
    return SimpleNamespace(
        settings=SimpleNamespace(),
        user_settings=SimpleNamespace(get_model=lambda uid: "model-x"),
        conversations=object(),
        executor=object(),
        llm=None,
        semantic_memory=None,
        planner=None,
        critic=None,
        users=AsyncMock(get_or_create=AsyncMock(return_value=(user, True))),
        event_bus=AsyncMock(),
    )


def _text_update(text: str) -> dict:
    return {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 1, "name": "Иван"},
            "recipient": {"chat_id": 10},
            "body": {"text": text},
        },
    }


async def test_text_calls_handle_user_task_and_sends(mocker) -> None:
    client = AsyncMock()
    c = _components()
    dispatcher = MaxUpdateDispatcher(client=client, components=c)
    hut = mocker.patch.object(
        adapter_module, "handle_user_task", new=AsyncMock(return_value="ответ")
    )

    await dispatcher.dispatch(_text_update("привет"))

    hut.assert_awaited_once()
    assert hut.await_args.kwargs["user_id"] == 1
    assert hut.await_args.kwargs["chat_id"] == 10
    assert hut.await_args.kwargs["model"] == "model-x"
    client.send_message.assert_awaited_once_with("ответ", chat_id=10)


async def test_text_publishes_events_with_max_channel(mocker) -> None:
    client = AsyncMock()
    c = _components()
    dispatcher = MaxUpdateDispatcher(client=client, components=c)
    mocker.patch.object(
        adapter_module, "handle_user_task", new=AsyncMock(return_value="ответ")
    )

    await dispatcher.dispatch(_text_update("привет"))

    published = [call.args[0] for call in c.event_bus.publish.await_args_list]
    received = [e for e in published if isinstance(e, MessageReceived)]
    generated = [e for e in published if isinstance(e, ResponseGenerated)]
    assert received and received[0].channel == "max"
    assert generated and generated[0].channel == "max"


async def test_long_reply_split_into_parts(mocker) -> None:
    client = AsyncMock()
    c = _components()
    dispatcher = MaxUpdateDispatcher(client=client, components=c)
    long_reply = "a" * (MAX_MESSAGE_TEXT_LEN + 5)
    mocker.patch.object(
        adapter_module, "handle_user_task", new=AsyncMock(return_value=long_reply)
    )

    await dispatcher.dispatch(_text_update("привет"))

    assert client.send_message.await_count == 2


@pytest.mark.parametrize(
    "exc, reply",
    [
        (LLMTimeout(), adapter_module.LLM_TIMEOUT_REPLY),
        (LLMUnavailable(), adapter_module.LLM_UNAVAILABLE_REPLY),
        (LLMBadResponse("boom"), adapter_module.LLM_BAD_RESPONSE_REPLY),
    ],
)
async def test_llm_errors_mapped_to_hints(mocker, exc, reply) -> None:
    client = AsyncMock()
    c = _components()
    dispatcher = MaxUpdateDispatcher(client=client, components=c)
    mocker.patch.object(
        adapter_module, "handle_user_task", new=AsyncMock(side_effect=exc)
    )

    await dispatcher.dispatch(_text_update("привет"))

    client.send_message.assert_awaited_once_with(reply, chat_id=10)
    # При ошибке LLM ResponseGenerated не публикуется.
    published = [call.args[0] for call in c.event_bus.publish.await_args_list]
    assert not any(isinstance(e, ResponseGenerated) for e in published)
