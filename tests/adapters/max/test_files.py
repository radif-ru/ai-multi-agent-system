"""Тесты `app.adapters.max.files.download_max_file` (моки httpx, без сети).

См. спринт 09, задача 4.1.
"""

from __future__ import annotations

import httpx
import pytest

from app.adapters.max.client import MaxClient
from app.adapters.max.files import FileTooLargeError, download_max_file

URL = "https://fu.oneme.ru/download/abc"


def _client(handler) -> MaxClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(
        base_url="https://platform-api.max.ru",
        headers={"Authorization": "tok"},
        transport=transport,
    )
    return MaxClient(token="tok", client=http)


async def test_download_saves_into_user_subdir(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"hello world")

    client = _client(handler)
    path = await download_max_file(
        client, URL, max_size_mb=20, tmp_dir=tmp_path, user_id=42,
        filename="report.pdf",
    )

    assert path.read_bytes() == b"hello world"
    assert path.parent == (tmp_path / "42").resolve()
    assert path.suffix == ".pdf"


async def test_path_stays_within_tmp_base_dir(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x")

    client = _client(handler)
    path = await download_max_file(
        client, URL, max_size_mb=20, tmp_dir=tmp_path, user_id=7,
    )

    assert tmp_path.resolve() in path.resolve().parents


async def test_content_length_over_limit_raises(tmp_path) -> None:
    big = b"x" * (1024 * 1024 + 10)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=big)

    client = _client(handler)
    with pytest.raises(FileTooLargeError):
        await download_max_file(
            client, URL, max_size_mb=1, tmp_dir=tmp_path, user_id=1,
        )


async def test_streamed_bytes_over_limit_raises(tmp_path) -> None:
    async def gen():
        # Без content-length: лимит ловится во время потоковой загрузки.
        yield b"x" * (1024 * 1024 + 10)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=gen())

    client = _client(handler)
    with pytest.raises(FileTooLargeError):
        await download_max_file(
            client, URL, max_size_mb=1, tmp_dir=tmp_path, user_id=1,
        )
