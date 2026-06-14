"""Точка входа MAX-адаптера.

Запуск через `python -m app.max_main`.

Переиспользует channel-agnostic сборку зависимостей `app.main._build_components`
(те же `core` / `agents` / `tools` / `memory`), добавляя транспорт MAX:
`_wire_max` собирает `MaxClient` + `MaxUpdateDispatcher`, `_run_polling`
крутит long polling, `_shutdown` корректно закрывает ресурсы. По образцу
`app/main.py` (graceful shutdown по сигналам, фоновое восстановление журналов).

См. `_docs/architecture.md` §3.1, §8.4 и спринт 09, задача 2.3.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from app.adapters.max.adapter import MaxUpdateDispatcher
from app.adapters.max.client import MaxClient, MaxError
from app.config import Settings
from app.core.logging_config import setup_logging
from app.main import _Components, _build_components, _shutdown_components
from app.observability import setup_sentry
from app.services.journal_recovery import recover_pending_journals

logger = logging.getLogger(__name__)


def _wire_max(c: _Components) -> tuple[MaxClient, MaxUpdateDispatcher]:
    """Собрать транспорт MAX поверх уже построенных компонентов."""
    assert c.settings.max_bot_token is not None  # гарантирует main()
    client = MaxClient(
        token=c.settings.max_bot_token,
        base_url=c.settings.max_api_base_url,
        poll_timeout=c.settings.max_poll_timeout,
    )
    dispatcher = MaxUpdateDispatcher(client=client, components=c)
    return client, dispatcher


async def _run_polling(
    client: MaxClient,
    dispatcher: MaxUpdateDispatcher,
    *,
    poll_timeout: int,
) -> None:
    """Long polling loop. Вынесен отдельно, чтобы smoke-тест мог замокать
    всю сетевую часть одной точкой (как `app.main._start_polling`).

    Сетевые ошибки логируются и не валят цикл (экспоненциальный backoff);
    ошибки обработки конкретного апдейта изолированы.
    """
    marker: int | None = None
    backoff = 1.0
    while True:
        try:
            data = await client.get_updates(marker=marker, timeout=poll_timeout)
        except MaxError as exc:
            logger.error("max polling error: %s", exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
            continue
        backoff = 1.0
        for update in data.get("updates", []):
            try:
                await dispatcher.dispatch(update)
            except Exception:  # noqa: BLE001
                logger.exception("max: ошибка обработки апдейта")
        new_marker = data.get("marker")
        if new_marker is not None:
            marker = new_marker


async def _shutdown(client: MaxClient, components: _Components) -> None:
    try:
        await client.close()
    except Exception:  # noqa: BLE001
        logger.exception("ошибка при закрытии MaxClient")
    await _shutdown_components(components)


async def main() -> None:
    """Async-точка входа MAX-адаптера: сборка, polling, graceful shutdown."""
    settings = Settings()
    setup_logging(settings)
    setup_sentry(settings)

    if not settings.max_bot_token:
        logger.error(
            "MAX_BOT_TOKEN не задан — MAX-канал не запускается. "
            "Задайте токен в .env (business.max.ru → Чат-боты → Интеграция)."
        )
        return

    shutdown_event = asyncio.Event()

    def signal_handler() -> None:
        logger.info("Получен сигнал shutdown, останавливаем MAX-адаптер...")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, signal_handler)
    loop.add_signal_handler(signal.SIGINT, signal_handler)

    if not settings.dangerous_tools_allowlist:
        logger.info(
            "DANGEROUS_TOOLS_ALLOWLIST пуст: опасные tools (http_request, read_file) "
            "запрещены (secure by default)."
        )

    components = await _build_components(settings)
    client, dispatcher = _wire_max(components)

    recovery_task: asyncio.Task | None = None
    if components.dialog_journal is not None:
        recovery_task = asyncio.create_task(
            recover_pending_journals(
                journal=components.dialog_journal,
                archiver=components.archiver,
                concurrency=settings.journal_recovery_concurrency,
                min_chars=settings.journal_recovery_min_chars,
            ),
            name="journal_recovery",
        )

    try:
        logger.info("MAX adapter started")
        # Ждём ПЕРВОЕ из {завершение polling, сигнал shutdown}: иначе при
        # падении polling main() висел бы на shutdown_event.wait() навсегда,
        # а исключение терялось бы (см. _docs/current-state.md §3).
        polling_task = asyncio.create_task(
            _run_polling(
                client, dispatcher, poll_timeout=settings.max_poll_timeout
            )
        )
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        done, _pending = await asyncio.wait(
            {polling_task, shutdown_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if polling_task in done:
            # polling завершился сам (штатно или с исключением): снимаем
            # ожидание сигнала и пробрасываем результат — при падении
            # сработает top-level логгер run() и Sentry.
            shutdown_task.cancel()
            try:
                await shutdown_task
            except asyncio.CancelledError:
                pass
            polling_task.result()
        else:
            # Пришёл сигнал shutdown — гасим polling.
            polling_task.cancel()
            try:
                await polling_task
            except asyncio.CancelledError:
                pass
    finally:
        if recovery_task is not None and not recovery_task.done():
            recovery_task.cancel()
            try:
                await recovery_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await _shutdown(client, components)


def run() -> None:
    """Синхронный wrapper для `python -m app.max_main`."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise
    except BaseException:
        logger.exception("необработанное исключение на верхнем уровне")
        raise


if __name__ == "__main__":  # pragma: no cover
    run()
