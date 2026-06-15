"""Тесты `app.services.llm.OllamaClient`.

Покрытие — по `_docs/testing.md` §3.2.
Все сценарии работают на моках, без сетевых вызовов.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from ollama import ResponseError

from app.services.llm import (
    LLMBadResponse,
    LLMTimeout,
    LLMUnavailable,
    OllamaClient,
)


@pytest.fixture
def client() -> OllamaClient:
    return OllamaClient(base_url="http://localhost:11434", timeout=10.0)


def _chat_resp(text: str) -> SimpleNamespace:
    return SimpleNamespace(message=SimpleNamespace(content=text))


async def test_chat_success(client, mocker):
    mocker.patch.object(client._client, "chat", return_value=_chat_resp("hello"))
    out = await client.chat([{"role": "user", "content": "hi"}], model="qwen3.5:4b")
    assert out == "hello"


async def test_chat_forwards_think_default_false(client, mocker):
    chat_mock = mocker.patch.object(client._client, "chat", return_value=_chat_resp("ok"))
    await client.chat([{"role": "user", "content": "hi"}], model="m")
    assert chat_mock.await_args.kwargs["think"] is False


async def test_chat_forwards_think_from_constructor(mocker):
    thinking = OllamaClient(base_url="http://localhost:11434", timeout=10.0, think=True)
    chat_mock = mocker.patch.object(thinking._client, "chat", return_value=_chat_resp("ok"))
    await thinking.chat([{"role": "user", "content": "hi"}], model="m")
    assert chat_mock.await_args.kwargs["think"] is True


async def test_chat_think_per_call_override(client, mocker):
    chat_mock = mocker.patch.object(client._client, "chat", return_value=_chat_resp("ok"))
    await client.chat([{"role": "user", "content": "hi"}], model="m", think=True)
    assert chat_mock.await_args.kwargs["think"] is True


async def test_chat_forwards_keep_alive(mocker):
    c = OllamaClient(base_url="http://localhost:11434", timeout=10.0, keep_alive="30m")
    chat_mock = mocker.patch.object(c._client, "chat", return_value=_chat_resp("ok"))
    await c.chat([{"role": "user", "content": "hi"}], model="m")
    assert chat_mock.await_args.kwargs["keep_alive"] == "30m"


async def test_chat_forwards_temperature_from_constructor(mocker):
    c = OllamaClient(base_url="http://localhost:11434", timeout=10.0, temperature=0.7)
    chat_mock = mocker.patch.object(c._client, "chat", return_value=_chat_resp("ok"))
    await c.chat([{"role": "user", "content": "hi"}], model="m")
    assert chat_mock.await_args.kwargs["options"]["temperature"] == 0.7


async def test_chat_temperature_per_call_override(client, mocker):
    chat_mock = mocker.patch.object(client._client, "chat", return_value=_chat_resp("ok"))
    await client.chat([{"role": "user", "content": "hi"}], model="m", temperature=0.3)
    assert chat_mock.await_args.kwargs["options"]["temperature"] == 0.3


async def test_embed_success(client, mocker):
    mocker.patch.object(
        client._client, "embeddings", return_value=SimpleNamespace(embedding=[0.1, 0.2, 0.3])
    )
    out = await client.embed("text", model="nomic-embed-text")
    assert out == [0.1, 0.2, 0.3]


async def test_list_models_success(client, mocker):
    mocker.patch.object(
        client._client,
        "list",
        return_value=SimpleNamespace(
            models=[
                SimpleNamespace(model="qwen3.5:4b", size=2_800_000_000),
                SimpleNamespace(model="qwen3.6:35b", size=23_000_000_000),
            ]
        ),
    )
    sizes = await client.list_models()
    assert sizes == {"qwen3.5:4b": 2_800_000_000, "qwen3.6:35b": 23_000_000_000}


async def test_list_models_returns_empty_on_error(client, mocker):
    mocker.patch.object(
        client._client, "list", side_effect=httpx.ConnectError("refused")
    )
    assert await client.list_models() == {}


async def test_chat_timeout_maps_to_llm_timeout(client, mocker):
    mocker.patch.object(
        client._client, "chat", side_effect=httpx.TimeoutException("slow")
    )
    with pytest.raises(LLMTimeout):
        await client.chat([{"role": "user", "content": "hi"}], model="m")


async def test_chat_connect_error_maps_to_unavailable(client, mocker):
    mocker.patch.object(
        client._client, "chat", side_effect=httpx.ConnectError("refused")
    )
    with pytest.raises(LLMUnavailable):
        await client.chat([{"role": "user", "content": "hi"}], model="m")


async def test_chat_http_404_maps_to_bad_response(client, mocker):
    mocker.patch.object(
        client._client, "chat", side_effect=ResponseError("model not found", 404)
    )
    with pytest.raises(LLMBadResponse):
        await client.chat([{"role": "user", "content": "hi"}], model="m")


async def test_chat_http_5xx_maps_to_bad_response(client, mocker):
    mocker.patch.object(
        client._client, "chat", side_effect=ResponseError("server error", 500)
    )
    with pytest.raises(LLMBadResponse):
        await client.chat([{"role": "user", "content": "hi"}], model="m")


async def test_chat_empty_response_maps_to_bad_response(client, mocker):
    mocker.patch.object(client._client, "chat", return_value=_chat_resp(""))
    with pytest.raises(LLMBadResponse):
        await client.chat([{"role": "user", "content": "hi"}], model="m")


async def test_embed_empty_response_maps_to_bad_response(client, mocker):
    mocker.patch.object(
        client._client, "embeddings", return_value=SimpleNamespace(embedding=[])
    )
    with pytest.raises(LLMBadResponse):
        await client.embed("text", model="m")


async def test_embed_connect_error_maps_to_unavailable(client, mocker):
    mocker.patch.object(
        client._client, "embeddings", side_effect=httpx.ConnectError("refused")
    )
    with pytest.raises(LLMUnavailable):
        await client.embed("text", model="m")


async def test_chat_logs_metrics(client, mocker, caplog):
    mocker.patch.object(client._client, "chat", return_value=_chat_resp("answer"))
    with caplog.at_level("INFO", logger="app.services.llm"):
        await client.chat([{"role": "user", "content": "hi"}], model="qwen3.5:4b")
    assert any(
        "kind=chat" in r.message and "model=qwen3.5:4b" in r.message and "status=ok" in r.message
        for r in caplog.records
    )


async def test_chat_logs_queue_wait_ms(client, mocker, caplog):
    mocker.patch.object(client._client, "chat", return_value=_chat_resp("answer"))
    with caplog.at_level("INFO", logger="app.services.llm"):
        await client.chat([{"role": "user", "content": "hi"}], model="m")
    assert any("queue_wait_ms=" in r.message for r in caplog.records)


async def test_chat_logs_performance_metrics(client, mocker, caplog):
    resp = _chat_resp("answer")
    resp.eval_count = 100
    resp.eval_duration = 2_000_000_000  # 2 секунды в наносекундах
    mocker.patch.object(client._client, "chat", return_value=resp)
    with caplog.at_level("INFO", logger="app.services.llm"):
        await client.chat([{"role": "user", "content": "hi"}], model="m")
    # Проверяем, что think, out_tok и tok_per_s присутствуют в extra
    assert any(
        getattr(r, "think", None) is False
        and getattr(r, "out_tok", None) == 100
        and getattr(r, "tok_per_s", None) == 50.0
        for r in caplog.records
    )


def _make_tracking_chat():
    """Async side_effect, отслеживающий пиковую конкуренцию вызовов."""
    state = {"in_flight": 0, "max_in_flight": 0}

    async def _chat(**kwargs):
        state["in_flight"] += 1
        state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
        await asyncio.sleep(0.02)
        state["in_flight"] -= 1
        return _chat_resp("ok")

    return _chat, state


async def test_chat_semaphore_serializes_calls(mocker):
    client = OllamaClient(base_url="http://localhost:11434", timeout=10.0, max_concurrency=1)
    chat_fn, state = _make_tracking_chat()
    mocker.patch.object(client._client, "chat", side_effect=chat_fn)
    await asyncio.gather(
        *[client.chat([{"role": "user", "content": "hi"}], model="m") for _ in range(4)]
    )
    assert state["max_in_flight"] == 1


async def test_chat_semaphore_respects_configured_limit(mocker):
    client = OllamaClient(base_url="http://localhost:11434", timeout=10.0, max_concurrency=2)
    chat_fn, state = _make_tracking_chat()
    mocker.patch.object(client._client, "chat", side_effect=chat_fn)
    await asyncio.gather(
        *[client.chat([{"role": "user", "content": "hi"}], model="m") for _ in range(4)]
    )
    assert state["max_in_flight"] == 2


def test_estimate_tokens_string():
    assert OllamaClient.estimate_tokens("a" * 40) == 10


def test_estimate_tokens_messages():
    msgs = [{"role": "user", "content": "x" * 12}, {"role": "assistant", "content": "y" * 8}]
    assert OllamaClient.estimate_tokens(msgs) == 5


async def test_close_does_not_raise(client):
    await client.close()
