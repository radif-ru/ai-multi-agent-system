"""Точка входа консольного режима.

Запуск через `python -m app.console_main`.

См. `_docs/console-adapter.md`.
"""

from __future__ import annotations

import asyncio
import logging

from app.adapters.console.adapter import ConsoleAdapter
from app.config import Settings
from app.core import orchestrator as _orchestrator
from app.core.logging_config import setup_logging
from app.main import _Components, _build_components, _shutdown_components
from app.observability import setup_sentry
from app.services.conversation import ConversationStore

logger = logging.getLogger(__name__)

assert _orchestrator is not None  # явная зависимость для будущего DI


async def main() -> None:
    """Async-точка входа консольного режима."""
    settings = Settings()
    # Отключаем консольный вывод логов чтобы не смешивать с ответами агента
    setup_logging(settings, console_output=False)
    setup_sentry(settings)

    if not settings.dangerous_tools_allowlist:
        logger.info(
            "DANGEROUS_TOOLS_ALLOWLIST пуст: опасные tools (http_request, read_file) "
            "запрещены (secure by default). Чтобы включить — задайте в .env, например: "
            "DANGEROUS_TOOLS_ALLOWLIST=http_request,read_file"
        )

    components: _Components = await _build_components(settings)

    # Функция core.handle_user_task для текстовых сообщений
    async def core_handle_user_task(
        *,
        text: str,
        user_id: int,
        chat_id: int,
        conversations: ConversationStore,
        model: str | None = None,
        system_prompt: str | None = None,
    ) -> str:
        """Обёртка над core.orchestrator.handle_user_task."""
        from app.core import orchestrator

        return await orchestrator.handle_user_task(
            text=text,
            user_id=user_id,
            chat_id=chat_id,
            conversations=conversations,
            executor=components.executor,
            model=model,
            settings=settings,
            llm=components.llm,
            semantic_memory=components.semantic_memory,
            planner=components.planner,
            critic=components.critic,
            user_settings=components.user_settings,
        )

    adapter = ConsoleAdapter(
        user_id=-1,
        chat_id=-1,
        settings=settings,
        user_settings=components.user_settings,
        prompts=components.prompts,
        tools=components.tools,
        skills=components.skills,
        conversations=components.conversations,
        archiver=components.archiver,
        core_handle_user_task=core_handle_user_task,
        users=components.users,
        event_bus=components.event_bus,
        journal=components.dialog_journal,
    )

    try:
        logger.info("Console adapter started")
        await adapter.run()
    finally:
        await _shutdown_components(components)


def run() -> None:
    """Синхронный wrapper для `python -m app.console_main`."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise
    except BaseException:
        logger.exception("необработанное исключение на верхнем уровне")
        raise


if __name__ == "__main__":  # pragma: no cover
    run()
