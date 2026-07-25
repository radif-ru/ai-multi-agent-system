"""Тесты команд /schedule и /schedules через CommandRegistry.

Команды проходят через реальный `CommandRegistry`; scheduler — `AsyncMock`.
См. спринт 15, задача 4.1.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.commands.context import CommandContext
from app.commands.registry import CommandRegistry


def _ctx(scheduler=None) -> CommandContext:
    return CommandContext(
        user_id=42,
        chat_id=100,
        settings=SimpleNamespace(
            scheduler_max_jobs_per_user=10,
            agent_reflection_mode="OFF",
            search_engines_available=["duckduckgo"],
            search_engine_default="duckduckgo",
        ),
        user_settings=MagicMock(),
        prompts=MagicMock(),
        tools=MagicMock(),
        skills=MagicMock(),
        conversations=MagicMock(),
        archiver=MagicMock(),
        users=None,
        channel="telegram",
        scheduler=scheduler,
    )


def _mock_scheduler(tasks=None) -> SimpleNamespace:
    store = AsyncMock()
    store.count_by_user = AsyncMock(return_value=0)
    store.list_by_user = AsyncMock(return_value=tasks or [])
    return SimpleNamespace(
        store=store,
        add_task=AsyncMock(),
    )


# --- /schedule -------------------------------------------------------------


async def test_schedule_no_scheduler() -> None:
    registry = CommandRegistry()
    result = await registry.execute("schedule", _ctx(), args="")
    assert "недоступен" in result.text.lower()


async def test_schedule_no_args() -> None:
    scheduler = _mock_scheduler()
    registry = CommandRegistry()
    result = await registry.execute("schedule", _ctx(scheduler), args="")
    assert "Использование" in result.text


async def test_schedule_too_few_parts() -> None:
    scheduler = _mock_scheduler()
    registry = CommandRegistry()
    result = await registry.execute("schedule", _ctx(scheduler), args="0 9 * * *")
    assert "5 полей" in result.text


async def test_schedule_invalid_cron() -> None:
    scheduler = _mock_scheduler()
    registry = CommandRegistry()
    result = await registry.execute(
        "schedule", _ctx(scheduler), args="99 99 * * * test"
    )
    assert "Невалидное" in result.text


async def test_schedule_success() -> None:
    scheduler = _mock_scheduler()
    registry = CommandRegistry()
    result = await registry.execute(
        "schedule", _ctx(scheduler), args="0 9 * * * Проверь почту"
    )
    assert "Задача создана" in result.text
    assert "ID:" in result.text
    scheduler.add_task.assert_awaited_once()


async def test_schedule_limit_reached() -> None:
    scheduler = _mock_scheduler()
    scheduler.store.count_by_user = AsyncMock(return_value=10)
    registry = CommandRegistry()
    result = await registry.execute(
        "schedule", _ctx(scheduler), args="0 9 * * * test"
    )
    assert "лимит" in result.text.lower()
    scheduler.add_task.assert_not_awaited()


# --- /schedules ------------------------------------------------------------


async def test_schedules_no_scheduler() -> None:
    registry = CommandRegistry()
    result = await registry.execute("schedules", _ctx())
    assert "недоступен" in result.text.lower()


async def test_schedules_empty() -> None:
    scheduler = _mock_scheduler(tasks=[])
    registry = CommandRegistry()
    result = await registry.execute("schedules", _ctx(scheduler))
    assert "нет запланированных" in result.text.lower()


async def test_schedules_lists_tasks() -> None:
    task = SimpleNamespace(
        id="abc123",
        prompt="Проверь почту",
        cron="0 9 * * *",
        timezone="Europe/Moscow",
        enabled=True,
        last_run_at=None,
        last_status=None,
    )
    scheduler = _mock_scheduler(tasks=[task])
    registry = CommandRegistry()
    result = await registry.execute("schedules", _ctx(scheduler))
    assert "abc123" in result.text
    assert "Проверь почту" in result.text
    assert "включена" in result.text
