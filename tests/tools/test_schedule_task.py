"""Тесты tools: schedule_task, list_scheduled_tasks, cancel_scheduled_task.

Покрываем: валидный/невалидный cron, превышение лимита, список задач,
отмена своей/чужой задачи. SchedulerService/Store замоканы.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.services.scheduled_tasks import (
    ScheduledTask,
    ScheduledTaskStore,
    new_task_id,
)
from app.services.scheduler import SchedulerService
from app.tools.cancel_scheduled_task import CancelScheduledTaskTool
from app.tools.list_scheduled_tasks import ListScheduledTasksTool
from app.tools.schedule_task import ScheduleTaskTool


def _make_ctx(*, user_id: int = 42, chat_id: int = 42, scheduler=None):
    ctx = MagicMock()
    ctx.user_id = user_id
    ctx.chat_id = chat_id
    ctx.scheduler = scheduler
    ctx.settings.scheduler_max_jobs_per_user = 5
    return ctx


@pytest.fixture
async def store(tmp_path: Path) -> ScheduledTaskStore:
    s = ScheduledTaskStore(db_path=tmp_path / "test.db")
    await s.init()
    yield s
    await s.close()


@pytest.fixture
async def scheduler(store: ScheduledTaskStore) -> SchedulerService:
    return SchedulerService(store=store, timezone="UTC")


class TestScheduleTaskTool:
    async def test_valid_cron_creates_task(self, scheduler: SchedulerService) -> None:
        tool = ScheduleTaskTool()
        ctx = _make_ctx(scheduler=scheduler)

        result = await tool.run(
            {"prompt": "Напомни выпить кофе", "cron": "0 9 * * *"},
            ctx,
        )

        assert "Задача создана" in result
        assert "0 9 * * *" in result
        tasks = await scheduler.store.list_by_user(42)
        assert len(tasks) == 1
        assert tasks[0].prompt == "Напомни выпить кофе"
        assert tasks[0].cron == "0 9 * * *"
        assert tasks[0].channel == "telegram"

    async def test_invalid_cron_raises_tool_error(self, scheduler: SchedulerService) -> None:
        from app.tools.errors import ToolError

        tool = ScheduleTaskTool()
        ctx = _make_ctx(scheduler=scheduler)

        with pytest.raises(ToolError, match="Не удалось определить расписание"):
            await tool.run(
                {"prompt": "test", "cron": "invalid"},
                ctx,
            )

    async def test_empty_prompt_raises_tool_error(self, scheduler: SchedulerService) -> None:
        from app.tools.errors import ToolError

        tool = ScheduleTaskTool()
        ctx = _make_ctx(scheduler=scheduler)

        with pytest.raises(ToolError, match="prompt"):
            await tool.run(
                {"prompt": "", "cron": "0 9 * * *"},
                ctx,
            )

    async def test_exceed_limit_raises_tool_error(self, scheduler: SchedulerService) -> None:
        from app.tools.errors import ToolError

        tool = ScheduleTaskTool()
        ctx = _make_ctx(scheduler=scheduler)
        ctx.settings.scheduler_max_jobs_per_user = 1

        # Create first task
        await tool.run({"prompt": "first", "cron": "0 9 * * *"}, ctx)

        with pytest.raises(ToolError, match="лимит"):
            await tool.run({"prompt": "second", "cron": "0 10 * * *"}, ctx)

    async def test_scheduler_none_raises_tool_error(self) -> None:
        from app.tools.errors import ToolError

        tool = ScheduleTaskTool()
        ctx = _make_ctx(scheduler=None)

        with pytest.raises(ToolError, match="недоступен"):
            await tool.run({"prompt": "test", "cron": "0 9 * * *"}, ctx)

    async def test_custom_timezone(self, scheduler: SchedulerService) -> None:
        tool = ScheduleTaskTool()
        ctx = _make_ctx(scheduler=scheduler)

        result = await tool.run(
            {"prompt": "test", "cron": "0 9 * * *", "timezone": "UTC"},
            ctx,
        )

        assert "UTC" in result
        tasks = await scheduler.store.list_by_user(42)
        assert tasks[0].timezone == "UTC"

    async def test_schedule_text_parsed_to_cron(self, scheduler: SchedulerService) -> None:
        tool = ScheduleTaskTool()
        ctx = _make_ctx(scheduler=scheduler)

        result = await tool.run(
            {"prompt": "Проверь почту", "schedule_text": "каждую субботу в 15:08"},
            ctx,
        )

        assert "Задача создана" in result
        assert "8 15 * * 6" in result
        tasks = await scheduler.store.list_by_user(42)
        assert len(tasks) == 1
        assert tasks[0].cron == "8 15 * * 6"

    async def test_schedule_text_unrecognized_falls_back_to_cron(self, scheduler: SchedulerService) -> None:
        tool = ScheduleTaskTool()
        ctx = _make_ctx(scheduler=scheduler)

        result = await tool.run(
            {"prompt": "test", "schedule_text": "непонятный текст", "cron": "0 9 * * *"},
            ctx,
        )

        assert "Задача создана" in result
        assert "0 9 * * *" in result
        tasks = await scheduler.store.list_by_user(42)
        assert tasks[0].cron == "0 9 * * *"

    async def test_no_schedule_text_no_cron_raises_error(self, scheduler: SchedulerService) -> None:
        from app.tools.errors import ToolError

        tool = ScheduleTaskTool()
        ctx = _make_ctx(scheduler=scheduler)

        with pytest.raises(ToolError, match="Не удалось определить расписание"):
            await tool.run(
                {"prompt": "test"},
                ctx,
            )


class TestListScheduledTasksTool:
    async def test_empty_list(self, scheduler: SchedulerService) -> None:
        tool = ListScheduledTasksTool()
        ctx = _make_ctx(scheduler=scheduler)

        result = await tool.run({}, ctx)

        assert "нет запланированных задач" in result

    async def test_lists_user_tasks(self, scheduler: SchedulerService) -> None:
        tool = ListScheduledTasksTool()
        ctx = _make_ctx(scheduler=scheduler)

        task = ScheduledTask(
            id=new_task_id(),
            user_id=42,
            chat_id=42,
            channel="telegram",
            prompt="Напомни выпить кофе",
            cron="0 9 * * *",
            timezone="Europe/Moscow",
        )
        await scheduler.add_task(task)

        result = await tool.run({}, ctx)

        assert task.id in result
        assert "0 9 * * *" in result
        assert "Напомни выпить кофе" in result

    async def test_scheduler_none_raises_tool_error(self) -> None:
        from app.tools.errors import ToolError

        tool = ListScheduledTasksTool()
        ctx = _make_ctx(scheduler=None)

        with pytest.raises(ToolError, match="недоступен"):
            await tool.run({}, ctx)


class TestCancelScheduledTaskTool:
    async def test_cancel_own_task(self, scheduler: SchedulerService) -> None:
        tool = CancelScheduledTaskTool()
        ctx = _make_ctx(scheduler=scheduler)

        task = ScheduledTask(
            id=new_task_id(),
            user_id=42,
            chat_id=42,
            channel="telegram",
            prompt="test",
            cron="0 9 * * *",
            timezone="UTC",
        )
        await scheduler.add_task(task)

        result = await tool.run({"task_id": task.id}, ctx)

        assert "отменена" in result
        assert task.id in result
        tasks = await scheduler.store.list_by_user(42)
        assert len(tasks) == 0

    async def test_cancel_nonexistent_task(self, scheduler: SchedulerService) -> None:
        tool = CancelScheduledTaskTool()
        ctx = _make_ctx(scheduler=scheduler)

        result = await tool.run({"task_id": "nonexistent"}, ctx)

        assert "не найдена" in result

    async def test_cancel_other_users_task(self, scheduler: SchedulerService) -> None:
        tool = CancelScheduledTaskTool()
        ctx = _make_ctx(scheduler=scheduler)

        # Create task for user 99
        task = ScheduledTask(
            id=new_task_id(),
            user_id=99,
            chat_id=99,
            channel="telegram",
            prompt="other user task",
            cron="0 9 * * *",
            timezone="UTC",
        )
        await scheduler.add_task(task)

        # Try to cancel as user 42
        result = await tool.run({"task_id": task.id}, ctx)

        assert "не найдена" in result
        # Task should still exist for user 99
        tasks = await scheduler.store.list_by_user(99)
        assert len(tasks) == 1

    async def test_scheduler_none_raises_tool_error(self) -> None:
        from app.tools.errors import ToolError

        tool = CancelScheduledTaskTool()
        ctx = _make_ctx(scheduler=None)

        with pytest.raises(ToolError, match="недоступен"):
            await tool.run({"task_id": "abc"}, ctx)
