"""Персистентное хранилище определений запланированных задач.

Таблица ``scheduled_tasks`` в ``data/memory.db`` (отдельное соединение,
как ``DialogJournal``). Доступ к соединению сериализован ``threading.Lock``
(см. ``_docs/current-state.md`` §2.3 про гонку sqlite). Каждый метод —
через ``asyncio.to_thread``.

См. ``_docs/memory.md`` §4 для образца стиля sqlite-сервиса.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_ALLOWED_CHANNELS = ("telegram", "console", "max")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ScheduledTask:
    """Определение запланированной задачи (строка таблицы)."""

    id: str
    user_id: int
    chat_id: int
    channel: str
    prompt: str
    cron: str
    timezone: str
    enabled: bool = True
    created_at: str = ""
    last_run_at: str | None = None
    last_status: str | None = None

    def __post_init__(self) -> None:
        if self.channel not in _ALLOWED_CHANNELS:
            raise ValueError(
                f"channel must be one of {_ALLOWED_CHANNELS}, got '{self.channel}'"
            )
        if not self.prompt.strip():
            raise ValueError("prompt must not be empty")
        if not self.cron.strip():
            raise ValueError("cron must not be empty")

    @classmethod
    def from_row(cls, row: sqlite3.Row | tuple) -> "ScheduledTask":
        """Создать объект из строки БД."""
        if isinstance(row, sqlite3.Row):
            d = dict(row)
        else:
            cols = (
                "id", "user_id", "chat_id", "channel", "prompt", "cron",
                "timezone", "enabled", "created_at", "last_run_at", "last_status",
            )
            d = dict(zip(cols, row))
        return cls(
            id=d["id"],
            user_id=d["user_id"],
            chat_id=d["chat_id"],
            channel=d["channel"],
            prompt=d["prompt"],
            cron=d["cron"],
            timezone=d["timezone"],
            enabled=bool(d["enabled"]),
            created_at=d["created_at"],
            last_run_at=d["last_run_at"],
            last_status=d["last_status"],
        )


class ScheduledTaskStore:
    """Слой над ``sqlite3`` для таблицы ``scheduled_tasks``.

    API асинхронный; синхронная суть через ``asyncio.to_thread``.
    Доступ к соединению сериализован ``threading.Lock``.
    """

    def __init__(self, *, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    # -- lifecycle --------------------------------------------------------

    async def init(self) -> None:
        await asyncio.to_thread(self._init_sync)

    def _init_sync(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id           TEXT    PRIMARY KEY,
                user_id      INTEGER NOT NULL,
                chat_id      INTEGER NOT NULL,
                channel      TEXT    NOT NULL,
                prompt       TEXT    NOT NULL,
                cron         TEXT    NOT NULL,
                timezone     TEXT    NOT NULL,
                enabled      INTEGER NOT NULL DEFAULT 1,
                created_at   TEXT    NOT NULL,
                last_run_at  TEXT,
                last_status  TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_sched_user
                ON scheduled_tasks(user_id);
            """
        )
        conn.commit()
        self._conn = conn

    async def close(self) -> None:
        await asyncio.to_thread(self._close_sync)

    def _close_sync(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # -- CRUD -------------------------------------------------------------

    async def add(self, task: ScheduledTask) -> None:
        await asyncio.to_thread(self._add_sync, task)

    def _add_sync(self, task: ScheduledTask) -> None:
        assert self._conn is not None
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO scheduled_tasks
                    (id, user_id, chat_id, channel, prompt, cron,
                     timezone, enabled, created_at, last_run_at, last_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.user_id,
                    task.chat_id,
                    task.channel,
                    task.prompt,
                    task.cron,
                    task.timezone,
                    int(task.enabled),
                    task.created_at or _now_iso(),
                    task.last_run_at,
                    task.last_status,
                ),
            )
            self._conn.commit()

    async def get(self, task_id: str) -> ScheduledTask | None:
        return await asyncio.to_thread(self._get_sync, task_id)

    def _get_sync(self, task_id: str) -> ScheduledTask | None:
        assert self._conn is not None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM scheduled_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        return ScheduledTask.from_row(row) if row else None

    async def list_by_user(self, user_id: int) -> list[ScheduledTask]:
        return await asyncio.to_thread(self._list_by_user_sync, user_id)

    def _list_by_user_sync(self, user_id: int) -> list[ScheduledTask]:
        assert self._conn is not None
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM scheduled_tasks WHERE user_id = ? ORDER BY created_at",
                (user_id,),
            ).fetchall()
        return [ScheduledTask.from_row(r) for r in rows]

    async def list_enabled(self) -> list[ScheduledTask]:
        return await asyncio.to_thread(self._list_enabled_sync)

    def _list_enabled_sync(self) -> list[ScheduledTask]:
        assert self._conn is not None
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM scheduled_tasks WHERE enabled = 1 ORDER BY created_at"
            ).fetchall()
        return [ScheduledTask.from_row(r) for r in rows]

    async def count_by_user(self, user_id: int) -> int:
        return await asyncio.to_thread(self._count_by_user_sync, user_id)

    def _count_by_user_sync(self, user_id: int) -> int:
        assert self._conn is not None
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM scheduled_tasks WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return row[0]

    async def mark_run(
        self, task_id: str, *, status: str, when: str
    ) -> None:
        await asyncio.to_thread(self._mark_run_sync, task_id, status, when)

    def _mark_run_sync(self, task_id: str, status: str, when: str) -> None:
        assert self._conn is not None
        with self._lock:
            self._conn.execute(
                """
                UPDATE scheduled_tasks
                SET last_run_at = ?, last_status = ?
                WHERE id = ?
                """,
                (when, status, task_id),
            )
            self._conn.commit()

    async def delete(self, task_id: str, *, user_id: int) -> bool:
        return await asyncio.to_thread(self._delete_sync, task_id, user_id)

    def _delete_sync(self, task_id: str, user_id: int) -> bool:
        assert self._conn is not None
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM scheduled_tasks WHERE id = ? AND user_id = ?",
                (task_id, user_id),
            )
            self._conn.commit()
        return cur.rowcount > 0


def new_task_id() -> str:
    """Сгенерировать новый ID задачи (uuid4 hex)."""
    return uuid.uuid4().hex
