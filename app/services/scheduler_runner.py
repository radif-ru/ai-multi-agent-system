"""Раннер запланированных задач — исполняет prompt через orchestrator.

``run_scheduled_task`` вызывается из ``SchedulerService._job_entrypoint``
(через ``set_run_task``). Изоляция от живой сессии: события шины **не**
публикуются (нет ``MessageReceived``/``ResponseGenerated``).

См. ``_docs/architecture.md`` §3.10 (контракт ``handle_user_task``).
"""

from __future__ import annotations

import html
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.orchestrator import handle_user_task
from app.security import sanitize_user_input
from app.services.llm import LLMBadResponse, LLMTimeout, LLMUnavailable
from app.services.scheduled_tasks import ScheduledTask, ScheduledTaskStore
from app.utils.text import split_long_message
from app.utils.tracing import bind_trace_id, bind_user_id, new_trace_id, reset_trace_id, reset_user_id

if TYPE_CHECKING:
    from app.agents.critic import CriticAgent
    from app.agents.executor import Executor
    from app.agents.planner import PlannerAgent
    from app.config import Settings
    from app.services.conversation import ConversationStore
    from app.services.llm import OllamaClient
    from app.services.memory import SemanticMemory
    from app.services.model_registry import UserSettingsRegistry

logger = logging.getLogger(__name__)

TELEGRAM_MAX_MESSAGE_LENGTH = 4096

LLM_UNAVAILABLE_REPLY = "LLM сейчас недоступна, попробуйте позже."
LLM_TIMEOUT_REPLY = "Модель слишком долго отвечает, попробуйте ещё раз."
LLM_BAD_RESPONSE_REPLY = "Модель ответила в неожиданном формате, попробуйте ещё раз."
GENERIC_ERROR_REPLY = "Что-то пошло не так при выполнении плановой задачи."


@dataclass
class RunnerDeps:
    """Зависимости раннера — те же компоненты, что в messages-хендлере."""

    conversations: "ConversationStore"
    executor: "Executor"
    settings: "Settings"
    llm: "OllamaClient"
    semantic_memory: "SemanticMemory | None"
    planner: "PlannerAgent"
    critic: "CriticAgent"
    user_settings: "UserSettingsRegistry"
    store: ScheduledTaskStore


NotifierFn = Callable[[int, str], Awaitable[None]]


def _format_result(task: ScheduledTask, result: str) -> str:
    """Префикс-шаблон для плановой задачи."""
    prompt_short = task.prompt[:80]
    if len(task.prompt) > 80:
        prompt_short += "…"
    return f"⏰ Плановая задача «{prompt_short}»:\n\n{result}"


async def run_scheduled_task(
    task: ScheduledTask,
    *,
    deps: RunnerDeps,
    notifier: NotifierFn,
) -> None:
    """Исполнить запланированную задачу и доставить результат.

    1. Биндим ``trace_id``/``user_id`` (try/finally со сбросом).
    2. Санитайзинг prompt.
    3. ``handle_user_task`` без публикации событий шины.
    4. Ошибки → человекочитаемый текст + ``mark_run(error)``.
    5. Успех → ``mark_run(ok)`` + доставка через notifier.
    """
    tid = new_trace_id()
    trace_token = bind_trace_id(tid)
    user_token = bind_user_id(task.user_id)
    try:
        await _run_inner(task, deps=deps, notifier=notifier)
    finally:
        reset_trace_id(trace_token)
        reset_user_id(user_token)


