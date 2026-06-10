"""Smoke-тест точки входа `app.main`.

См. `_docs/testing.md` §3.11. Сетевая часть (`bot.set_my_commands` +
`dispatcher.start_polling`) патчится одной точкой `_start_polling`,
чтобы тест работал офлайн и быстро.
"""

from __future__ import annotations

import inspect
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import console_main as console_main_module
from app import main as main_module
from app.main import main

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROMPT = REPO_ROOT / "app" / "prompts" / "agent_system.md"

ENV_KEYS = (
    "TELEGRAM_BOT_TOKEN",
    "OLLAMA_BASE_URL",
    "OLLAMA_DEFAULT_MODEL",
    "OLLAMA_AVAILABLE_MODELS",
    "OLLAMA_TIMEOUT",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIMENSIONS",
    "AGENT_MAX_STEPS",
    "AGENT_MAX_OUTPUT_CHARS",
    "HISTORY_MAX_MESSAGES",
    "HISTORY_SUMMARY_THRESHOLD",
    "MEMORY_DB_PATH",
    "MEMORY_CHUNK_SIZE",
    "MEMORY_CHUNK_OVERLAP",
    "MEMORY_SEARCH_TOP_K",
    "AGENT_SYSTEM_PROMPT_PATH",
    "LOG_LEVEL",
    "LOG_FILE",
    "LOG_LLM_CONTEXT",
)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    # Минимально-валидный токен для aiogram (regex `^\d+:[\w-]+$`).
    monkeypatch.setenv(
        "TELEGRAM_BOT_TOKEN",
        "123456789:AAFakeTokenForSmokeTesting_0123456789",
    )
    monkeypatch.setenv("AGENT_SYSTEM_PROMPT_PATH", str(DEFAULT_PROMPT))
    monkeypatch.setenv("MEMORY_DB_PATH", str(tmp_path / "memory.db"))
    monkeypatch.setenv("LOG_FILE", str(tmp_path / "agent.log"))
    monkeypatch.setenv("SENTRY_DSN", "")  # офлайн: не дёргаем GlitchTip
    return monkeypatch


def test_main_is_async_callable() -> None:
    """`python -c "from app.main import main; print(main)"` не падает."""
    assert callable(main)
    assert inspect.iscoroutinefunction(main)


@pytest.mark.asyncio
async def test_main_logs_bot_started_and_closes(
    env: pytest.MonkeyPatch,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    polling = AsyncMock()
    monkeypatch.setattr(main_module, "_start_polling", polling)

    shutdown_calls: list[tuple] = []
    real_shutdown = main_module._shutdown

    async def spy_shutdown(bot, components):
        shutdown_calls.append((bot, components))
        await real_shutdown(bot, components)

    monkeypatch.setattr(main_module, "_shutdown", spy_shutdown)

    await main()

    polling.assert_awaited_once()
    assert len(shutdown_calls) == 1
    # `setup_logging` пересобирает root-логгер, поэтому caplog не видит
    # сообщения; читаем файл логов (путь задан через LOG_FILE в фикстуре).
    import os

    log_path = Path(os.environ["LOG_FILE"])
    assert log_path.exists()
    assert "Bot started" in log_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_main_shuts_down_when_polling_raises(
    env: pytest.MonkeyPatch,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если polling упал — shutdown всё равно вызывается (finally)."""
    polling = AsyncMock(side_effect=RuntimeError("polling crashed"))
    monkeypatch.setattr(main_module, "_start_polling", polling)

    shutdown_called = AsyncMock()
    monkeypatch.setattr(main_module, "_shutdown", shutdown_called)

    with pytest.raises(RuntimeError, match="polling crashed"):
        await main()

    shutdown_called.assert_awaited_once()


def _components_with_closeables(*, semantic_memory: bool, dialog_journal: bool) -> MagicMock:
    """Собрать мок `_Components` с AsyncMock-методами `close()`."""
    components = MagicMock()
    components.llm.close = AsyncMock()
    components.users.close = AsyncMock()
    components.semantic_memory = MagicMock(close=AsyncMock()) if semantic_memory else None
    components.dialog_journal = MagicMock(close=AsyncMock()) if dialog_journal else None
    return components


@pytest.mark.asyncio
async def test_shutdown_components_closes_all_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Общий хелпер закрывает llm, semantic_memory, dialog_journal, users и FileIdMapper."""
    components = _components_with_closeables(semantic_memory=True, dialog_journal=True)
    mapper = MagicMock()
    monkeypatch.setattr("app.security.get_global_mapper", lambda: mapper)

    await main_module._shutdown_components(components)

    components.llm.close.assert_awaited_once()
    components.semantic_memory.close.assert_awaited_once()
    components.dialog_journal.close.assert_awaited_once()
    components.users.close.assert_awaited_once()
    mapper.close.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_components_tolerates_optional_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если semantic_memory/dialog_journal == None — хелпер не падает, остальное закрывает."""
    components = _components_with_closeables(semantic_memory=False, dialog_journal=False)
    monkeypatch.setattr("app.security.get_global_mapper", MagicMock())

    await main_module._shutdown_components(components)

    components.llm.close.assert_awaited_once()
    components.users.close.assert_awaited_once()


def _fake_asyncio_run(exc: BaseException):
    """Возвращает функцию, замещающую `asyncio.run`: корректно закрывает coro и бросает `exc`."""

    def _run(coro):
        coro.close()
        raise exc

    return _run


@pytest.mark.parametrize(
    "module, logger_name",
    [
        (main_module, "app.main"),
        (console_main_module, "app.console_main"),
    ],
    ids=["main", "console_main"],
)
def test_run_logs_unhandled_exception_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    module,
    logger_name: str,
) -> None:
    """`run()` логирует необработанное исключение через logger.exception и пробрасывает дальше."""
    monkeypatch.setattr(module.asyncio, "run", _fake_asyncio_run(RuntimeError("boom")))

    caplog.set_level(logging.ERROR, logger=logger_name)
    with pytest.raises(RuntimeError, match="boom"):
        module.run()

    records = [r for r in caplog.records if r.name == logger_name and r.levelno == logging.ERROR]
    assert records, "ожидаем запись уровня ERROR"
    assert any(r.exc_info is not None for r in records), "logger.exception должен приложить traceback"


@pytest.mark.parametrize(
    "module",
    [main_module, console_main_module],
    ids=["main", "console_main"],
)
def test_run_passes_keyboard_interrupt_without_logging(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    module,
) -> None:
    """`KeyboardInterrupt` пробрасывается без записи ERROR (штатное завершение)."""
    monkeypatch.setattr(module.asyncio, "run", _fake_asyncio_run(KeyboardInterrupt()))

    caplog.set_level(logging.ERROR)
    with pytest.raises(KeyboardInterrupt):
        module.run()

    assert not [r for r in caplog.records if r.levelno == logging.ERROR]
