"""Диспетчер апдейтов MAX.

Диспетчер определяет тип входящего события (команда / текст / вложение) и
вызывает соответствующий обработчик. Обработчики текста и команд (Этап 3)
вызывают единый доменный контракт `core.handle_user_task` и общий
`CommandRegistry`; обработка файлов (Этап 4) — заглушка.

Адаптер тонкий: знает только про транспорт (`MaxClient`) и доменный контракт,
саму бизнес-логику не дублирует.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.adapters.max.client import MAX_MESSAGE_TEXT_LEN, MaxClient
from app.core.events import MessageReceived, ResponseGenerated
from app.core.orchestrator import handle_user_task
from app.security import sanitize_user_input
from app.services.llm import LLMBadResponse, LLMTimeout, LLMUnavailable
from app.utils.text import split_long_message

if TYPE_CHECKING:
    from app.main import _Components

logger = logging.getLogger(__name__)

CHANNEL = "max"

LLM_UNAVAILABLE_REPLY = "LLM сейчас недоступна, попробуйте позже."
LLM_TIMEOUT_REPLY = "Модель слишком долго отвечает, попробуйте ещё раз."
LLM_BAD_RESPONSE_REPLY = (
    "Модель ответила в неожиданном формате, попробуйте ещё раз."
)


class MaxUpdateDispatcher:
    """Маршрутизирует апдейты MAX (`GET /updates`) по типу содержимого."""

    def __init__(
        self, *, client: MaxClient, components: "_Components | None" = None
    ) -> None:
        self._client = client
        self._c = components

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

    # -- обработчики ------------------------------------------------------

    async def _handle_text(self, message: dict[str, Any], text: str) -> None:
        """Текстовое сообщение → `core.handle_user_task` → ответ в MAX."""
        c = self._c
        if c is None:
            logger.warning("max: текст без компонентов — пропуск")
            return

        user_id, chat_id = _extract_ids(message)
        if user_id is None or chat_id is None:
            logger.warning("max: не удалось определить user_id/chat_id")
            return

        user = None
        if c.users is not None:
            user, _ = await c.users.get_or_create(
                CHANNEL, str(user_id), _display_name(message, user_id)
            )

        if c.event_bus is not None and user is not None:
            await c.event_bus.publish(MessageReceived(
                user=user,
                text=text,
                conversation_id=str(chat_id),
                channel=CHANNEL,
            ))

        sanitized = sanitize_user_input(text, user_id=user_id, mode="warn")
        model = c.user_settings.get_model(user_id)

        try:
            reply = await handle_user_task(
                sanitized,
                user_id=user_id,
                chat_id=chat_id,
                conversations=c.conversations,
                executor=c.executor,
                model=model,
                settings=c.settings,
                llm=c.llm,
                semantic_memory=c.semantic_memory,
                planner=c.planner,
                critic=c.critic,
                user_settings=c.user_settings,
            )
        except LLMTimeout:
            logger.warning("max: LLM timeout user=%s", user_id)
            await self._send(chat_id, LLM_TIMEOUT_REPLY)
            return
        except LLMUnavailable:
            logger.error("max: LLM недоступна user=%s", user_id)
            await self._send(chat_id, LLM_UNAVAILABLE_REPLY)
            return
        except LLMBadResponse:
            logger.warning("max: LLM вернула некорректный ответ user=%s", user_id)
            await self._send(chat_id, LLM_BAD_RESPONSE_REPLY)
            return

        if c.event_bus is not None and user is not None:
            await c.event_bus.publish(ResponseGenerated(
                user=user,
                text=reply,
                conversation_id=str(chat_id),
                channel=CHANNEL,
            ))

        await self._send(chat_id, reply)

    async def _handle_command(self, message: dict[str, Any], text: str) -> None:
        command = text.split(maxsplit=1)[0]
        logger.info("max: команда %s (обработчик — Этап 3.2)", command)

    async def _handle_attachments(
        self, message: dict[str, Any], attachments: list[Any]
    ) -> None:
        logger.info("max: вложение (обработчик — Этап 4)")

    # -- транспорт --------------------------------------------------------

    async def _send(self, chat_id: int, text: str) -> None:
        """Отправить ответ в MAX, разбивая длинный текст под лимит API."""
        for part in split_long_message(text, MAX_MESSAGE_TEXT_LEN):
            await self._client.send_message(part, chat_id=chat_id)


def _extract_ids(message: dict[str, Any]) -> tuple[int | None, int | None]:
    """Достать `user_id` отправителя и `chat_id` из сообщения MAX."""
    sender = message.get("sender") or {}
    recipient = message.get("recipient") or {}
    user_id = sender.get("user_id")
    chat_id = recipient.get("chat_id")
    return user_id, chat_id


def _display_name(message: dict[str, Any], user_id: int) -> str:
    sender = message.get("sender") or {}
    return sender.get("name") or sender.get("username") or f"User {user_id}"
