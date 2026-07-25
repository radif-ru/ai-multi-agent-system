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


async def test_log_start_and_ok_on_success(
    store: ScheduledTaskStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Успешный прогон: логируется запуск и выполнение с dur_ms."""
    task = _make_task()
    await store.add(task)

    deps = _make_deps(store)
    notifier = AsyncMock()

    with patch(
        "app.services.scheduler_runner.handle_user_task",
        new=AsyncMock(return_value="Готово"),
    ):
        with caplog.at_level("INFO", logger="app.services.scheduler_runner"):
            await run_scheduled_task(task, deps=deps, notifier=notifier)

    messages = [r.message for r in caplog.records]
    assert any("scheduler: запуск" in m for m in messages)
    assert any("scheduler: выполнено" in m and "dur_ms=" in m for m in messages)


async def test_log_error_on_llm_timeout(
    store: ScheduledTaskStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """LLMTimeout: логируется ошибка с dur_ms."""
    task = _make_task()
    await store.add(task)

    deps = _make_deps(store)
    notifier = AsyncMock()

    from app.services.llm import LLMTimeout

    with patch(
        "app.services.scheduler_runner.handle_user_task",
        new=AsyncMock(side_effect=LLMTimeout("timeout")),
    ):
        with caplog.at_level("WARNING", logger="app.services.scheduler_runner"):
            await run_scheduled_task(task, deps=deps, notifier=notifier)

    messages = [r.message for r in caplog.records]
    assert any("scheduler: ошибка" in m and "dur_ms=" in m for m in messages)


async def test_log_error_on_generic_exception(
    store: ScheduledTaskStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Generic exception: логируется ошибка с dur_ms."""
    task = _make_task()
    await store.add(task)

    deps = _make_deps(store)
    notifier = AsyncMock()

    with patch(
        "app.services.scheduler_runner.handle_user_task",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        with caplog.at_level("ERROR", logger="app.services.scheduler_runner"):
            await run_scheduled_task(task, deps=deps, notifier=notifier)

    messages = [r.message for r in caplog.records]
    assert any("scheduler: ошибка" in m and "dur_ms=" in m for m in messages)


async def test_scheduled_task_uses_empty_history(
    store: ScheduledTaskStore,
) -> None:
    """run_scheduled_task передаёт history=[] в handle_user_task для изоляции
    от живой сессии пользователя (не читает историю текущего диалога)."""
    task = _make_task()
    await store.add(task)

    deps = _make_deps(store)
    notifier = AsyncMock()

    with patch(
        "app.services.scheduler_runner.handle_user_task",
        new=AsyncMock(return_value="Готово"),
    ) as mock_handle:
        await run_scheduled_task(task, deps=deps, notifier=notifier)

    _, kwargs = mock_handle.call_args
    assert kwargs.get("history") == []


async def test_scheduled_task_prompt_has_execution_context(
    store: ScheduledTaskStore,
) -> None:
    """Промпт cron-задачи обёрнут контекстом «выполни сейчас», чтобы LLM
    не создал новую задачу вместо выполнения."""
    task = _make_task(prompt="Проверяй почту каждый день в 16:29")
    await store.add(task)

    deps = _make_deps(store)
    notifier = AsyncMock()

    with patch(
        "app.services.scheduler_runner.handle_user_task",
        new=AsyncMock(return_value="Готово"),
    ) as mock_handle:
        await run_scheduled_task(task, deps=deps, notifier=notifier)

    args, _ = mock_handle.call_args
    goal = args[0]
    assert "выполни" in goal.lower()
    assert "не создавай" in goal.lower()
    assert "Проверяй почту" in goal
