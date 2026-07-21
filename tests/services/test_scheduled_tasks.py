"""Тесты ScheduledTaskStore — хранилище запланированных задач в sqlite.

Покрываем: add/get/list_by_user/list_enabled/count_by_user/mark_run/delete,
идемпотентность init, валидацию ScheduledTask, delete чужой задачи.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.scheduled_tasks import (
    ScheduledTask,
    ScheduledTaskStore,
    new_task_id,
)


def _make_task(
    *,
    user_id: int = 42,
    chat_id: int = 42,
    prompt: str = "Напомни выпить кофе",
    cron: str = "0 10 * * *",
    timezone: str = "Europe/Moscow",
    channel: str = "telegram",
    enabled: bool = True,
) -> ScheduledTask:
    return ScheduledTask(
        id=new_task_id(),
        user_id=user_id,
        chat_id=chat_id,
        channel=channel,
        prompt=prompt,
        cron=cron,
        timezone=timezone,
        enabled=enabled,
    )


@pytest.fixture
async def store(tmp_path: Path) -> ScheduledTaskStore:
    s = ScheduledTaskStore(db_path=tmp_path / "test.db")
    await s.init()
    yield s
    await s.close()


async def test_init_is_idempotent(tmp_path: Path) -> None:
    """Повторный init не падает и не дублирует схему."""
    s = ScheduledTaskStore(db_path=tmp_path / "test.db")
    await s.init()
    await s.init()
    await s.close()


async def test_add_and_get(store: ScheduledTaskStore) -> None:
    """Добавленная задача доступна через get."""
    task = _make_task()
    await store.add(task)
    got = await store.get(task.id)
    assert got is not None
    assert got.id == task.id
    assert got.user_id == task.user_id
    assert got.prompt == task.prompt
    assert got.cron == task.cron
    assert got.enabled is True


async def test_get_nonexistent(store: ScheduledTaskStore) -> None:
    """get несуществующего ID возвращает None."""
    assert await store.get("nonexistent") is None


async def test_list_by_user(store: ScheduledTaskStore) -> None:
    """list_by_user возвращает задачи пользователя по created_at."""
    t1 = _make_task(user_id=42, prompt="задача 1")
    t2 = _make_task(user_id=42, prompt="задача 2")
    t3 = _make_task(user_id=99, prompt="чужая задача")
    await store.add(t1)
    await store.add(t2)
    await store.add(t3)

    tasks = await store.list_by_user(42)
    assert len(tasks) == 2
    assert all(t.user_id == 42 for t in tasks)
    # Порядок по created_at
    assert tasks[0].created_at <= tasks[1].created_at

    other = await store.list_by_user(99)
    assert len(other) == 1


async def test_list_enabled(store: ScheduledTaskStore) -> None:
    """list_enabled возвращает только enabled=1."""
    t1 = _make_task(prompt="enabled")
    t2 = _make_task(prompt="disabled", enabled=False)
    await store.add(t1)
    await store.add(t2)

    enabled = await store.list_enabled()
    assert len(enabled) == 1
    assert enabled[0].id == t1.id


async def test_count_by_user(store: ScheduledTaskStore) -> None:
    """count_by_user считает задачи пользователя."""
    await store.add(_make_task(user_id=42))
    await store.add(_make_task(user_id=42))
    await store.add(_make_task(user_id=99))

    assert await store.count_by_user(42) == 2
    assert await store.count_by_user(99) == 1
    assert await store.count_by_user(0) == 0


async def test_mark_run(store: ScheduledTaskStore) -> None:
    """mark_run обновляет last_run_at и last_status."""
    task = _make_task()
    await store.add(task)

    await store.mark_run(task.id, status="ok", when="2026-07-20T10:00:00+00:00")
    got = await store.get(task.id)
    assert got is not None
    assert got.last_run_at == "2026-07-20T10:00:00+00:00"
    assert got.last_status == "ok"


async def test_delete_own_task(store: ScheduledTaskStore) -> None:
    """delete удаляет свою задачу и возвращает True."""
    task = _make_task(user_id=42)
    await store.add(task)
    assert await store.delete(task.id, user_id=42) is True
    assert await store.get(task.id) is None


async def test_delete_foreign_task(store: ScheduledTaskStore) -> None:
    """delete чужой задачи не удаляет и возвращает False."""
    task = _make_task(user_id=42)
    await store.add(task)
    assert await store.delete(task.id, user_id=99) is False
    assert await store.get(task.id) is not None


def test_scheduled_task_validates_channel() -> None:
    """ScheduledTask отклоняет невалидный channel."""
    with pytest.raises(ValueError, match="channel"):
        ScheduledTask(
            id="test",
            user_id=1,
            chat_id=1,
            channel="email",
            prompt="test",
            cron="0 10 * * *",
            timezone="UTC",
        )


def test_scheduled_task_validates_empty_prompt() -> None:
    """ScheduledTask отклоняет пустой prompt."""
    with pytest.raises(ValueError, match="prompt"):
        ScheduledTask(
            id="test",
            user_id=1,
            chat_id=1,
            channel="telegram",
            prompt="  ",
            cron="0 10 * * *",
            timezone="UTC",
        )


def test_scheduled_task_validates_empty_cron() -> None:
    """ScheduledTask отклоняет пустой cron."""
    with pytest.raises(ValueError, match="cron"):
        ScheduledTask(
            id="test",
            user_id=1,
            chat_id=1,
            channel="telegram",
            prompt="test",
            cron="",
            timezone="UTC",
        )
