"""Тесты `app.adapters.max.client.MaxClient` (моки httpx, без сети)."""

from __future__ import annotations

import logging

import httpx
import pytest

from app.adapters.max.client import (
    MaxBadResponse,
    MaxClient,
    MaxTimeout,
    MaxUnavailable,
)

TOKEN = "super-secret-max-token"


def _client(handler) -> MaxClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(
        base_url="https://platform-api.max.ru",
        headers={"Authorization": TOKEN},
        transport=transport,
    )
    return MaxClient(token=TOKEN, client=http)


async def test_get_me_returns_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/me"
        assert request.headers["Authorization"] == TOKEN
        return httpx.Response(200, json={"user_id": 1, "name": "My Bot"})

    client = _client(handler)
    me = await client.get_me()
    assert me["user_id"] == 1
    assert me["name"] == "My Bot"


async def test_get_updates_passes_marker_and_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/updates"
        assert request.url.params["marker"] == "42"
        assert request.url.params["timeout"] == "30"
        return httpx.Response(200, json={"updates": [], "marker": 43})

    client = _client(handler)
    data = await client.get_updates(marker=42)
    assert data["marker"] == 43
    assert data["updates"] == []


async def test_get_updates_omits_marker_when_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "marker" not in request.url.params
        return httpx.Response(200, json={"updates": [], "marker": 1})

    client = _client(handler)
    await client.get_updates()


async def test_send_message_to_user_puts_text_in_body() -> None:
    import json as _json

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/messages"
        assert request.url.params["user_id"] == "777"
        body = _json.loads(request.content)
        assert body == {"text": "hello"}
        return httpx.Response(200, json={"message": {"body": {"text": "hello"}}})

    client = _client(handler)
    res = await client.send_message("hello", user_id=777)
    assert res["message"]["body"]["text"] == "hello"


async def test_send_message_requires_exactly_one_target() -> None:
    client = _client(lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValueError):
        await client.send_message("x")
    with pytest.raises(ValueError):
        await client.send_message("x", user_id=1, chat_id=2)


async def test_timeout_maps_to_max_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    client = _client(handler)
    with pytest.raises(MaxTimeout):
        await client.get_me()


async def test_connect_error_maps_to_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = _client(handler)
    with pytest.raises(MaxUnavailable):
        await client.get_me()


async def test_http_error_maps_to_bad_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    client = _client(handler)
    with pytest.raises(MaxBadResponse):
        await client.get_me()


async def test_invalid_json_maps_to_bad_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    client = _client(handler)
    with pytest.raises(MaxBadResponse):
        await client.get_me()


async def test_token_not_leaked_in_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"user_id": 1})

    client = _client(handler)
    with caplog.at_level(logging.INFO):
        await client.get_me()

    for record in caplog.records:
        assert TOKEN not in record.getMessage()
        for value in getattr(record, "__dict__", {}).values():
            assert TOKEN not in str(value)
