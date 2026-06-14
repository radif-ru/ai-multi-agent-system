"""Одноразовая зачистка backlog «висящих» сессий журнала (спринт 11, задача 3.3).

Неинтерактивный maintenance-прогон: переиспользует `app.main._build_components`
и `recover_pending_journals`, чтобы один раз обойти `dialog_journal` той же
`data/memory.db`, что и боевой процесс. «Мусорные» сессии (суммарный `content`
ниже `JOURNAL_RECOVERY_MIN_CHARS`) закрываются без LLM, реальные — архивируются
через `Archiver` (нужен запущенный Ollama). Печатает pending «до/после» и
сводку, затем корректно закрывает ресурсы и выходит.

Запуск из корня репозитория (с поднятым Ollama и валидным `.env`):

    python -m scripts.recover_backlog

Идемпотентно: повторный запуск после успешного прогона должен показать
`pending: 0` (backlog не растёт между рестартами). БД не коммитим (gitignore).
"""

from __future__ import annotations

import asyncio
import logging

from app.config import Settings
from app.core.logging_config import setup_logging
from app.main import _build_components, _shutdown_components
from app.observability import setup_sentry
from app.services.journal_recovery import recover_pending_journals

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = Settings()
    setup_logging(settings)
    # Глушим шумные HTTP-логи (httpcore/httpx на DEBUG заливают консоль и
    # топят итоговую сводку); прогресс recovery/archiver (INFO) остаётся.
    for noisy in ("httpcore", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    setup_sentry(settings)

    components = await _build_components(settings)
    journal = components.dialog_journal
    if journal is None:
        logger.error("dialog_journal недоступен — нечего восстанавливать")
        await _shutdown_components(components)
        return

    try:
        before = await journal.pending_conversations()
        print(f"pending до прогона: {len(before)}")

        summary = await recover_pending_journals(
            journal=journal,
            archiver=components.archiver,
            concurrency=settings.journal_recovery_concurrency,
            min_chars=settings.journal_recovery_min_chars,
            start_delay=0.0,
        )

        after = await journal.pending_conversations()
        print("\n" + "=" * 48)
        print("ЗАЧИСТКА BACKLOG — ИТОГ")
        print(f"  pending до:    {len(before)}")
        print(f"  sessions:      {summary['sessions']}")
        print(f"  archived:      {summary['archived']}")
        print(f"  failed:        {summary['failed']}")
        print(f"  pending после: {len(after)}")
        print("=" * 48)
        if after:
            print("осталось висеть (вероятно, упавшие при архивации):")
            for user_id, chat_id, conversation_id in after:
                print(f"  user={user_id} chat={chat_id} conv={conversation_id}")
    finally:
        await _shutdown_components(components)


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise
    except BaseException:
        logger.exception("необработанное исключение в recover_backlog")
        raise


if __name__ == "__main__":  # pragma: no cover
    run()
