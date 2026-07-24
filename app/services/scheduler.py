"""SchedulerService — обёртка над APScheduler для запланированных задач.

Использует ``AsyncIOScheduler`` с ``MemoryJobStore``: персистентность
обеспечивается ``ScheduledTaskStore`` (sqlite), а jobs пересоздаются из
таблицы при ``start()``. ``run_task`` — внедряемый раннер (задаётся в 2.3).

См. ``_docs/architecture.md`` §3.1 (сборка/lifecycle).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from functools import partial

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services.scheduled_tasks import ScheduledTask, ScheduledTaskStore

logger = logging.getLogger(__name__)

RunTaskFn = Callable[[ScheduledTask], Awaitable[None]]

# APScheduler использует 0=Monday, а standard cron — 0=Sunday.
# Конвертируем numeric DOW в имена дней, которые APScheduler интерпретирует
# одинаково независимо от конвенции.
_DOW_NAMES = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat']


def _convert_cron_dow_field(dow: str) -> str:
    """Конвертировать DOW-поле из standard cron (0=Sun) в APScheduler-совместимое."""
    if dow == '*' or dow.startswith('*/'):
        return dow
    if any(c.isalpha() for c in dow):
        return dow  # Уже имена дней

    def _to_name(s: str) -> str:
        n = int(s)
        if n == 7:
            n = 0  # 7 = Sunday в standard cron
        return _DOW_NAMES[n]

    if ',' in dow:
        return ','.join(_to_name(p) for p in dow.split(','))
    if '-' in dow:
        lo, hi = dow.split('-')
        return f'{_to_name(lo)}-{_to_name(hi)}'
    return _to_name(dow)


def _cron_to_trigger(cron: str, timezone: str) -> CronTrigger:
    """Создать CronTrigger из standard cron-выражения с корректным DOW."""
    parts = cron.split()
    if len(parts) == 5:
        parts[4] = _convert_cron_dow_field(parts[4])
        cron = ' '.join(parts)
    return CronTrigger.from_crontab(cron, timezone=timezone)


def validate_cron(expr: str) -> bool:
    """Проверить, что ``expr`` — валидное 5-польное cron-выражение."""
    try:
        _cron_to_trigger(expr, 'UTC')
        return True
    except (ValueError, IndexError):
        return False


class SchedulerService:
    """Управление запланированными задачами поверх APScheduler.

    Конструктор принимает ``store``, ``timezone``, ``run_task`` и
    опц. ``scheduler`` для тестов (DI фейка).
    """

    def __init__(
        self,
        *,
        store: ScheduledTaskStore,
        timezone: str,
        run_task: RunTaskFn | None = None,
        scheduler: AsyncIOScheduler | None = None,
    ) -> None:
        self._store = store
        self._run_task = run_task
        self._scheduler: AsyncIOScheduler = scheduler or AsyncIOScheduler(
            timezone=timezone,
            job_defaults={"misfire_grace_time": 3600, "coalesce": True},
        )

    @property
    def store(self) -> ScheduledTaskStore:
        """Доступ к хранилищу задач (для tools)."""
        return self._store

    def set_run_task(self, run_task: RunTaskFn) -> None:
        """Внедрить раннер (вызывается из 2.3 после сборки компонентов)."""
        self._run_task = run_task

    async def start(self) -> None:
        """Стартовать scheduler и пересоздать jobs из store."""
        if not self._scheduler.running:
            self._scheduler.start()
        await self._rehydrate()
        logger.info("SchedulerService запущен, jobs: %d", len(self._scheduler.get_jobs()))

    async def shutdown(self) -> None:
        """Остановить scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        logger.info("SchedulerService остановлен")

    async def add_task(self, task: ScheduledTask) -> None:
        """Сохранить задачу в store и зарегистрировать job."""
        await self._store.add(task)
        self._add_job(task)

    async def remove_task(self, task_id: str, *, user_id: int) -> bool:
        """Удалить задачу из store и scheduler. Вернуть был ли удалён."""
        deleted = await self._store.delete(task_id, user_id=user_id)
        if deleted:
            try:
                self._scheduler.remove_job(task_id)
            except Exception:  # noqa: BLE001
                pass  # JobLookupError — job уже не существует
        return deleted

    def _add_job(self, task: ScheduledTask) -> None:
        """Зарегистрировать job в scheduler для задачи."""
        if not task.enabled:
            return
        trigger = _cron_to_trigger(task.cron, timezone=task.timezone)
        runner = partial(self._job_entrypoint, task_id=task.id)
        self._scheduler.add_job(
            runner,
            trigger=trigger,
            id=task.id,
            replace_existing=True,
            misfire_grace_time=3600,
            coalesce=True,
        )

    async def _rehydrate(self) -> None:
        """Пересоздать jobs из ``store.list_enabled()``."""
        tasks = await self._store.list_enabled()
        for task in tasks:
            try:
                self._add_job(task)
            except Exception:  # noqa: BLE001
                logger.exception("не удалось зарегистрировать job для задачи %s", task.id)

    async def _job_entrypoint(self, task_id: str) -> None:
        """Точка входа job: достать задачу из store и вызвать раннер.

        Модульная (не метод экземпляра в args) — замыкание над ``self``
        через ``functools.partial``, pickle не требуется (MemoryJobStore).
        """
        task = await self._store.get(task_id)
        if task is None or not task.enabled:
            return
        if self._run_task is None:
            logger.warning("run_task не задан, задача %s пропущена", task_id)
            return
        await self._run_task(task)
