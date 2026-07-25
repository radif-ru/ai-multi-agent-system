"""Тесты SchedulerService — обёртка APScheduler.

Покрываем: add_task регистрирует job, remove_task удаляет из store и
scheduler, невалидный cron отклоняется, rehydrate добавляет enabled-задачи.
Сеть/реальное время не используются — инспекция get_jobs().
"""

from __future__ import annotations

from pathlib import Path

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.services.scheduled_tasks import (
    ScheduledTask,
    ScheduledTaskStore,
    new_task_id,
)
from app.services.scheduler import (
    SchedulerService,
    _convert_cron_dow_field,
    _cron_to_trigger,
    validate_cron,
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


@pytest.fixture
def scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler(timezone="UTC")


@pytest.fixture
async def service(
    store: ScheduledTaskStore, scheduler: AsyncIOScheduler
) -> SchedulerService:
    svc = SchedulerService(
        store=store,
        timezone="UTC",
        run_task=None,
        scheduler=scheduler,
    )
    scheduler.start()
    yield svc
    if scheduler.running:
        scheduler.shutdown(wait=False)


async def test_add_task_registers_job(
    store: ScheduledTaskStore, scheduler: AsyncIOScheduler
) -> None:
    """add_task сохраняет в store и регистрирует job в scheduler."""
    svc = SchedulerService(
        store=store, timezone="UTC", scheduler=scheduler
    )
    scheduler.start()
    try:
        task = _make_task()
        await svc.add_task(task)

        # job зарегистрирован
        jobs = scheduler.get_jobs()
        assert len(jobs) == 1
        assert jobs[0].id == task.id

        # задача в store
        got = await store.get(task.id)
        assert got is not None
    finally:
        scheduler.shutdown(wait=False)


async def test_remove_task_deletes_from_store_and_scheduler(
    store: ScheduledTaskStore, scheduler: AsyncIOScheduler
) -> None:
    """remove_task удаляет из store и scheduler."""
    svc = SchedulerService(
        store=store, timezone="UTC", scheduler=scheduler
    )
    scheduler.start()
    try:
        task = _make_task()
        await svc.add_task(task)
        assert len(scheduler.get_jobs()) == 1

        deleted = await svc.remove_task(task.id, user_id=42)
        assert deleted is True
        assert len(scheduler.get_jobs()) == 0
        assert await store.get(task.id) is None
    finally:
        scheduler.shutdown(wait=False)


async def test_remove_task_foreign_user(
    store: ScheduledTaskStore, scheduler: AsyncIOScheduler
) -> None:
    """remove_task чужого пользователя возвращает False."""
    svc = SchedulerService(
        store=store, timezone="UTC", scheduler=scheduler
    )
    scheduler.start()
    try:
        task = _make_task(user_id=42)
        await svc.add_task(task)

        deleted = await svc.remove_task(task.id, user_id=99)
        assert deleted is False
        assert len(scheduler.get_jobs()) == 1
    finally:
        scheduler.shutdown(wait=False)


async def test_rehydrate_adds_enabled_tasks(
    store: ScheduledTaskStore, scheduler: AsyncIOScheduler
) -> None:
    """start() пересоздаёт enabled-задачи из store."""
    # Добавляем задачи в store напрямую
    t1 = _make_task(prompt="enabled task", cron="0 10 * * *")
    t2 = _make_task(prompt="disabled task", cron="0 11 * * *", enabled=False)
    await store.add(t1)
    await store.add(t2)

    svc = SchedulerService(
        store=store, timezone="UTC", scheduler=scheduler
    )
    await svc.start()
    try:
        jobs = scheduler.get_jobs()
        assert len(jobs) == 1
        assert jobs[0].id == t1.id
    finally:
        await svc.shutdown()


async def test_rehydrate_skips_disabled(
    store: ScheduledTaskStore, scheduler: AsyncIOScheduler
) -> None:
    """disabled-задачи не регистрируются как jobs."""
    task = _make_task(enabled=False)
    await store.add(task)

    svc = SchedulerService(
        store=store, timezone="UTC", scheduler=scheduler
    )
    await svc.start()
    try:
        assert len(scheduler.get_jobs()) == 0
    finally:
        await svc.shutdown()


def test_validate_cron_valid() -> None:
    """validate_cron принимает валидные cron-выражения."""
    assert validate_cron("0 10 * * *") is True
    assert validate_cron("*/5 * * * *") is True
    assert validate_cron("0 0 1 1 0") is True


def test_validate_cron_invalid() -> None:
    """validate_cron отклоняет невалидные cron-выражения."""
    assert validate_cron("") is False
    assert validate_cron("not a cron") is False
    assert validate_cron("0 10") is False
    assert validate_cron("100 10 * * *") is False


async def test_disabled_task_not_added_as_job(
    store: ScheduledTaskStore, scheduler: AsyncIOScheduler
) -> None:
    """add_task с enabled=False сохраняет в store, но не регистрирует job."""
    svc = SchedulerService(
        store=store, timezone="UTC", scheduler=scheduler
    )
    scheduler.start()
    try:
        task = _make_task(enabled=False)
        await svc.add_task(task)
        assert len(scheduler.get_jobs()) == 0
        assert await store.get(task.id) is not None
    finally:
        scheduler.shutdown(wait=False)


# --- DOW конвертация (standard cron 0=Sun → APScheduler 0=Mon) ---


def test_dow_convert_single_friday() -> None:
    """5 (Friday в standard cron) → 'fri'."""
    assert _convert_cron_dow_field("5") == "fri"


def test_dow_convert_sunday_zero() -> None:
    """0 (Sunday в standard cron) → 'sun'."""
    assert _convert_cron_dow_field("0") == "sun"


def test_dow_convert_sunday_seven() -> None:
    """7 (Sunday в standard cron) → 'sun'."""
    assert _convert_cron_dow_field("7") == "sun"


def test_dow_convert_range() -> None:
    """1-5 (Mon-Fri) → 'mon-fri'."""
    assert _convert_cron_dow_field("1-5") == "mon-fri"


def test_dow_convert_list() -> None:
    """1,3,5 → 'mon,wed,fri'."""
    assert _convert_cron_dow_field("1,3,5") == "mon,wed,fri"


def test_dow_convert_star() -> None:
    """* → '*' (без изменений)."""
    assert _convert_cron_dow_field("*") == "*"


def test_dow_convert_named_days_passthrough() -> None:
    """Имена дней проходят без изменений."""
    assert _convert_cron_dow_field("mon-fri") == "mon-fri"
    assert _convert_cron_dow_field("fri") == "fri"


def test_cron_to_trigger_friday_correct() -> None:
    """46 13 * * 5 → следующий запуск в пятницу, не субботу."""
    from datetime import datetime

    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Moscow")
    except ImportError:
        import pytz
        tz = pytz.timezone("Europe/Moscow")

    now = datetime(2026, 7, 24, 13, 45, tzinfo=tz)  # Friday 13:45
    trigger = _cron_to_trigger("46 13 * * 5", "Europe/Moscow")
    next_fire = trigger.get_next_fire_time(None, now)
    assert next_fire.strftime("%A") == "Friday"
    assert next_fire.hour == 13
    assert next_fire.minute == 46
