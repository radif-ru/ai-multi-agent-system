"""Тесты сервиса `YandexDiskReader` (REST, read-only).

httpx-клиент подменяется фейком — реальной сети нет.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.services.yandex_disk import (
    DiskAuthError,
    DiskError,
    DiskNotConfigured,
    DiskUnavailable,
    YandexDiskReader,
)


def _settings(token="oauth-token", max_file_mb=20):
    return SimpleNamespace(
        yandex_disk_token=token, telegram_max_file_mb=max_file_mb
    )


class _FakeResponse:
    def __init__(self, status=200, payload=None, content=b""):
        self.status_code = status
        self._payload = payload or {}
        self.content = content

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, responses):
        # responses: dict url_suffix -> _FakeResponse
        self._responses = responses
        self.calls = []

    async def get(self, url, params=None, headers=None):
        self.calls.append((url, params, headers))
        for suffix, resp in self._responses.items():
            if url.endswith(suffix):
                return resp
        return _FakeResponse(404, {})

    async def put(self, url, content=None, **kwargs):
        self.calls.append((url, None, None))
        for suffix, resp in self._responses.items():
            if url.endswith(suffix):
                return resp
        return _FakeResponse(200, {})


# --- list_path -------------------------------------------------------------


async def test_list_path_returns_items():
    payload = {"_embedded": {"items": [
        {"name": "doc.pdf", "path": "disk:/doc.pdf", "type": "file",
         "size": 100, "modified": "2026-01-01"},
        {"name": "folder", "path": "disk:/folder", "type": "dir"},
    ]}}
    client = _FakeClient({"/resources": _FakeResponse(200, payload)})
    reader = YandexDiskReader(_settings(), client=client)
    items = await reader.list_path("/")
    assert [i["name"] for i in items] == ["doc.pdf", "folder"]
    assert items[0]["type"] == "file"
    # Заголовок Authorization передан.
    assert client.calls[0][2]["Authorization"] == "OAuth oauth-token"


async def test_list_path_file_without_embedded():
    payload = {"name": "doc.pdf", "path": "disk:/doc.pdf", "type": "file"}
    client = _FakeClient({"/resources": _FakeResponse(200, payload)})
    reader = YandexDiskReader(_settings(), client=client)
    items = await reader.list_path("/doc.pdf")
    assert items == [{
        "name": "doc.pdf", "path": "disk:/doc.pdf", "type": "file",
        "size": None, "modified": "",
    }]


async def test_not_configured_raises():
    reader = YandexDiskReader(_settings(token=None))
    with pytest.raises(DiskNotConfigured, match="YANDEX_DISK_TOKEN"):
        await reader.list_path("/")


async def test_auth_error_maps():
    client = _FakeClient({"/resources": _FakeResponse(403, {})})
    reader = YandexDiskReader(_settings(), client=client)
    with pytest.raises(DiskAuthError, match="токен"):
        await reader.list_path("/")


async def test_not_found_maps():
    client = _FakeClient({"/resources": _FakeResponse(404, {})})
    reader = YandexDiskReader(_settings(), client=client)
    with pytest.raises(DiskError, match="не найден"):
        await reader.list_path("/nope")


async def test_network_error_maps_to_unavailable():
    class _BadClient:
        async def get(self, *a, **k):
            raise httpx.ConnectError("refused")

    reader = YandexDiskReader(_settings(), client=_BadClient())
    with pytest.raises(DiskUnavailable, match="недоступен"):
        await reader.list_path("/")


# --- download --------------------------------------------------------------


async def test_download_saves_file(tmp_path):
    responses = {
        "/resources/download": _FakeResponse(200, {"href": "https://cdn/x"}),
        "cdn/x": _FakeResponse(200, content=b"file-bytes"),
    }
    client = _FakeClient(responses)
    reader = YandexDiskReader(_settings(), client=client)
    dest = await reader.download("disk:/doc.pdf", tmp_path)
    assert dest.read_bytes() == b"file-bytes"
    assert dest.name == "doc.pdf"


async def test_download_rejects_oversized(tmp_path):
    responses = {
        "/resources/download": _FakeResponse(200, {"href": "https://cdn/x"}),
        "cdn/x": _FakeResponse(200, content=b"x" * 2048),
    }
    client = _FakeClient(responses)
    reader = YandexDiskReader(_settings(max_file_mb=0), client=client)
    with pytest.raises(DiskError, match="лимит"):
        await reader.download("disk:/big.bin", tmp_path)


async def test_configured_flag():
    assert YandexDiskReader(_settings()).configured is True
    assert YandexDiskReader(_settings(token=None)).configured is False


# --- upload ----------------------------------------------------------------


async def test_upload_sends_file(tmp_path):
    local = tmp_path / "report.txt"
    local.write_bytes(b"hello-disk")
    responses = {
        "/resources/upload": _FakeResponse(200, {"href": "https://upload/x"}),
        "upload/x": _FakeResponse(200, {}),
    }
    client = _FakeClient(responses)
    reader = YandexDiskReader(_settings(), client=client)
    result = await reader.upload(local, "/uploads/report.txt")
    assert result == "/uploads/report.txt"
    # PUT на upload URL был вызван
    assert any("upload/x" in c[0] for c in client.calls)


async def test_upload_missing_local_file(tmp_path):
    reader = YandexDiskReader(_settings(), client=_FakeClient({}))
    with pytest.raises(DiskError, match="не найден"):
        await reader.upload(tmp_path / "nope.txt", "/uploads/nope.txt")


async def test_upload_rejects_oversized(tmp_path):
    local = tmp_path / "big.bin"
    local.write_bytes(b"x" * 2048)
    reader = YandexDiskReader(_settings(max_file_mb=0), client=_FakeClient({}))
    with pytest.raises(DiskError, match="лимит"):
        await reader.upload(local, "/uploads/big.bin")


async def test_upload_not_configured(tmp_path):
    local = tmp_path / "file.txt"
    local.write_bytes(b"data")
    reader = YandexDiskReader(_settings(token=None))
    with pytest.raises(DiskNotConfigured, match="YANDEX_DISK_TOKEN"):
        await reader.upload(local, "/uploads/file.txt")