async def _run_inner(
    task: ScheduledTask,
    *,
    deps: RunnerDeps,
    notifier: NotifierFn,
) -> None:
    sanitized = sanitize_user_input(task.prompt, user_id=task.user_id, mode="warn")
    goal = (
        "Это автоматическое выполнение запланированной задачи. "
        "Выполни задачу прямо сейчас, не создавай новую задачу. "
        f"Задача: {sanitized}"
    )
    model = deps.user_settings.get_model(task.user_id)
    start = time.monotonic()
    logger.info("scheduler.run status=start task=%s", task.id)
    try:
        reply = await handle_user_task(
            goal,
            user_id=task.user_id,
            chat_id=task.chat_id,
            conversations=deps.conversations,
            executor=deps.executor,
            model=model,
            settings=deps.settings,
            llm=deps.llm,
            semantic_memory=deps.semantic_memory,
            planner=deps.planner,
            critic=deps.critic,
            user_settings=deps.user_settings,
            history=[],
        )
    except LLMTimeout:
        dur = time.monotonic() - start
        logger.warning("scheduler.run status=error task=%s reason=llm_timeout dur_ms=%d", task.id, int(dur * 1000))
        await deps.store.mark_run(task.id, status="error", when=_now_iso())
        await _deliver(notifier, task.chat_id, _format_result(task, LLM_TIMEOUT_REPLY))
        return
    except LLMUnavailable:
        dur = time.monotonic() - start
        logger.error("scheduler.run status=error task=%s reason=llm_unavailable dur_ms=%d", task.id, int(dur * 1000))
        await deps.store.mark_run(task.id, status="error", when=_now_iso())
        await _deliver(notifier, task.chat_id, _format_result(task, LLM_UNAVAILABLE_REPLY))
        return
    except LLMBadResponse as exc:
        dur = time.monotonic() - start
        logger.warning(
            "scheduler.run status=error task=%s reason=llm_bad_response err=%s dur_ms=%d",
            task.id, exc, int(dur * 1000),
        )
        await deps.store.mark_run(task.id, status="error", when=_now_iso())
        await _deliver(notifier, task.chat_id, _format_result(task, LLM_BAD_RESPONSE_REPLY))
        return
    except Exception:  # noqa: BLE001
        dur = time.monotonic() - start
        logger.exception("scheduler.run status=error task=%s dur_ms=%d", task.id, int(dur * 1000))
        await deps.store.mark_run(task.id, status="error", when=_now_iso())
        await _deliver(notifier, task.chat_id, _format_result(task, GENERIC_ERROR_REPLY))
        return

    dur_ms = int((time.monotonic() - start) * 1000)
    await deps.store.mark_run(task.id, status="ok", when=_now_iso())
    logger.info("scheduler.run status=ok task=%s dur_ms=%d", task.id, dur_ms)
    await _deliver(notifier, task.chat_id, _format_result(task, reply))


async def _deliver(notifier: NotifierFn, chat_id: int, text: str) -> None:
    """Доставить результат через notifier, разбивая длинный текст."""
    for part in split_long_message(text, TELEGRAM_MAX_MESSAGE_LENGTH):
        await notifier(chat_id, part)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_telegram_notifier(bot) -> NotifierFn:
    """Создать notifier для Telegram-бота.

    ``bot`` — экземпляр ``aiogram.Bot``. Текст экранируется через
    ``html.escape`` и отправляется с ``parse_mode=HTML``.
    """
    async def notifier(chat_id: int, text: str) -> None:
        for part in split_long_message(text, TELEGRAM_MAX_MESSAGE_LENGTH):
            await bot.send_message(chat_id, html.escape(part), parse_mode="HTML")

    return notifier


def make_console_notifier() -> NotifierFn:
    """Создать notifier для консоли — печатает результат в stdout."""

    async def notifier(chat_id: int, text: str) -> None:
        print(f"\n{'=' * 60}\n{text}\n{'=' * 60}\n")

    return notifier


def make_max_notifier(client) -> NotifierFn:
    """Создать notifier для MAX-клиента.

    ``client`` — экземпляр ``MaxClient``. Текст разбивается под лимит API.
    """
    from app.adapters.max.client import MAX_MESSAGE_TEXT_LEN

    async def notifier(chat_id: int, text: str) -> None:
        for part in split_long_message(text, MAX_MESSAGE_TEXT_LEN):
            await client.send_message(part, chat_id=chat_id)

    return notifier
