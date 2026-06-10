"""Smoke- и polling-тесты точки входа `app.max_main`.

Сетевая часть (`_run_polling` / `MaxClient.get_updates`) мокается, тесты
работают офлайн. См. спринт 09, задача 2.3.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import max_main as max_main_module
from app.adapters.max.client import MaxUnavailable
from app.max_main import main

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROMPT = REPO_ROOT / "app" / "prompts" / "agent_system.md"


def test_main_is_async_callable() -> None:
    """`python -c "from app.max_main import main; print(main)"` не падает."""
    assert callable(main)
    assert inspect.iscoroutinefunction(main)


def test_adapter_importable() -> None:
    """`python -c "import app.adapters.max.adapter"` не падает."""
    import app.adapters.max.adapter as adapter

    assert adapter is not None


async def test_run_polling_dispatches_and_advances_marker() -> None:
    client = AsyncMock()
    client.get_updates.side_effect = [
        {"updates": [{"update_type": "message_created"}], "marker": 7},
        asyncio.CancelledError(),
    ]
    dispatcher = AsyncMock()

    with pytest.raises(asyncio.CancelledError):
        await max_main_module._run_polling(client, dispatcher, poll_timeout=30)

    dispatcher.dispatch.assert_awaited_once_with({"update_type": "message_created"})
    # Второй вызов get_updates получил продвинутый marker.
    assert client.get_updates.await_args_list[1].kwargs["marker"] == 7


async def test_run_polling_backoff_on_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = AsyncMock()
    client.get_updates.side_effect = [
        MaxUnavailable("down"),
        asyncio.CancelledError(),
    ]
    dispatcher = AsyncMock()

    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(max_main_module.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await max_main_module._run_polling(client, dispatcher, poll_timeout=30)

    assert sleeps, "ожидаем backoff-паузу после сетевой ошибки"
    dispatcher.dispatch.assert_not_awaited()


async def test_main_returns_early_without_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Пустой MAX_BOT_TOKEN — канал не запускается, сборка не вызывается."""
    monkeypatch.setenv(
        "TELEGRAM_BOT_TOKEN", "123456789:AAFakeTokenForSmokeTesting_0123"
    )
    monkeypatch.delenv("MAX_BOT_TOKEN", raising=False)
    monkeypatch.setenv("SENTRY_DSN", "")  # офлайн: не дёргаем GlitchTip
    monkeypatch.setenv("AGENT_SYSTEM_PROMPT_PATH", str(DEFAULT_PROMPT))
    monkeypatch.setenv("MEMORY_DB_PATH", str(tmp_path / "memory.db"))
    monkeypatch.setenv("LOG_FILE", str(tmp_path / "agent.log"))

    build = AsyncMock()
    monkeypatch.setattr(max_main_module, "_build_components", build)

    await main()

    build.assert_not_awaited()


def _wire_main_mocks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    polling: AsyncMock,
) -> AsyncMock:
    """Замокать сборку/wiring/polling/shutdown, чтобы main() дошёл до
    shutdown-пути офлайн. Возвращает мок `_shutdown` для проверок."""
    monkeypatch.setenv(
        "TELEGRAM_BOT_TOKEN", "123456789:AAFakeTokenForSmokeTesting_0123"
    )
    monkeypatch.setenv("MAX_BOT_TOKEN", "max-fake-token")
    monkeypatch.setenv("SENTRY_DSN", "")  # офлайн: не дёргаем GlitchTip
    monkeypatch.setenv("AGENT_SYSTEM_PROMPT_PATH", str(DEFAULT_PROMPT))
    monkeypatch.setenv("MEMORY_DB_PATH", str(tmp_path / "memory.db"))
    monkeypatch.setenv("LOG_FILE", str(tmp_path / "agent.log"))

    components = MagicMock()
    components.dialog_journal = None  # без recovery_task
    monkeypatch.setattr(
        max_main_module, "_build_components", AsyncMock(return_value=components)
    )
    monkeypatch.setattr(
        max_main_module, "_wire_max", MagicMock(return_value=(AsyncMock(), AsyncMock()))
    )
    monkeypatch.setattr(max_main_module, "_run_polling", polling)
    shutdown = AsyncMock()
    monkeypatch.setattr(max_main_module, "_shutdown", shutdown)
    return shutdown


async def test_main_shuts_down_on_polling_completion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Штатное завершение polling → main() доходит до `_shutdown`."""
    shutdown = _wire_main_mocks(monkeypatch, tmp_path, polling=AsyncMock())

    await main()

    shutdown.assert_awaited_once()


async def test_main_shuts_down_when_polling_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Если polling упал — исключение пробрасывается, но `_shutdown` вызван."""
    shutdown = _wire_main_mocks(
        monkeypatch,
        tmp_path,
        polling=AsyncMock(side_effect=RuntimeError("polling crashed")),
    )

    with pytest.raises(RuntimeError, match="polling crashed"):
        await main()

    shutdown.assert_awaited_once()
