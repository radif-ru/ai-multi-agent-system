"""Сервис чтения Яндекс.Диска (read-only) через REST API.

Обёртка над `https://cloud-api.yandex.net/v1/disk` (заголовок
`Authorization: OAuth <token>`): список ресурсов и скачивание файла в
каталог пользователя. Ошибки — иерархия `DiskError` с человекочитаемыми
сообщениями. См. `_docs/tools.md`.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

API_BASE = "https://cloud-api.yandex.net/v1/disk"


class DiskError(Exception):
    """Базовая ошибка Яндекс.Диска (сообщение — для пользователя)."""


class DiskNotConfigured(DiskError):
    """Токен диска не заполнен в `.env`."""


class DiskAuthError(DiskError):
    """Токен отвергнут (401/403)."""


class DiskUnavailable(DiskError):
    """Сервис недоступен, таймаут или иная ошибка сети."""


class YandexDiskReader:
    """Read-only доступ к Яндекс.Диску: список ресурсов и скачивание."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._settings = settings
        self._client = client  # для тестов; иначе создаём per-call
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._settings.yandex_disk_token)

    def _token(self) -> str:
        token = self._settings.yandex_disk_token
        if not token:
            raise DiskNotConfigured(
                "Яндекс.Диск не подключён: заполните YANDEX_DISK_TOKEN в .env "
                "(OAuth-токен с правом чтения диска, см. .env.example)."
            )
        return token

    async def list_path(
        self, path: str = "/", *, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Содержимое папки: `{name, path, type, size, modified}`."""
        token = self._token()
        data = await self._get(
            token,
            "/resources",
            {"path": path or "/", "limit": limit,
             "fields": "_embedded.items.name,_embedded.items.path,"
                       "_embedded.items.type,_embedded.items.size,"
                       "_embedded.items.modified,type"},
        )
        embedded = data.get("_embedded")
        if not embedded:
            # Путь указывает на файл, а не на папку.
            return [_resource(data)]
        return [_resource(item) for item in embedded.get("items", [])]

    async def download(self, path: str, dest_dir: Path) -> Path:
        """Скачать файл диска в `dest_dir`, вернуть локальный путь."""
        token = self._token()
        meta = await self._get(
            token, "/resources/download", {"path": path}
        )
        href = meta.get("href")
        if not href:
            raise DiskUnavailable(f"Не удалось получить ссылку на скачивание {path}.")
        limit_bytes = self._settings.telegram_max_file_mb * 1024 * 1024
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / Path(path).name
        await self._download_to(href, dest, limit_bytes)
        return dest

    # --- Внутреннее ------------------------------------------------------

    async def _get(
        self, token: str, endpoint: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        url = f"{API_BASE}{endpoint}"
        headers = {"Authorization": f"OAuth {token}"}
        started = time.monotonic()
        logger.info(
            "external.call service=yandex_disk endpoint=%s",
            endpoint,
            extra={"service": "yandex_disk", "endpoint": endpoint},
        )
        try:
            if self._client is not None:
                resp = await self._client.get(url, params=params, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            self._log_fail(endpoint, started, exc)
            raise DiskUnavailable(
                f"Яндекс.Диск недоступен: {exc}. Попробуйте позже."
            ) from exc
        self._raise_for_status(resp, started, endpoint)
        self._log_ok(endpoint, started)
        return resp.json()

    async def _download_to(self, href: str, dest: Path, limit_bytes: int) -> None:
        started = time.monotonic()
        try:
            if self._client is not None:
                resp = await self._client.get(href)
                content = resp.content
                self._raise_for_status(resp, started, "/download")
                if len(content) > limit_bytes:
                    raise DiskError(
                        f"Файл больше лимита {self._settings.telegram_max_file_mb} МБ."
                    )
                dest.write_bytes(content)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    async with client.stream("GET", href) as resp:
                        self._raise_for_status(resp, started, "/download")
                        total = 0
                        with dest.open("wb") as fh:
                            async for chunk in resp.aiter_bytes():
                                total += len(chunk)
                                if total > limit_bytes:
                                    fh.close()
                                    dest.unlink(missing_ok=True)
                                    raise DiskError(
                                        "Файл больше лимита "
                                        f"{self._settings.telegram_max_file_mb} МБ."
                                    )
                                fh.write(chunk)
        except httpx.HTTPError as exc:
            self._log_fail("/download", started, exc)
            raise DiskUnavailable(
                f"Не удалось скачать файл с Яндекс.Диска: {exc}."
            ) from exc
        self._log_ok("/download", started)

    def _raise_for_status(
        self, resp: httpx.Response, started: float, endpoint: str
    ) -> None:
        if resp.status_code in (401, 403):
            self._log_fail(endpoint, started, Exception(f"HTTP {resp.status_code}"))
            raise DiskAuthError(
                "Яндекс.Диск отклонил токен (проверьте YANDEX_DISK_TOKEN в .env "
                "и права на чтение диска)."
            )
        if resp.status_code == 404:
            raise DiskError("Путь на Яндекс.Диске не найден.")
        if resp.status_code >= 400:
            self._log_fail(endpoint, started, Exception(f"HTTP {resp.status_code}"))
            raise DiskUnavailable(f"Яндекс.Диск вернул HTTP {resp.status_code}.")

    @staticmethod
    def _log_ok(endpoint: str, started: float) -> None:
        dur_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "external.ok service=yandex_disk endpoint=%s dur_ms=%d",
            endpoint, dur_ms,
            extra={"service": "yandex_disk", "endpoint": endpoint,
                   "duration_ms": dur_ms, "status": "ok"},
        )

    @staticmethod
    def _log_fail(endpoint: str, started: float, exc: Exception) -> None:
        dur_ms = int((time.monotonic() - started) * 1000)
        logger.error(
            "external.fail service=yandex_disk endpoint=%s dur_ms=%d error=%s",
            endpoint, dur_ms, exc,
            extra={"service": "yandex_disk", "endpoint": endpoint,
                   "duration_ms": dur_ms, "status": "fail", "error": str(exc)},
        )


def _resource(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": item.get("name", ""),
        "path": item.get("path", ""),
        "type": item.get("type", ""),
        "size": item.get("size"),
        "modified": item.get("modified", ""),
    }
