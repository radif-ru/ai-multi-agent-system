"""Тесты scheduler_runner — раннер запланированных задач.

Покрываем: успешный прогон вызывает notifier и mark_run(ok), ошибка
handle_user_task → mark_run(error) и человекочитаемый текст. Сеть не
дёргается — handle_user_task и notifier замоканы.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.scheduled_tasks import (
    ScheduledTask,
    ScheduledTaskStore,
    new_task_id,
)
from app.services.scheduler_runner import (
    GENERIC_ERROR_REPLY,
    LLM_TIMEOUT_REPLY,
    RunnerDeps,
    _cron_checkin,
    run_scheduled_task,
)


def _make_task(
    *,
    user_id: int = 42,
    chat_id: int = 42,
    prompt: str = "Напомни выпить кофе",
) -> ScheduledTask:
    return ScheduledTask(
        id=new_task_id(),
        user_id=user_id,
        chat_id=chat_id,
        channel="telegram",
        prompt=prompt,
        cron="0 10 * * *",
        timezone="Europe/Moscow",
    )


def _make_deps(store: ScheduledTaskStore) -> RunnerDeps:
    return RunnerDeps(
        conversations=MagicMock(),
        executor=MagicMock(),
        settings=MagicMock(),
        llm=MagicMock(),
        semantic_memory=None,
        planner=MagicMock(),
        critic=MagicMock(),
        user_settings=MagicMock(),
        store=store,
    )


@pytest.fixture
async def store(tmp_path: Path) -> ScheduledTaskStore:
    s = ScheduledTaskStore(db_path=tmp_path / "test.db")
    await s.init()
    yield s
    await s.close()


async def test_success_calls_notifier_and_mark_run_ok(
    store: ScheduledTaskStore,
) -> None:
    """Успешный прогон: notifier вызван, mark_run(ok)."""
    task = _make_task()
    await store.add(task)

    deps = _make_deps(store)
    notifier = AsyncMock()

    with patch(
        "app.services.scheduler_runner.handle_user_task",
        new=AsyncMock(return_value="Кофе готов!"),
    ):
        await run_scheduled_task(task, deps=deps, notifier=notifier)

    notifier.assert_awaited()
    updated = await store.get(task.id)
    assert updated is not None
    assert updated.last_status == "ok"


async def test_llm_timeout_marks_error_and_notifies(
    store: ScheduledTaskStore,
) -> None:
    """LLMTimeout → mark_run(error), notifier с человекочитаемым текстом."""
    task = _make_task()
    await store.add(task)

    deps = _make_deps(store)
    notifier = AsyncMock()

    from app.services.llm import LLMTimeout

    with patch(
        "app.services.scheduler_runner.handle_user_task",
        new=AsyncMock(side_effect=LLMTimeout("timeout")),
    ):
        await run_scheduled_task(task, deps=deps, notifier=notifier)

    notifier.assert_awaited()
    # Проверяем что в тексте есть человекочитаемое сообщение
    call_args = notifier.call_args
    delivered_text = call_args.args[1]
    assert LLM_TIMEOUT_REPLY in delivered_text

    updated = await store.get(task.id)
    assert updated is not None
    assert updated.last_status == "error"


async def test_generic_exception_marks_error_and_notifies(
    store: ScheduledTaskStore,
) -> None:
    """Произвольная ошибка → mark_run(error), notifier с generic-текстом."""
    task = _make_task()
    await store.add(task)

    deps = _make_deps(store)
    notifier = AsyncMock()

    with patch(
        "app.services.scheduler_runner.handle_user_task",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        await run_scheduled_task(task, deps=deps, notifier=notifier)

    notifier.assert_awaited()
    call_args = notifier.call_args
    delivered_text = call_args.args[1]
    assert GENERIC_ERROR_REPLY in delivered_text

    updated = await store.get(task.id)
    assert updated is not None
    assert updated.last_status == "error"


async def test_long_result_split_into_multiple_messages(
    store: ScheduledTaskStore,
) -> None:
    """Длинный результат разбивается на несколько сообщений через notifier."""
    task = _make_task()
    await store.add(task)

    deps = _make_deps(store)
    notifier = AsyncMock()

    long_text = "А" * 5000  # > 4096
    with patch(
        "app.services.scheduler_runner.handle_user_task",
        new=AsyncMock(return_value=long_text),
    ):
        await run_scheduled_task(task, deps=deps, notifier=notifier)

    # Должно быть как минимум 2 вызова notifier (разбивка)
    assert notifier.await_count >= 2


async def test_result_has_prefix(store: ScheduledTaskStore) -> None:
    """Результат доставляется с префиксом «⏰ Плановая задача»."""
    task = _make_task(prompt="Напомни выпить кофе")
    await store.add(task)

    deps = _make_deps(store)
    notifier = AsyncMock()

    with patch(
        "app.services.scheduler_runner.handle_user_task",
        new=AsyncMock(return_value="Готово"),
    ):
        await run_scheduled_task(task, deps=deps, notifier=notifier)

    call_args = notifier.call_args
    delivered_text = call_args.args[1]
    assert "⏰ Плановая задача" in delivered_text
    assert "Готово" in delivered_text


async def test_cron_checkin_in_progress_and_ok_on_success(
    store: ScheduledTaskStore,
) -> None:
    """Успешный прогон: capture_checkin вызван с in_progress и ok."""
    task = _make_task()
    await store.add(task)

    deps = _make_deps(store)
    notifier = AsyncMock()

    with (
        patch(
            "app.services.scheduler_runner.handle_user_task",
            new=AsyncMock(return_value="Готово"),
        ),
        patch("app.services.scheduler_runner.sentry_sdk") as mock_sentry,
    ):
        await run_scheduled_task(task, deps=deps, notifier=notifier)

    statuses = [
        call.kwargs.get("status") for call in mock_sentry.crons.capture_checkin.call_args_list
    ]
    assert "in_progress" in statuses
    assert "ok" in statuses


async def test_cron_checkin_error_on_llm_timeout(
    store: ScheduledTaskStore,
) -> None:
    """LLMTimeout: capture_checkin вызван с in_progress и error."""
    task = _make_task()
    await store.add(task)

    deps = _make_deps(store)
    notifier = AsyncMock()

    from app.services.llm import LLMTimeout

    with (
        patch(
            "app.services.scheduler_runner.handle_user_task",
            new=AsyncMock(side_effect=LLMTimeout("timeout")),
        ),
        patch("app.services.scheduler_runner.sentry_sdk") as mock_sentry,
    ):
        await run_scheduled_task(task, deps=deps, notifier=notifier)

    statuses = [
        call.kwargs.get("status") for call in mock_sentry.crons.capture_checkin.call_args_list
    ]
    assert "in_progress" in statuses
    assert "error" in statuses


async def test_cron_checkin_error_on_generic_exception(
    store: ScheduledTaskStore,
) -> None:
    """Generic exception: capture_checkin вызван с error."""
    task = _make_task()
    await store.add(task)

    deps = _make_deps(store)
    notifier = AsyncMock()

    with (
        patch(
            "app.services.scheduler_runner.handle_user_task",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
        patch("app.services.scheduler_runner.sentry_sdk") as mock_sentry,
    ):
        await run_scheduled_task(task, deps=deps, notifier=notifier)

    statuses = [
        call.kwargs.get("status") for call in mock_sentry.crons.capture_checkin.call_args_list
    ]
    assert "in_progress" in statuses
    assert "error" in statuses


def test_cron_checkin_does_not_raise_when_sentry_unavailable() -> None:
    """_cron_checkin не падает, если sentry_sdk не инициализирован."""
    with patch("app.services.scheduler_runner.sentry_sdk") as mock_sentry:
        mock_sentry.crons.capture_checkin.side_effect = Exception("no sentry")
        _cron_checkin("test-task-id", "ok", duration=1.5)
