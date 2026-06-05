"""Диспетчер апдейтов MAX.

Этап 2 спринта 09 — транспортный каркас: диспетчер определяет тип входящего
события (команда / текст / вложение) и вызывает соответствующий обработчик.
Реальные обработчики текста и команд (Этап 3) и файлов (Этап 4) подключаются
позже; пока это заглушки, чтобы polling-цикл не падал на необработанных типах.

Адаптер тонкий: знает только про транспорт (`MaxClient`) и доменный контракт,
который появится на следующих этапах. Доменные слои здесь не вызываются.
"""

from __future__ import annotations

import logging
from typing import Any

from app.adapters.max.client import MaxClient

logger = logging.getLogger(__name__)

CHANNEL = "max"


class MaxUpdateDispatcher:
    """Маршрутизирует апдейты MAX (`GET /updates`) по типу содержимого."""

    def __init__(self, *, client: MaxClient) -> None:
        self._client = client

    async def dispatch(self, update: dict[str, Any]) -> None:
        """Разобрать апдейт и направить в нужный обработчик.

        На Этапе 2 обрабатывается только `message_created`; прочие типы
        логируются и пропускаются. Внутри сообщения порядок маршрутизации:
        вложение → команда (`/...`) → произвольный текст.
        """
        update_type = update.get("update_type")
        if update_type != "message_created":
            logger.debug("max: пропуск update_type=%s", update_type)
            return

        message = update.get("message")
        if not isinstance(message, dict):
            logger.warning("max: message_created без объекта message")
            return

        body = message.get("body") or {}
        text = (body.get("text") or "").strip()
        attachments = body.get("attachments") or []

        if attachments:
            await self._handle_attachments(message, attachments)
        elif text.startswith("/"):
            await self._handle_command(message, text)
        elif text:
            await self._handle_text(message, text)
        else:
            logger.debug("max: сообщение без текста и вложений — пропуск")

    # -- обработчики (заглушки Этапа 2, наполняются в Этапах 3–4) ---------

    async def _handle_text(self, message: dict[str, Any], text: str) -> None:
        logger.info("max: текстовое сообщение (обработчик — Этап 3)")

    async def _handle_command(self, message: dict[str, Any], text: str) -> None:
        command = text.split(maxsplit=1)[0]
        logger.info("max: команда %s (обработчик — Этап 3)", command)

    async def _handle_attachments(
        self, message: dict[str, Any], attachments: list[Any]
    ) -> None:
        logger.info("max: вложение (обработчик — Этап 4)")
