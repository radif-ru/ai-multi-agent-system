"""Диспетчер апдейтов MAX.

Диспетчер определяет тип входящего события (команда / текст / вложение) и
вызывает соответствующий обработчик. Обработчики текста и команд (Этап 3)
вызывают единый доменный контракт `core.handle_user_task` и общий
`CommandRegistry`; вложения (Этап 4) скачиваются и маршрутизируются в
существующий конвейер (`read_document` / `Vision` / `Transcriber`).

Адаптер тонкий: знает только про транспорт (`MaxClient`) и доменный контракт,
саму бизнес-логику не дублирует.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from app.adapters.max.client import MAX_MESSAGE_TEXT_LEN, MaxClient
from app.adapters.max.files import FileTooLargeError, download_max_file
from app.commands import CommandRegistry
from app.commands.context import CommandContext
from app.core.events import MessageReceived, ResponseGenerated
from app.core.orchestrator import handle_user_task
from app.security import get_global_mapper, sanitize_user_input
from app.services.llm import LLMBadResponse, LLMTimeout, LLMUnavailable
from app.services.transcribe import Transcriber, is_transcriber_available
from app.services.vision import Vision
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
FILE_TOO_LARGE_REPLY = (
    "Файл слишком большой, отправьте файл меньшего размера."
)
GENERIC_FILE_ERROR_REPLY = "Не удалось обработать вложение, попробуйте ещё раз."
VISION_UNAVAILABLE_REPLY = (
    "Распознавание изображений недоступно: не настроена vision-модель."
)
VOICE_UNAVAILABLE_REPLY = (
    "Распознавание речи недоступно, установите faster-whisper."
)
UNSUPPORTED_ATTACHMENT_REPLY = "Этот тип вложения пока не поддерживается."


class MaxUpdateDispatcher:
    """Маршрутизирует апдейты MAX (`GET /updates`) по типу содержимого."""

    def __init__(
        self, *, client: MaxClient, components: "_Components | None" = None
    ) -> None:
        self._client = client
        self._c = components
        self._command_registry = (
            CommandRegistry() if components is not None else None
        )

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
        """Команда (`/...`) → общий `CommandRegistry` → ответ в MAX."""
        c = self._c
        if c is None or self._command_registry is None:
            logger.warning("max: команда без компонентов — пропуск")
            return

        user_id, chat_id = _extract_ids(message)
        if user_id is None or chat_id is None:
            logger.warning("max: не удалось определить user_id/chat_id")
            return

        parts = text.split(maxsplit=1)
        command_name = parts[0][1:]  # убираем ведущий слеш
        args = parts[1] if len(parts) > 1 else ""

        ctx = await self._build_command_context(user_id, chat_id, message)

        if command_name == "new":

            async def _progress_callback(progress_text: str) -> None:
                await self._send(chat_id, progress_text)

            result = await self._command_registry.execute(
                command_name, ctx, args=args,
                progress_callback=_progress_callback,
            )
        else:
            result = await self._command_registry.execute(
                command_name, ctx, args=args
            )

        await self._send(chat_id, result.text)

    async def _build_command_context(
        self, user_id: int, chat_id: int, message: dict[str, Any]
    ) -> CommandContext:
        c = self._c
        assert c is not None
        user = None
        if c.users is not None:
            user, _ = await c.users.get_or_create(
                CHANNEL, str(user_id), _display_name(message, user_id)
            )
        return CommandContext(
            user_id=user_id,
            chat_id=chat_id,
            settings=c.settings,
            user_settings=c.user_settings,
            prompts=c.prompts,
            tools=c.tools,
            skills=c.skills,
            conversations=c.conversations,
            archiver=c.archiver,
            users=c.users,
            user=user,
            channel=CHANNEL,
            journal=c.dialog_journal,
        )

    async def _handle_attachments(
        self, message: dict[str, Any], attachments: list[Any]
    ) -> None:
        """Вложение MAX → скачать → существующий конвейер обработки файлов."""
        c = self._c
        if c is None:
            logger.warning("max: вложение без компонентов — пропуск")
            return

        user_id, chat_id = _extract_ids(message)
        if user_id is None or chat_id is None:
            logger.warning("max: не удалось определить user_id/chat_id")
            return

        attachment = _first_supported(attachments)
        if attachment is None:
            await self._send(chat_id, UNSUPPORTED_ATTACHMENT_REPLY)
            return

        att_type = attachment.get("type")
        url = (attachment.get("payload") or {}).get("url")
        if not url:
            logger.warning("max: вложение type=%s без payload.url", att_type)
            await self._send(chat_id, GENERIC_FILE_ERROR_REPLY)
            return

        # Голос/аудио: проверяем доступность распознавания до скачивания.
        if att_type == "audio" and not is_transcriber_available():
            await self._send(chat_id, VOICE_UNAVAILABLE_REPLY)
            return
        # Фото: без vision-модели описывать нечем.
        if att_type == "image" and not c.settings.vision_model:
            await self._send(chat_id, VISION_UNAVAILABLE_REPLY)
            return

        caption = ((message.get("body") or {}).get("text") or "").strip()
        try:
            file_path = await download_max_file(
                self._client,
                url,
                max_size_mb=c.settings.max_max_file_mb,
                tmp_dir=c.settings.tmp_base_dir,
                user_id=user_id,
                filename=attachment.get("filename"),
            )
        except FileTooLargeError:
            await self._send(chat_id, FILE_TOO_LARGE_REPLY)
            return
        except Exception:  # noqa: BLE001
            logger.exception("max: ошибка скачивания вложения user=%s", user_id)
            await self._send(chat_id, GENERIC_FILE_ERROR_REPLY)
            return

        if att_type == "file":
            goal, kind = await self._build_document_goal(file_path, caption)
        elif att_type == "image":
            goal, kind = await self._build_image_goal(file_path, caption)
        else:  # audio
            built = await self._build_audio_goal(file_path)
            if built is None:
                await self._send(chat_id, VOICE_UNAVAILABLE_REPLY)
                return
            goal, kind = built

        await self._process_goal(
            message, user_id, chat_id, goal, kind=kind, file_path=file_path
        )

    async def _build_document_goal(
        self, file_path: Any, caption: str
    ) -> tuple[str, str]:
        file_id = get_global_mapper().generate_id(file_path)
        goal = (
            f"Пользователь прислал документ (ID: {file_id}, путь: {file_path}). "
            f"Caption: {caption}. Прочитай через read_document с параметром "
            f"file_id={file_id} и ответь по сути."
        )
        return goal, "document"

    async def _build_image_goal(
        self, file_path: Any, caption: str
    ) -> tuple[str, str]:
        c = self._c
        assert c is not None and c.settings.vision_model
        vision = Vision(c.llm, c.settings.vision_model)
        description = await vision.describe(file_path, caption)
        goal = (
            f"Пользователь прислал изображение. Caption: {caption}. "
            f"Описание изображения: {description}. Ответь по сути."
        )
        return goal, "image"

    async def _build_audio_goal(self, file_path: Any) -> tuple[str, str] | None:
        c = self._c
        assert c is not None
        transcriber = Transcriber(
            model=c.settings.whisper_model, language=c.settings.whisper_language
        )
        text = await asyncio.to_thread(transcriber.transcribe, file_path)
        if not text:
            return None
        file_id = get_global_mapper().generate_id(file_path)
        goal = (
            f"Голосовое сообщение (ID: {file_id}, путь: {file_path})\n"
            f"Транскрипция: {text}"
        )
        return goal, "voice"

    async def _process_goal(
        self,
        message: dict[str, Any],
        user_id: int,
        chat_id: int,
        goal: str,
        *,
        kind: str,
        file_path: Any,
    ) -> None:
        """Общий путь файлового goal: события → core → ответ в MAX."""
        c = self._c
        assert c is not None

        user = None
        if c.users is not None:
            user, _ = await c.users.get_or_create(
                CHANNEL, str(user_id), _display_name(message, user_id)
            )

        mapper = get_global_mapper()
        file_id = mapper.generate_id(file_path)
        if c.event_bus is not None and user is not None:
            await c.event_bus.publish(MessageReceived(
                user=user,
                text=goal,
                conversation_id=str(chat_id),
                channel=CHANNEL,
                kind=kind,
                file_id=file_id,
                file_path=str(file_path),
            ))

        sanitized = sanitize_user_input(goal, user_id=user_id, mode="warn")
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

    # -- транспорт --------------------------------------------------------

    async def _send(self, chat_id: int, text: str) -> None:
        """Отправить ответ в MAX, разбивая длинный текст под лимит API."""
        for part in split_long_message(text, MAX_MESSAGE_TEXT_LEN):
            await self._client.send_message(part, chat_id=chat_id)


_SUPPORTED_ATTACHMENT_TYPES = ("file", "image", "audio")


def _first_supported(attachments: list[Any]) -> dict[str, Any] | None:
    """Вернуть первое поддерживаемое вложение (file / image / audio)."""
    for att in attachments:
        if isinstance(att, dict) and att.get("type") in _SUPPORTED_ATTACHMENT_TYPES:
            return att
    return None


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
