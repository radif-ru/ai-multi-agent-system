"""Async-клиент MAX Bot API на `httpx`.

Тонкая обёртка над REST API MAX (`dev.max.ru/docs-api`) без сторонних SDK.
Реализует методы, нужные адаптеру: `get_me` (идентификация/smoke),
`get_updates` (long polling) и `send_message`. По образцу
`app/services/llm.py`: один общий `httpx.AsyncClient`, явные исключения и
структурные логи `external.call` / `external.ok` / `external.fail`.

Авторизация — заголовок `Authorization: <token>` (передача токена в query
не поддерживается MAX). Токен не логируется: в `extra`-поля попадает только
результат `mask_secrets`.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.utils.secrets import mask_secrets

logger = logging.getLogger(__name__)

# Лимит длины текста сообщения в MAX (POST /messages, поле text).
MAX_MESSAGE_TEXT_LEN = 4000


class MaxError(Exception):
    """Базовое исключение MAX-клиента."""


class MaxTimeout(MaxError):
    """Таймаут при обращении к MAX Bot API."""


class MaxUnavailable(MaxError):
    """MAX Bot API недоступен (ошибка соединения и т.п.)."""


class MaxBadResponse(MaxError):
    """MAX вернул некорректный ответ (4xx/5xx, битый JSON)."""


class MaxClient:
    """Async-клиент MAX Bot API над общим `httpx.AsyncClient`."""

    def __init__(
        self,
        *,
        token: str,
        base_url: str = "https://platform-api.max.ru",
        poll_timeout: int = 30,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._poll_timeout = poll_timeout
        # Тайм-аут HTTP-запроса с запасом над long polling, чтобы сервер успел
        # вернуть пустой ответ по своему таймауту раньше клиентского.
        self._request_timeout = float(poll_timeout) + 10.0
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": token},
            timeout=self._request_timeout,
        )

    async def get_me(self) -> dict[str, Any]:
        """`GET /me` — информация о боте (идентификация / smoke)."""
        return await self._request("GET", "/me")

    async def get_updates(
        self,
        *,
        marker: int | None = None,
        timeout: int | None = None,
        limit: int = 100,
        types: str | None = None,
    ) -> dict[str, Any]:
        """`GET /updates` — long polling новых событий.

        `marker` — указатель на следующую страницу из предыдущего ответа
        (None для первого запроса). Возвращает `{"updates": [...], "marker": ...}`.
        """
        params: dict[str, Any] = {
            "limit": limit,
            "timeout": self._poll_timeout if timeout is None else timeout,
        }
        if marker is not None:
            params["marker"] = marker
        if types is not None:
            params["types"] = types
        return await self._request("GET", "/updates", params=params)

    async def send_message(
        self,
        text: str,
        *,
        user_id: int | None = None,
        chat_id: int | None = None,
        disable_link_preview: bool | None = None,
    ) -> dict[str, Any]:
        """`POST /messages` — отправить текстовое сообщение.

        Адресат задаётся через `user_id` ИЛИ `chat_id` (query-параметры);
        текст — в теле запроса (до 4000 символов).
        """
        if (user_id is None) == (chat_id is None):
            raise ValueError("send_message requires exactly one of user_id / chat_id")
        params: dict[str, Any] = {}
        if user_id is not None:
            params["user_id"] = user_id
        if chat_id is not None:
            params["chat_id"] = chat_id
        if disable_link_preview is not None:
            params["disable_link_preview"] = disable_link_preview
        return await self._request(
            "POST", "/messages", params=params, json={"text": text}
        )

    def stream(self, url: str) -> Any:
        """Контекст-менеджер потокового `GET` по абсолютному URL вложения.

        Используется для скачивания файлов из MAX (`payload.url` указывает на
        CDN, отличный от `base_url`). Возвращает `httpx`-stream как есть, чтобы
        вызывающий код мог контролировать размер на лету.
        """
        return self._client.stream("GET", url)

    async def close(self) -> None:
        await self._client.aclose()

    # -- internals --------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        logger.info(
            "external.call service=max method=%s path=%s",
            method, path,
            extra={
                "service": "max", "method": method, "path": path,
                "params": mask_secrets(params or {}),
            },
        )
        try:
            resp = await self._client.request(
                method, path, params=params, json=json
            )
        except httpx.TimeoutException as exc:
            self._log_fail(method, path, started, "timeout", exc)
            raise MaxTimeout(f"{method} {path} timeout: {exc}") from exc
        except httpx.RequestError as exc:
            self._log_fail(method, path, started, "unavailable", exc)
            raise MaxUnavailable(f"{method} {path} request error: {exc}") from exc

        if resp.status_code >= 400:
            self._log_fail(
                method, path, started, f"http {resp.status_code}", None
            )
            raise MaxBadResponse(
                f"{method} {path} http error {resp.status_code}: {resp.text}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            self._log_fail(method, path, started, "bad_json", exc)
            raise MaxBadResponse(f"{method} {path} invalid JSON: {exc}") from exc

        dur_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "external.ok service=max method=%s path=%s dur_ms=%d http_status=%d",
            method, path, dur_ms, resp.status_code,
            extra={
                "service": "max", "method": method, "path": path,
                "duration_ms": dur_ms, "status": "ok",
                "http_status": resp.status_code,
            },
        )
        return data if isinstance(data, dict) else {"result": data}

    @staticmethod
    def _log_fail(
        method: str,
        path: str,
        started: float,
        status: str,
        exc: Exception | None,
    ) -> None:
        dur_ms = int((time.monotonic() - started) * 1000)
        logger.error(
            "external.fail service=max method=%s path=%s dur_ms=%d status=%s",
            method, path, dur_ms, status,
            extra={
                "service": "max", "method": method, "path": path,
                "duration_ms": dur_ms, "status": status,
                "error": str(exc) if exc is not None else status,
            },
        )
