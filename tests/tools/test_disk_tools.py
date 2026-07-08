"""Тесты tools `disk_list` и `disk_download` (Яндекс.Диск, read-only)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.security import clear_global_mapper, get_global_mapper
from app.services.yandex_disk import DiskAuthError, DiskNotConfigured
from app.tools import disk_download as disk_download_mod
from app.tools import disk_list as disk_list_mod
from app.tools.disk_download import DiskDownloadTool
from app.tools.disk_list import DiskListTool
from app.tools.errors import ToolError


def _ctx(tmp_path):
    settings = SimpleNamespace(
        yandex_disk_token="t",
        telegram_max_file_mb=20,
        get_user_tmp_dir=lambda uid: tmp_path / str(uid),
    )
    return SimpleNamespace(settings=settings, user_id=7)


class _FakeReader:
    def __init__(self, settings, *, items=None, exc=None, saved=None):
        self._items = items or []
        self._exc = exc
        self._saved = saved

    async def list_path(self, path="/", *, limit=50):
        if self._exc:
            raise self._exc
        return self._items

    async def download(self, path, dest_dir):
        if self._exc:
            raise self._exc
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / Path(path).name
        dest.write_bytes(b"data")
        return dest


# --- disk_list -------------------------------------------------------------


async def test_disk_list_returns_items(monkeypatch, tmp_path):
    items = [{"name": "a.txt", "path": "disk:/a.txt", "type": "file"}]
    monkeypatch.setattr(
        disk_list_mod, "YandexDiskReader",
        lambda settings: _FakeReader(settings, items=items),
    )
    out = json.loads(await DiskListTool().run({"path": "/"}, _ctx(tmp_path)))
    assert out["items"][0]["name"] == "a.txt"


async def test_disk_list_not_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(
        disk_list_mod, "YandexDiskReader",
        lambda settings: _FakeReader(
            settings, exc=DiskNotConfigured("Яндекс.Диск не подключён: YANDEX_DISK_TOKEN")
        ),
    )
    with pytest.raises(ToolError, match="YANDEX_DISK_TOKEN"):
        await DiskListTool().run({}, _ctx(tmp_path))


# --- disk_download ---------------------------------------------------------


async def test_disk_download_returns_file_id(monkeypatch, tmp_path):
    monkeypatch.setattr(
        disk_download_mod, "YandexDiskReader",
        lambda settings: _FakeReader(settings),
    )
    clear_global_mapper()
    try:
        out = json.loads(
            await DiskDownloadTool().run({"path": "disk:/doc.pdf"}, _ctx(tmp_path))
        )
        assert out["name"] == "doc.pdf"
        assert out["file_id"].startswith("file_")
        # file_id резолвится обратно в путь через глобальный маппер.
        resolved = get_global_mapper().get_path(out["file_id"])
        assert resolved is not None and resolved.name == "doc.pdf"
    finally:
        clear_global_mapper()


async def test_disk_download_requires_path(tmp_path):
    with pytest.raises(ToolError, match="path обязателен"):
        await DiskDownloadTool().run({"path": "  "}, _ctx(tmp_path))


async def test_disk_download_auth_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        disk_download_mod, "YandexDiskReader",
        lambda settings: _FakeReader(
            settings, exc=DiskAuthError("Яндекс.Диск отклонил токен")
        ),
    )
    with pytest.raises(ToolError, match="токен"):
        await DiskDownloadTool().run({"path": "disk:/x"}, _ctx(tmp_path))
