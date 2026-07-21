# Спринт 14. Планировщик задач, логи в GlitchTip и качество RAG

- **Источник:** ТЗ пользователя (планировщик cron-задач из Telegram, логи INFO+ в GlitchTip, аудит векторной памяти) + `_docs/decisions.md` ADR-2 (cron = APScheduler в процессе) + `_docs/current-state.md` §1.2/§1.7.
- **Ветка:** `feature/14-scheduler-logs-rag` (от `main`; см. `_board/process.md` §2, п.2).
- **Открыт:** 2026-07-10
- **Закрыт:** 2026-07-21

## 1. Цель спринта

Дать пользователю **повторяющиеся (cron) задачи прямо из Telegram на естественном языке**: «проверяй почту каждый день в 9 утра» → агент ставит расписание, задача переживает рестарт процесса, результат приходит в Telegram. Планировщик — **APScheduler внутри процесса бота** (ADR-2: n8n/Celery отклонены как избыточные для single-user local-first; брокеры/второе хранилище не вводим).

Параллельно закрываем два запроса по наблюдаемости и памяти: (1) отправлять **логи уровня INFO и выше в уже существующий GlitchTip** (а `DEBUG` — никогда), расширив текущую Sentry-интеграцию без ELK и новых сервисов; (2) провести **аудит долгосрочной памяти на `sqlite-vec`** (чанки, эмбеддинги, метрика близости), зафиксировать решение по архитектуре БД (остаётся `sqlite-vec`, ADR-3) и внедрить безопасные улучшения качества RAG.

## 2. Скоуп и non-goals

### В скоупе

- **GlitchTip-логи:** настраиваемый порог событий Sentry/GlitchTip (`SENTRY_EVENT_LEVEL`), чтобы `INFO+` уезжали как события, `DEBUG` — нет. Только `app/observability/`, `app/config.py`, `.env.example`, доки, тесты.
- **Планировщик:** зависимость `APScheduler`; сервис-обёртка `SchedulerService`; персистентная таблица `scheduled_tasks` в `data/memory.db`; исполнение задания через `core.handle_user_task`; доставка результата в **Telegram**; tools для агента (`schedule_task` / `list_scheduled_tasks` / `cancel_scheduled_task`); скилл-инструкция `scheduler`.
- **RAG-аудит:** spike с ADR по `sqlite-vec` (метрика, префиксы `nomic`, чанкинг, TTL) + внедрение безопасных улучшений (task-префиксы `search_document:` / `search_query:`).
- **Документация:** новый `_docs/scheduler.md`; актуализация `current-state.md`, `architecture.md`, `observability.md`, `memory.md`, `roadmap.md`, `decisions.md`, `stack.md` §9, `commands.md`/`tools.md`; презентабельность корневого `README.md`; зелёные CI-гейты.

### Вне скоупа (non-goals)

- **Celery / Redis / RabbitMQ / ELK / Logstash / Filebeat** — не вводим (ADR-2, local-first).
- **Смена векторной БД** на Qdrant/Chroma/pgvector — не делаем (ADR-3). Только улучшения поверх `sqlite-vec`.
- **Доставка результатов планировщика в console и MAX** — MVP только Telegram; console/MAX → `roadmap.md`.
- **Пересоздание/миграция существующей `memory.db`** (например, смена метрики на cosine, требующая DROP `memory_vec`) — если spike решит, что нужно, задача уходит в `roadmap.md`, а не в этот спринт.
- **Bot-команды `/schedule` / `/schedules`** (вместо/в дополнение к tools) — MVP делает natural-language через tools; команды → `roadmap.md`.
- **Webhook-режим, throttling** — не трогаем.

## 3. Acceptance Criteria спринта

- [x] При заданном `SENTRY_DSN` логи уровня `SENTRY_LOG_LEVEL` (default `INFO`) и выше доходят в GlitchTip во вкладку **Logs**; ошибки уровня `SENTRY_EVENT_LEVEL` (default `ERROR`) и выше — в **Issues**; `DEBUG` можно включить через `SENTRY_LOG_LEVEL=DEBUG`; при пустом `SENTRY_DSN` поведение прежнее (ничего не инициализируется).
- [x] Пользователь из Telegram естественным языком («проверяй почту каждый день в 9:00») ставит повторяющуюся задачу; она сохраняется в `data/memory.db`, **переживает рестарт** процесса и запускается по расписанию; результат приходит сообщением в Telegram.
- [x] Пользователь может посмотреть свои задачи и отменить любую (через агента/tools).
- [x] RAG-пайплайн `sqlite-vec` задокументирован и аудитирован (spike), решение по архитектуре БД и метрике зафиксировано в `_docs/decisions.md`; внедрены безопасные улучшения качества (task-префиксы `nomic`).
- [x] Документация актуализирована, `README.md` презентабелен; все CI-гейты зелёные: `flake8`, `pytest -q` c `--cov-fail-under=80`, `check_env_sync`, `check_sprint_sync`, `check_doc_links`, `check_agents_sync`.
- [x] Все задачи спринта — `Done`, сводная таблица актуальна.

---

## 4. Этап 1. Логи в GlitchTip (настраиваемый уровень событий и Logs API)

Цель: отправлять в существующий GlitchTip логи с уровня `INFO` (настраивается), не заводя ELK. Малый изолированный этап — делаем первым. Задача 1.2 добавлена по факту: INFO-логи попадали в Issues (шум), нужно разделить — ошибки в Issues, информационные логи в Logs.

### Задача 1.1. Настраиваемый порог событий Sentry/GlitchTip

- **Статус:** Done
- **Приоритет:** high
- **Объём:** S
- **Зависит от:** —
- **Связанные документы:** `_docs/observability.md` §5; `_docs/current-state.md` §1.7; `_docs/stack.md` §9.
- **Затрагиваемые файлы:** `app/config.py`, `app/observability/__init__.py`, `.env.example`, `tests/observability/test_error_capture.py` (или новый `tests/observability/test_event_level.py`), `_docs/observability.md`.

#### Описание

Сейчас `setup_sentry` жёстко задаёт `LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)` (`app/observability/__init__.py:77`): в GlitchTip **событиями** уезжают только `ERROR+`, а `INFO`/`WARNING` — лишь breadcrumbs. Пользователю нужно, чтобы **логи уровня INFO и выше тоже попадали в GlitchTip как события**, а `DEBUG` — никогда.

Важно (зафиксировать в доке, не менять поведение по-умолчанию агрессивно): GlitchTip — трекер ошибок, а не лог-хранилище; каждое уникальное сообщение уровня события становится «issue». Поэтому порог делаем **настраиваемым** (`SENTRY_EVENT_LEVEL`), дефолт по запросу пользователя — `INFO`, и в доке рекомендуем `WARNING` тем, кто не хочет «шумных» issue.

Шаги:

1. В `app/config.py` добавить поле в секцию `--- Observability ...`:
   `sentry_event_level: str = "INFO"` с комментарием (какие логи уезжают событием в GlitchTip; `DEBUG` не отправляется никогда).
2. Добавить `@field_validator("sentry_event_level", mode="before")`, который `.strip().upper()` и валидирует значение по множеству `{"DEBUG","INFO","WARNING","ERROR","CRITICAL"}` (иначе `ValueError`). Нормализованное значение хранить строкой в верхнем регистре.
3. В `app/observability/__init__.py::setup_sentry` заменить хардкод `event_level=logging.ERROR` на `event_level=logging.getLevelName(settings.sentry_event_level)` (получает int по имени уровня). `level` (breadcrumbs) оставить `logging.INFO`, чтобы `DEBUG` не шёл даже в breadcrumbs.
4. В `.env.example` в секции `# --- Observability / error tracking (GlitchTip / Sentry) ---` добавить закомментированную/активную запись `SENTRY_EVENT_LEVEL=INFO` с описанием и рекомендацией `WARNING` для снижения шума.
5. Обновить `_docs/observability.md` §5 (подсекция «Интеграции»): описать `SENTRY_EVENT_LEVEL`, дефолт `INFO`, что `DEBUG` не отправляется, и оговорку про «issue-флуд» + рекомендацию `WARNING`. Обновить `_docs/current-state.md` §1.7 (одна строка про настраиваемый порог).
6. Тест: юнит на то, что при `SENTRY_EVENT_LEVEL=INFO` в `sentry_sdk.init` уезжает `LoggingIntegration` с `event_level == logging.INFO` (пропатчить/замокать `sentry_sdk.init`, проверить переданный integration), и что `DEBUG` не создаёт событие (в стиле `tests/observability/test_error_capture.py` с in-memory transport — сгенерировать `logger.info(...)` → событие есть; `logger.debug(...)` → события нет).

#### Definition of Done

- [x] `SENTRY_EVENT_LEVEL` есть в `Settings` (с валидатором) и в `.env.example`; `check_env_sync` зелёный.
- [x] `setup_sentry` использует `SENTRY_EVENT_LEVEL` для `event_level`; при `INFO` INFO-логи уезжают событием, `DEBUG` — нет; при пустом `SENTRY_DSN` ничего не инициализируется (поведение не изменилось).
- [x] Документация обновлена (`observability.md` §5, `current-state.md` §1.7, `stack.md` §9 если там перечислены env).
- [x] Тесты добавлены; `pytest -q` зелёный, порог покрытия не нарушен.
- [x] `git status` чист, артефакты не закоммичены.

### Задача 1.2. Логи в GlitchTip Logs (не Issues)

- **Статус:** Done
- **Приоритет:** high
- **Объём:** S
- **Зависит от:** 1.1
- **Связанные документы:** `_docs/observability.md` §5; `_docs/current-state.md` §1.7.
- **Затрагиваемые файлы:** `app/observability/__init__.py`, `app/config.py`, `.env.example`, `tests/observability/test_event_level.py`, `_docs/observability.md`.

#### Описание

Задача 1.1 настроила `LoggingIntegration` с `event_level=INFO` — все INFO+ логи уезжают в GlitchTip как **события (Issues)**. GlitchTip поддерживает Sentry Logs API: при `enable_logs=True` в `sentry_sdk.init()` логи направляются во вкладку **Logs**, а не в Issues.

Внедрить разделение (Вариант 2 из обсуждения с пользователем) + настраиваемый уровень логов:

1. В `sentry_sdk.init()` добавить `enable_logs=True` и `auto_session_tracking=False` (GlitchTip не поддерживает sessions).
2. `LoggingIntegration` использует `event_level` из `SENTRY_EVENT_LEVEL` (дефолт `ERROR` — ошибки и исключения → Issues). `level` (breadcrumbs + Logs) берётся из новой настройки `SENTRY_LOG_LEVEL` (дефолт `INFO`).
3. `SENTRY_EVENT_LEVEL` (дефолт `ERROR`) контролирует только порог **событий (Issues)**. `SENTRY_LOG_LEVEL` (дефолт `INFO`) контролирует порог **логов в Logs и breadcrumbs**. `DEBUG` можно включить через `SENTRY_LOG_LEVEL=DEBUG`.
4. Добавить `sentry_enable_logs: bool = True` в `Settings` (возможность отключить логи в Logs при необходимости).
5. Добавить `sentry_log_level: str = "INFO"` в `Settings` с валидатором (аналог `sentry_event_level`).
6. В `.env.example` обновить комментарии и добавить `SENTRY_ENABLE_LOGS=true`, `SENTRY_LOG_LEVEL=INFO`.
7. Обновить `_docs/observability.md` §5: описать разделение Logs vs Issues, три параметра.
8. Тесты: `enable_logs=True`, `auto_session_tracking=False`; `LoggingIntegration` имеет `event_level=ERROR` (дефолт) и `level=INFO` (дефолт); `SENTRY_LOG_LEVEL=DEBUG` меняет `level`; `SENTRY_EVENT_LEVEL=WARNING` меняет `event_level`.

#### Definition of Done

- [x] `sentry_sdk.init()` вызывается с `enable_logs=True`, `auto_session_tracking=False`.
- [x] `LoggingIntegration` использует `event_level` из `SENTRY_EVENT_LEVEL` (дефолт `ERROR`) и `level` из `SENTRY_LOG_LEVEL` (дефолт `INFO`); INFO-логи идут в Logs, ERROR+ — в Issues; `SENTRY_LOG_LEVEL=DEBUG` включает DEBUG в Logs.
- [x] `SENTRY_ENABLE_LOGS` и `SENTRY_LOG_LEVEL` в `Settings` и `.env.example`; `check_env_sync` зелёный.
- [x] `_docs/observability.md` §5 обновлён (разделение Logs vs Issues, три параметра).
- [x] Тесты добавлены/обновлены; `pytest -q` зелёный, порог покрытия не нарушен.
- [x] `git status` чист.

### Задача 1.3. Performance-трассировки и Crons в GlitchTip

- **Статус:** Done
- **Приоритет:** medium
- **Объём:** S
- **Зависит от:** 1.1
- **Связанные документы:** `_docs/observability.md` §5; `_docs/scheduler.md`.
- **Затрагиваемые файлы:** `app/observability/__init__.py`, `app/services/scheduler_runner.py`, `app/config.py`, `.env.example`, `tests/observability/test_event_level.py`, `tests/services/test_scheduler_runner.py`, `_docs/observability.md`.

#### Описание

GlitchTip имеет вкладки **Performance** (трассировки запросов) и **Crons** (мониторинг cron-задач). Сейчас `SENTRY_TRACES_SAMPLE_RATE=0.0` — трассировки выключены. Crons не используются.

Внедрить:

1. **Performance**: поднять дефолт `SENTRY_TRACES_SAMPLE_RATE` с `0.0` до `0.1` (10% запросов — баланс между видимостью и нагрузкой). Настройка уже есть в `Settings` и `.env.example` — обновить дефолт и комментарий.
2. **Crons**: использовать `sentry_sdk.crons.capture_check_in()` в `run_scheduled_task` для отправки heartbeat в GlitchTip при запуске/успехе/ошибке cron-задачи. Monitor ID — `task_id` (или его хэш). Это позволит видеть пропуски и задержки в вкладке Crons.
3. В `.env.example` обновить комментарий к `SENTRY_TRACES_SAMPLE_RATE` (теперь дефолт `0.1`).
4. Обновить `_docs/observability.md` §5: описать Performance и Crons.
5. Тесты: проверить что `sentry_sdk.crons.capture_check_in` вызывается при запуске/успехе/ошибке задачи (мок `sentry_sdk.crons`); проверить что `SENTRY_TRACES_SAMPLE_RATE` передаётся в `sentry_sdk.init`.

#### Definition of Done

- [x] `SENTRY_TRACES_SAMPLE_RATE` дефолт `0.1` в `Settings` и `.env.example`; `check_env_sync` зелёный.
- [x] `sentry_sdk.crons.capture_checkin` вызывается в `run_scheduled_task` (in_progress, ok/error).
- [x] `_docs/observability.md` §5 обновлён (Performance, Crons).
- [x] Тесты добавлены; `pytest -q` зелёный, порог покрытия не нарушен.
- [x] `git status` чист.

---

## 5. Этап 2. Планировщик задач (APScheduler)

Цель: повторяющиеся задачи из Telegram на естественном языке. Планировщик — `AsyncIOScheduler` (APScheduler 3.x) в процессе бота; расписания персистятся в собственной таблице `data/memory.db` и восстанавливаются при старте; исполнение задания = `core.handle_user_task(...)`; доставка результата — в Telegram.

**Архитектурная рамка этапа (обязательна к соблюдению):**

- Один экземпляр `SchedulerService` на процесс, живёт в `_Components`, стартует/останавливается в lifecycle точки входа (`app/main.py`).
- Персистентность — **своя таблица** `scheduled_tasks` в `data/memory.db` (отдельное соединение, как `DialogJournal`), **не** SQLAlchemyJobStore (не тянем SQLAlchemy; «единственная БД — sqlite», см. architecture-discipline). В APScheduler — `MemoryJobStore`; при старте задания **пересоздаются** из таблицы.
- Job регистрируется с `args=[task_id]` и ссылкой на top-level корутину-раннер → никакого pickle сложных объектов.
- Исполнение задания **не публикует** `MessageReceived`/`ResponseGenerated` и не пишет в `ConversationStore` (чтобы не засорять живую сессию пользователя). Внутри задания биндится свежий `trace_id`/`user_id` (`app/utils/tracing.py`).
- Безопасность: текст задачи — пользовательский ввод → при создании прогоняется `sanitize_user_input`; на выходе работает существующий `ResponseSanitizer` (Executor). Лимит числа задач на пользователя (`SCHEDULER_MAX_JOBS_PER_USER`).

### Задача 2.1. Хранилище расписаний `ScheduledTaskStore` (sqlite)

- **Статус:** Done
- **Приоритет:** high
- **Объём:** M
- **Зависит от:** —
- **Связанные документы:** `_docs/memory.md` §4 (пример стиля sqlite-сервиса `DialogJournal`); `_docs/scheduler.md` (создаётся в 2.6).
- **Затрагиваемые файлы:** `app/services/scheduled_tasks.py` (новый), `tests/services/test_scheduled_tasks.py` (новый).

#### Описание

Персистентное хранилище определений задач в `data/memory.db` (`Settings.memory_db_path`), по образцу `app/services/dialog_journal.py` (отдельное `sqlite3.Connection` с `check_same_thread=False`, доступ сериализован `threading.Lock`, каждый метод — через `asyncio.to_thread`; см. `_docs/current-state.md` §2.3 про гонку sqlite).

Схема таблицы:

```sql
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id           TEXT    PRIMARY KEY,   -- uuid4 hex, он же job_id в APScheduler
    user_id      INTEGER NOT NULL,
    chat_id      INTEGER NOT NULL,
    channel      TEXT    NOT NULL,       -- "telegram" (MVP)
    prompt       TEXT    NOT NULL,       -- что попросить агента при срабатывании
    cron         TEXT    NOT NULL,       -- 5-польное cron-выражение (min hour dom mon dow)
    timezone     TEXT    NOT NULL,       -- IANA tz, напр. "Europe/Moscow"
    enabled      INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT    NOT NULL,       -- ISO 8601
    last_run_at  TEXT,                    -- ISO 8601 | NULL
    last_status  TEXT                     -- "ok" | "error" | NULL
);
CREATE INDEX IF NOT EXISTS ix_sched_user ON scheduled_tasks(user_id);
```

API (async, синхронная суть через `asyncio.to_thread`, доступ под `threading.Lock`):

- `init()` — создать таблицу/индекс (идемпотентно).
- `add(task: ScheduledTask) -> None` — вставка.
- `get(task_id) -> ScheduledTask | None`.
- `list_by_user(user_id) -> list[ScheduledTask]` — по `created_at`.
- `list_enabled() -> list[ScheduledTask]` — все `enabled=1` (для восстановления при старте).
- `count_by_user(user_id) -> int` — для лимита.
- `mark_run(task_id, *, status: str, when: str)` — обновить `last_run_at`/`last_status`.
- `delete(task_id, *, user_id: int) -> bool` — удалить только свою задачу (фильтр по `user_id`), вернуть был ли удалён.
- `close()`.

`ScheduledTask` — `@dataclass` (frozen) с полями схемы. Валидировать `channel` и непустой `prompt`/`cron` на уровне конструктора dataclass или store.

#### Definition of Done

- [x] Модуль `app/services/scheduled_tasks.py` с `ScheduledTask` и `ScheduledTaskStore` реализован; доступ к соединению сериализован `Lock` (регресс sqlite-гонки, ср. §2.3 current-state).
- [x] Тесты `tests/services/test_scheduled_tasks.py` на `tmp_path`-БД: add/get/list_by_user/list_enabled/count/mark_run/delete (в т.ч. `delete` чужой задачи не удаляет), идемпотентность `init`.
- [x] Документация — записи для 2.1 попадут в `_docs/scheduler.md` (задача 2.6); здесь достаточно docstring'ов.
- [x] `pytest -q` зелёный, покрытие не нарушено; `git status` чист.

### Задача 2.2. `SchedulerService` (обёртка APScheduler) + lifecycle

- **Статус:** Done
- **Приоритет:** high
- **Объём:** M
- **Зависит от:** Задача 2.1
- **Связанные документы:** `_docs/architecture.md` §3.1 (сборка/lifecycle); `_docs/scheduler.md`.
- **Затрагиваемые файлы:** `requirements.txt`, `app/config.py`, `.env.example`, `app/services/scheduler.py` (новый), `app/main.py`, `tests/services/test_scheduler.py` (новый), `tests/test_main.py` (если нужно поправить smoke).

#### Описание

Добавить зависимость `APScheduler>=3.10,<4` в `requirements.txt` (pure-Python, без брокеров — соответствует ADR-2).

Конфиг (`app/config.py`, секция `--- Scheduler ---`) + записи в `.env.example`:

- `scheduler_enabled: bool = True` — выключатель планировщика.
- `scheduler_timezone: str = "Europe/Moscow"` — IANA-таймзона по умолчанию для cron.
- `scheduler_max_jobs_per_user: int = 20` — лимит задач на пользователя (валидатор `> 0`).

`app/services/scheduler.py::SchedulerService`:

- Конструктор принимает `store: ScheduledTaskStore`, `timezone: str`, `run_task: Callable[[ScheduledTask], Awaitable[None]]` (раннер задаётся в 2.3), опц. `scheduler` для тестов (DI фейка).
- Внутри — `apscheduler.schedulers.asyncio.AsyncIOScheduler` с `MemoryJobStore` и `timezone`.
- `async def start()` — стартует scheduler, затем `await self._rehydrate()`: читает `store.list_enabled()` и на каждую задачу вызывает `_add_job`.
- `async def shutdown()` — `scheduler.shutdown(wait=False)` через `asyncio.to_thread` при необходимости.
- `async def add_task(task)` — `store.add(task)` + `_add_job(task)`.
- `async def remove_task(task_id, *, user_id)` — `store.delete(...)`; при успехе `scheduler.remove_job(task_id)` (тихо игнорировать `JobLookupError`).
- `_add_job(task)` — `trigger = CronTrigger.from_crontab(task.cron, timezone=task.timezone)`; `scheduler.add_job(_job_entrypoint, trigger=trigger, id=task.id, args=[task.id], replace_existing=True, misfire_grace_time=3600, coalesce=True)`.
- top-level корутина `_job_entrypoint(task_id)` (модульная, не метод — чтобы не тянуть self в job args): достаёт активный `SchedulerService` из модульного реестра/синглтона (или через `functools.partial`, привязанный при `_add_job`; допускается `args=[task_id]` + замыкание `run_task`), затем: `task = await store.get(task_id)`; если `None`/`disabled` — выход; иначе `await run_task(task)`.
  - Реализовать так, чтобы job не требовал pickle (MemoryJobStore это позволяет): можно `scheduler.add_job(partial_runner, ...)` где `partial_runner` — замыкание над `self.run_task` и `self._store`.

Валидация cron: метод/утилита `validate_cron(expr) -> bool` (через попытку `CronTrigger.from_crontab`), используется в tool 2.4.

Lifecycle (`app/main.py`):

1. В `_build_components` создать `ScheduledTaskStore(db_path=settings.memory_db_path)`, `await store.init()`; создать `SchedulerService(...)`; положить оба в `_Components` (новые поля). Раннер (`run_task`) внедряется в 2.3 — на этом шаге допускается временная заглушка/None, но лучше сразу подготовить точку внедрения.
2. В `main()` после `_wire_telegram` и до/рядом с recovery: если `settings.scheduler_enabled` — `await components.scheduler.start()`.
3. В `_shutdown_components` (или в `finally` `main`) — `await components.scheduler.shutdown()`.
4. Учесть, что `tests/test_main.py` патчит `_start_polling`; убедиться, что старт scheduler не ломает smoke (в тесте scheduler можно не стартовать или мокать).

#### Definition of Done

- [x] `APScheduler` в `requirements.txt`; `SchedulerService` создаётся/стартует/останавливается в lifecycle `app/main.py`; при `SCHEDULER_ENABLED=false` не стартует.
- [x] Новые поля `Settings` (`scheduler_enabled`, `scheduler_timezone`, `scheduler_max_jobs_per_user`) есть в `.env.example`; `check_env_sync` зелёный.
- [x] Задачи восстанавливаются из `store.list_enabled()` при `start()` (тест на rehydrate с фейковым/реальным `AsyncIOScheduler` и мгновенным триггером или проверкой `get_jobs()`).
- [x] Тесты `tests/services/test_scheduler.py`: add_task регистрирует job; remove_task удаляет из store и scheduler; невалидный cron отклоняется; rehydrate добавляет enabled-задачи. Сеть/реальное время не используются (либо `DateTrigger`/immediate, либо инспекция `get_jobs()`).
- [x] `pytest -q` зелёный, покрытие не нарушено; `git status` чист.

### Задача 2.3. Исполнение задания и доставка результата в Telegram

- **Статус:** Done
- **Приоритет:** high
- **Объём:** M
- **Зависит от:** Задача 2.2
- **Связанные документы:** `_docs/observability.md` §2 (`trace_id`); `_docs/architecture.md` §3.10 (контракт `handle_user_task`); `_docs/security.md`.
- **Затрагиваемые файлы:** `app/services/scheduler_runner.py` (новый) или функция в `app/services/scheduler.py`; `app/main.py` (`_wire_telegram`), `app/adapters/telegram/` (утилита отправки), `tests/services/test_scheduler_runner.py` (новый).

#### Описание

Раннер задания `run_scheduled_task(task, *, deps, notifier)`:

1. Забиндить `trace_id = bind_trace_id(new_trace_id())` и `user_id = bind_user_id(task.user_id)`; всё в `try/finally` со сбросом (см. `app/utils/tracing.py` и `_docs/observability.md` §2 — сейчас фоновые задачи логируются без trace_id; здесь делаем правильно).
2. Прогнать `prompt` через `sanitize_user_input(task.prompt, user_id=task.user_id, mode="warn")` (двойная защита; основная — при создании в 2.4).
3. Вызвать `orchestrator.handle_user_task(sanitized, user_id=task.user_id, chat_id=task.chat_id, conversations=..., executor=..., settings=..., llm=..., semantic_memory=..., planner=..., critic=..., user_settings=..., model=user_settings.get_model(task.user_id))` — те же зависимости, что в `build_messages_router` (`app/adapters/telegram/handlers/messages.py`). **Не публиковать** события шины (изоляция от живой сессии).
4. Ошибки LLM-слоя (`LLMError` и наследники) и прочее — ловим, формируем человекочитаемый текст (как в messages-хендлере), пишем `store.mark_run(status="error")`, лог `scheduler.run status=error`.
5. При успехе — `store.mark_run(status="ok")`, лог `scheduler.run status=ok dur_ms=...`.
6. Доставка: вызвать `notifier(channel=task.channel, chat_id=task.chat_id, text=<result>)`. Для MVP реализован только `telegram`-notifier.

Notifier для Telegram (`_wire_telegram` в `app/main.py`): замыкание/функция, которая `await bot.send_message(chat_id, html.escape(text), ...)` с разбиением длинного текста через существующий `split_long_message` (как в messages-хендлере). Внедряется в `SchedulerService.run_task`/раннер после создания `bot`. Для `channel != "telegram"` — лог `scheduler.deliver skipped channel=...` (console/MAX вне scope).

Формат сообщения пользователю — префикс, что это плановая задача, например: `⏰ Плановая задача «<краткий prompt>»:\n\n<result>`.

#### Definition of Done

- [x] Раннер вызывает `handle_user_task` с теми же зависимостями, что Telegram-хендлер; события шины не публикуются; `trace_id`/`user_id` биндятся и сбрасываются.
- [x] Результат доставляется в Telegram (`bot.send_message`, `split_long_message`, `html.escape`); длинный ответ не роняет доставку.
- [x] Ошибки задания не валят scheduler/процесс; `mark_run` фиксирует статус.
- [x] Тесты `tests/services/test_scheduler_runner.py`: успешный прогон вызывает notifier и `mark_run(ok)`; исключение `handle_user_task` → `mark_run(error)` и человекочитаемый текст (notifier с фейком); `handle_user_task` замокан, сеть не дёргается.
- [x] `pytest -q` зелёный, покрытие не нарушено; `git status` чист.

### Задача 2.4. Tools для агента: `schedule_task` / `list_scheduled_tasks` / `cancel_scheduled_task`

- **Статус:** Done
- **Приоритет:** high
- **Объём:** M
- **Зависит от:** Задача 2.3
- **Связанные документы:** `_docs/tools.md` §2–§3 (контракт tool); `app/tools/weather.py` (образец); `_docs/scheduler.md`.
- **Затрагиваемые файлы:** `app/tools/schedule_task.py`, `app/tools/list_scheduled_tasks.py`, `app/tools/cancel_scheduled_task.py` (новые), `app/main.py` (регистрация в `ToolRegistry`), `app/tools/base.py`/`ToolContext` (при необходимости прокинуть `scheduler`), `tests/tools/test_schedule_task.py` и др. (новые), `_docs/tools.md`.

#### Описание

Три tool'а по контракту `app/tools/base.py::Tool` (`name`, `description`, `args_schema`, `async run(args, ctx) -> str`), регистрируются в `ToolRegistry` в `_build_components`. Планировщик прокидывается в tools через `ToolContext` (добавить атрибут `scheduler` в протокол `ToolContext` и в реальную сборку контекста Executor'а; проверить, где `ToolContext` конструируется — `app/agents/executor.py`).

- **`schedule_task`** — args: `{ "prompt": str, "cron": str, "timezone": str? }`. Поведение: валидировать cron (`SchedulerService.validate_cron`); проверить лимит `count_by_user < scheduler_max_jobs_per_user` (иначе `ToolError` с человекочитаемым текстом); `sanitize_user_input(prompt)`; создать `ScheduledTask` (uuid4 hex id, `channel=ctx` канал — прокинуть текущий канал в контекст или брать `"telegram"` для MVP; `chat_id`/`user_id` из `ctx`); `await scheduler.add_task(task)`; вернуть подтверждение с человекочитаемым описанием расписания и id. Описание tool должно объяснить модели, что `cron` — 5-польное выражение и что «каждый день в 9 утра» = `0 9 * * *` (детально — в скилле 2.5).
- **`list_scheduled_tasks`** — args: `{}`. Возвращает JSON/текст задач текущего пользователя (`store.list_by_user(ctx.user_id)`): id, prompt, cron, timezone, enabled, last_run_at/last_status.
- **`cancel_scheduled_task`** — args: `{ "task_id": str }`. `await scheduler.remove_task(task_id, user_id=ctx.user_id)`; если не найдено/не своё — понятный ответ.

Все ошибки сервиса → `ToolError` с человекочитаемым текстом (единообразно во всех каналах). Планировщик — потенциально «опасный» tool? Нет: он не трогает ФС/сеть напрямую, работает только со своими задачами пользователя (scope по `user_id`). В `_DANGEROUS_TOOLS` **не** добавляем.

#### Definition of Done

- [x] Три tool'а реализованы и зарегистрированы; `ToolContext` даёт доступ к `scheduler` и `user_id`/`chat_id`/каналу.
- [x] `schedule_task` валидирует cron, соблюдает лимит на пользователя, санитизирует prompt; `list`/`cancel` работают в scope пользователя (нельзя отменить чужую задачу).
- [x] Тесты на каждый tool (валидный/невалидный cron, превышение лимита, отмена своей/чужой задачи) с фейковым `SchedulerService`/`store`.
- [x] `_docs/tools.md` дополнен тремя tool'ами (§4.16–4.18, задача 4.1); `pytest -q` зелёный, покрытие не нарушено; `git status` чист.

### Задача 2.5. Скилл `scheduler` (инструкция агенту + маппинг времени в cron)

- **Статус:** Done
- **Приоритет:** medium
- **Объём:** S
- **Зависит от:** Задача 2.4
- **Связанные документы:** `_docs/skills.md` (формат `SKILL.md`); `app/skills/email-assistant/SKILL.md` (образец).
- **Затрагиваемые файлы:** `app/skills/scheduler/SKILL.md` (новый).

#### Описание

Создать скилл по формату `_docs/skills.md` (первая строка `Description:` или YAML frontmatter — как в существующих скиллах; сверить `check_agents_sync`/`SkillRegistry` требования). Содержание:

- Когда использовать: пользователь просит делать что-то регулярно/по расписанию.
- Как перевести естественный язык в 5-польный cron (`min hour dom mon dow`): примеры «каждый день в 9 утра» → `0 9 * * *`; «по будням в 18:30» → `30 18 * * 1-5`; «каждый час» → `0 * * * *`; «1-го числа в 10:00» → `0 10 1 * *`.
- Таймзона: по умолчанию из настроек сервера (`Europe/Moscow`), пользователь может указать другую.
- Порядок действий агента: сформировать `prompt` (что именно делать при срабатывании, напр. «Проверь непрочитанную почту через email_list и сделай краткий дайджест») → вызвать `schedule_task` с `cron` + `prompt` → подтвердить пользователю. Для просмотра/отмены — `list_scheduled_tasks` / `cancel_scheduled_task`.
- Безопасность: не планировать опасные действия; prompt задачи будет исполнен от имени пользователя.

#### Definition of Done

- [x] `app/skills/scheduler/SKILL.md` создан в правильном формате (описание подхватывается `SkillRegistry`, инжектится в системный промпт).
- [x] `check_agents_sync` (и загрузка `SkillRegistry`) зелёные; smoke `python -c "from app.services.skills import SkillRegistry; r=SkillRegistry('app/skills'); r.load(); print('scheduler' in [d['name'] for d in r.list_descriptions()])"` → `True`.
- [x] Тесты — `n/a` (чисто-скилловая задача, только `app/skills/`).
- [x] `git status` чист.

### Задача 2.6. Документ `_docs/scheduler.md` + ссылки

- **Статус:** Done
- **Приоритет:** medium
- **Объём:** S
- **Зависит от:** Задачи 2.1–2.5
- **Связанные документы:** `_docs/README.md` (индекс), `_docs/architecture.md`, `_docs/decisions.md` (ADR-2).
- **Затрагиваемые файлы:** `_docs/scheduler.md` (новый), `_docs/README.md`, `_docs/architecture.md`.

#### Описание

Написать `_docs/scheduler.md`: назначение, архитектура (APScheduler `AsyncIOScheduler` + собственная таблица `scheduled_tasks`, `MemoryJobStore`, rehydrate при старте), поток исполнения задания (`handle_user_task` → notifier → Telegram), изоляция от живой сессии, безопасность (sanitize, лимит, scope по user_id), конфиг (`SCHEDULER_*`), tools и скилл, ограничения MVP (только Telegram-доставка; console/MAX → roadmap; cron-only, без «естественного» парсера времени в коде — маппинг делает LLM по скиллу). Явно сослаться на ADR-2 (почему APScheduler, а не Celery/n8n).

Добавить `_docs/scheduler.md` в индекс `_docs/README.md` (раздел «Как устроено») и краткую ссылку-упоминание в `_docs/architecture.md` (точки расширения / компоненты). Проверить относительные ссылки (`check_doc_links`).

#### Definition of Done

- [x] `_docs/scheduler.md` создан, добавлен в `_docs/README.md` и упомянут в `architecture.md`.
- [x] `check_doc_links` зелёный (только относительные, не битые ссылки).
- [x] Тесты — `n/a` (docs). `git status` чист.

### Задача 2.7. Фиксы cron-исполнения по итогам ручного тестирования

- **Статус:** Done
- **Приоритет:** high
- **Объём:** S
- **Зависит от:** Задача 2.3 (баг обнаружен при ручной проверке исполнения задания)
- **Связанные документы:** `_docs/scheduler.md`; `_docs/agent-loop.md` §4; `_docs/architecture.md` §3.10.
- **Затрагиваемые файлы:** `app/core/orchestrator.py`, `app/services/scheduler_runner.py`, `app/config.py`, `.env.example`, `_docs/agent-loop.md`, `_docs/requirements.md`, `_docs/stack.md`, `tests/services/test_scheduler_runner.py`, `tests/test_config.py`.

#### Описание

Оформление постфактум (см. `_board/process.md` §3 п.4 «Работа вне формальной задачи») двух фиксов, сделанных при ручном тестировании планировщика в Telegram. Симптом: cron-задача при срабатывании не выполнялась, а `qwen3.5:4b` вместо исполнения prompt повторял диалог о её создании и повторно вызывал `schedule_task` с неверным cron.

Первопричины и фиксы:

1. **Живая история протекала в cron-задание** (commit `cbe02c07`). `handle_user_task` читал историю из `ConversationStore`, поэтому модель видела предыдущий диалог «поставь задачу» и повторяла его. Фикс: в `handle_user_task` добавлен параметр `history: list[dict[str,str]] | None = None`; `run_scheduled_task` передаёт `history=[]` — полная изоляция от живой сессии.
2. **Нет явного контекста исполнения + мало шагов** (commit `0cacd7ce`). Prompt задачи обёрнут явной инструкцией «это автоматическое выполнение запланированной задачи, выполни сейчас, не создавай новую задачу». `AGENT_MAX_STEPS` поднят с 15 до 30 (cron-prompt требует больше шагов: подгрузка скилла → tool → ответ). Обновлены `agent-loop.md` §4, `requirements.md` FR-13, `stack.md` §9, `.env.example`.

#### Definition of Done

- [x] `handle_user_task` принимает `history`; `run_scheduled_task` передаёт `history=[]` (изоляция).
- [x] Prompt cron-задачи обёрнут контекстом исполнения; `AGENT_MAX_STEPS` дефолт `30` в `Settings`, `.env.example` и доках (`agent-loop.md`, `requirements.md`, `stack.md`) синхронно.
- [x] Тесты в `tests/services/test_scheduler_runner.py` (изоляция истории, контекст исполнения) и `tests/test_config.py` обновлены; `pytest -q` зелёный, покрытие не нарушено.
- [x] `git status` чист (фиксы уже в ветке: `cbe02c07`, `0cacd7ce`).

---

## 6. Этап 3. Качество долгосрочной памяти (RAG на `sqlite-vec`)

Цель: разобраться, как реально работают чанки/эмбеддинги/поиск, зафиксировать решение по архитектуре БД (остаётся `sqlite-vec`), внедрить безопасные улучшения качества.

### Задача 3.1. Spike: аудит RAG-пайплайна + ADR

- **Статус:** Done
- **Приоритет:** high
- **Объём:** M
- **Зависит от:** —
- **Связанные документы:** `_docs/memory.md` §3; `_docs/decisions.md` (ADR-3); `app/services/memory.py`, `app/services/archiver.py`, `app/services/llm.py::embed`, `app/tools/memory_search.py`, `app/services/session_bootstrap.py`.
- **Затрагиваемые файлы (spike):** `_docs/decisions.md` (новый ADR), `_docs/roadmap.md`, `_docs/memory.md` (уточнения по итогам).

#### Описание (spike — результат-документ, не код)

Задокументировать и проверить фактический пайплайн: `Summarizer` → `chunk_text(size=1500, overlap=150)` → `nomic-embed-text` (768d) → `SemanticMemory.insert_batch` (`memory_chunks` + `memory_vec vec0`) → KNN `MATCH` c пост-фильтром по `user_id`.

Разобрать и зафиксировать выводы по пунктам:

1. **Чанкинг применяется к саммари, а не к сырой сессии** → обычно выходит 1 чанк (саммари короткое). Оценить, нужен ли чанкинг вообще при текущей длине саммари; зафиксировать вывод.
2. **`nomic-embed-text` без task-префиксов** (`search_document:` / `search_query:`) → просадка качества. Проверить документацию модели/эмпирику; рекомендация — внедрить префиксы (реализация — задача 3.2).
3. **Метрика близости `vec0`**: определить дефолт `sqlite-vec` (L2 vs cosine) и нужна ли `distance_metric=cosine` / нормализация векторов для `nomic`. **Важно:** смена метрики требует пересоздания `memory_vec` (DROP/миграция) → если рекомендуется, задача уходит в `roadmap.md`, а не в текущий спринт.
4. **TTL/cleanup**: индекс `ix_memory_created` есть, но очистки нет. Зафиксировать: нужен ли TTL, куда (roadmap).
5. **Архитектура БД**: подтвердить решение «остаёмся на `sqlite-vec`» (ADR-3, local-first) — со ссылкой; смена на Qdrant/Chroma/pgvector отклонена.

Проверка (smoke, допустимо описать как ручную с реальной Ollama, если нет в CI): заархивировать короткую сессию, затем `memory_search` по релевантному запросу → чанк находится; зафиксировать наблюдение в ADR.

Оформить **ADR** в `_docs/decisions.md` (следующий свободный номер, вероятно ADR-4): контекст → варианты → решение (остаёмся на `sqlite-vec`; внедряем task-префиксы; метрика/TTL — по итогам, при необходимости в roadmap) → последствия. Синхронизировать `_docs/roadmap.md` (добавить отложенные пункты: метрика cosine + миграция, TTL-cleanup, чанкинг сырой сессии — если решено).

#### Definition of Done

- [x] ADR добавлен в `_docs/decisions.md` (контекст/варианты/решение/последствия), решение по архитектуре БД и метрике зафиксировано.
- [x] `_docs/roadmap.md` синхронизирован (отложенные улучшения RAG добавлены с обоснованием).
- [x] `_docs/memory.md` уточнён по фактическим находкам (при расхождении с кодом — приоритет коду).
- [x] Тесты — `n/a` (spike). `git status` чист; `check_doc_links` зелёный.

### Задача 3.2. Task-префиксы эмбеддингов (`search_document:` / `search_query:`)

- **Статус:** Done
- **Приоритет:** medium
- **Объём:** M
- **Зависит от:** Задача 3.1 (внедряем только если spike подтвердил)
- **Связанные документы:** `_docs/memory.md` §3.2–§3.4; ADR из 3.1.
- **Затрагиваемые файлы:** `app/config.py`, `.env.example`, `app/services/archiver.py`, `app/tools/memory_search.py`, `app/services/session_bootstrap.py`, соответствующие тесты в `tests/services/` и `tests/tools/`, `_docs/memory.md`.

#### Описание

Внедрить рекомендованные `nomic` task-префиксы: при **записи** чанков (архивация) эмбеддить `f"search_document: {chunk}"`; при **поиске** (tool `memory_search` и авто-подгрузка `session_bootstrap`) эмбеддить `f"search_query: {query}"`. Сам текст чанка в `memory_chunks.text` хранить **без** префикса (префикс — только для вычисления вектора).

Конфиг (чтобы не хардкодить и отключать для не-nomic моделей): `embedding_document_prefix: str = "search_document: "` и `embedding_query_prefix: str = "search_query: "` в `Settings` + записи в `.env.example` (пустая строка = без префикса). Применять префикс там, где вызывается `llm.embed(...)` для документа/запроса.

**Важно (зафиксировать в доке и подтверждении пользователю):** смена схемы эмбеддинга делает **старый архив несовместимым** по качеству поиска (векторы считались иначе). Для single-user это приемлемо: описать в `_docs/memory.md`, что при желании можно начать архив заново (удалить `data/memory.db` или сделать несколько `/new`). Миграцию старых векторов не делаем.

#### Definition of Done

- [x] Префиксы применяются при архивации (document) и при поиске/бутстрапе (query); `memory_chunks.text` — без префикса.
- [x] Новые поля `Settings` есть в `.env.example`; `check_env_sync` зелёный; пустой префикс отключает поведение.
- [x] Тесты: архивация вызывает `embed` с document-префиксом; `memory_search`/bootstrap — с query-префиксом (мок `llm.embed`, проверка аргумента); текст чанка сохранён без префикса.
- [x] `_docs/memory.md` §3.2–§3.4 обновлён (в т.ч. про несовместимость старого архива).
- [x] `pytest -q` зелёный, покрытие не нарушено; `git status` чист.

---

## 7. Этап 4. Документация и презентабельность

Цель: свести документацию к фактическому состоянию кода и сделать корневой `README.md` презентабельным. Делается **после** кодовых этапов (см. `_board/process.md` §3 п.5).

### Задача 4.1. Актуализация `_docs/*` и roadmap

- **Статус:** Done
- **Приоритет:** medium
- **Объём:** M
- **Зависит от:** Задачи 1.1, 2.1–2.6, 3.1–3.2
- **Связанные документы:** все затронутые в спринте.
- **Затрагиваемые файлы:** `_docs/current-state.md`, `_docs/architecture.md`, `_docs/observability.md`, `_docs/memory.md`, `_docs/roadmap.md`, `_docs/decisions.md`, `_docs/stack.md` §9, `_docs/commands.md`, `_docs/tools.md`, `_docs/README.md`.

#### Описание

Пройти по фактическим изменениям спринта и синхронизировать документацию:

- `current-state.md` §1 — новые подсистемы: планировщик (§1.10 «Планировщик задач»), настраиваемый порог GlitchTip (§1.7), task-префиксы RAG (§1.2).
- `architecture.md` — компонент «Планировщик» и точка расширения (channel-notifier).
- `stack.md` §9 — все новые env (`SENTRY_EVENT_LEVEL`, `SCHEDULER_*`, `EMBEDDING_*_PREFIX`).
- `roadmap.md` — вынести отложенные пункты (доставка планировщика в console/MAX; bot-команды `/schedule`; cosine-метрика + миграция; TTL RAG; естественный парсер времени).
- `commands.md`/`tools.md` — новые tools планировщика (если ещё не покрыто задачей 2.4/2.6).
- Проверить, что все ссылки относительные и не битые.

#### Definition of Done

- [x] Документы `_docs/*` соответствуют коду; roadmap синхронизирован; ADR на месте.
- [x] `check_doc_links`, `check_env_sync`, `check_sprint_sync` зелёные.
- [x] Тесты — `n/a` (docs). `git status` чист.

### Задача 4.2. Презентабельность `README.md` + финальная сверка гейтов

- **Статус:** Done
- **Приоритет:** medium
- **Объём:** M
- **Зависит от:** Задача 4.1
- **Связанные документы:** `README.md`; `.agents/skills/git-discipline/scripts/preflight.sh`.
- **Затрагиваемые файлы:** `README.md`.

#### Описание

Обновить корневой `README.md`, сохранив стиль:

- В «Возможности» добавить пункт про **планировщик задач** (cron из Telegram на естественном языке, APScheduler, персистентность, доставка результата) со ссылками на `app/services/scheduler.py` и `_docs/scheduler.md`.
- В «Логирование» — упомянуть настраиваемый порог отправки логов в GlitchTip (`SENTRY_EVENT_LEVEL`).
- В «Долгосрочная память» — упомянуть task-префиксы `nomic` (качество RAG).
- Обновить список спринтов (добавить «14 (Планировщик, GlitchTip-логи, качество RAG)»), таблицу команд/tools при необходимости, «Требования» (упомянуть `APScheduler` как зависимость), раздел «Документация» (ссылка на `_docs/scheduler.md`).
- Проверить эмодзи/ссылки/бейджи, чтобы README оставался аккуратным.

Финальная сверка: прогнать `bash .agents/skills/git-discipline/scripts/preflight.sh` (flake8 + pytest + все скрипты-гейты) — всё зелёное.

#### Definition of Done

- [x] `README.md` актуален и презентабелен; ссылки относительные и рабочие.
- [x] `preflight.sh` зелёный (flake8, pytest c порогом покрытия, `check_env_sync`, `check_sprint_sync`, `check_doc_links`, `check_agents_sync`).
- [x] Тесты — `n/a` (docs, но общий `pytest` должен быть зелёным). `git status` чист.

---

## 8. Риски и смягчение

| # | Риск | Смягчение |
|---|------|-----------|
| 1 | APScheduler-job пытается сериализоваться (pickle) и падает | `MemoryJobStore` + `args=[task_id]` + top-level/замыкание-раннер; сложные объекты в job не кладём. Персистентность — своя таблица, не JobStore. |
| 2 | Планировщик засоряет живую сессию пользователя | Задание не публикует события шины и не пишет в `ConversationStore`; изоляция задокументирована. |
| 3 | Плановый prompt — вектор prompt-injection | `sanitize_user_input` при создании и в раннере; `ResponseSanitizer` на выходе Executor; scope tools по `user_id`; лимит задач. |
| 4 | GlitchTip «завален» issue при `SENTRY_EVENT_LEVEL=INFO` | Порог настраивается; в доке рекомендация `WARNING`; дефолт `INFO` — по явному запросу пользователя. |
| 5 | Смена схемы эмбеддинга ломает старый архив | Префикс включается флагом; в доке — как пересобрать архив; миграцию векторов не делаем (single-user). |
| 6 | Гонка sqlite при доступе к `scheduled_tasks` из job-потоков | Доступ к соединению сериализован `threading.Lock` (регресс из `current-state.md` §2.3). |
| 7 | Смена метрики близости требует пересоздания БД | Вынесено из спринта: если spike (3.1) рекомендует cosine — задача уходит в `roadmap.md`. |
| 8 | Старт scheduler ломает `tests/test_main.py` smoke | Scheduler мокается/не стартует в smoke; `SCHEDULER_ENABLED` управляет запуском. |

## 9. Сводная таблица задач спринта

| #   | Задача | Приоритет | Объём | Статус | Зависит от |
|-----|--------|:---------:|:-----:|:------:|:----------:|
| 1.1 | Настраиваемый порог событий Sentry/GlitchTip | high | S | Done | — |
| 1.2 | Логи в GlitchTip Logs (не Issues) | high | S | Done | 1.1 |
| 1.3 | Performance-трассировки и Crons в GlitchTip | medium | S | Done | 1.1 |
| 2.1 | Хранилище расписаний `ScheduledTaskStore` (sqlite) | high | M | Done | — |
| 2.2 | `SchedulerService` (APScheduler) + lifecycle | high | M | Done | 2.1 |
| 2.3 | Исполнение задания и доставка в Telegram | high | M | Done | 2.2 |
| 2.4 | Tools: schedule/list/cancel scheduled task | high | M | Done | 2.3 |
| 2.5 | Скилл `scheduler` (маппинг времени в cron) | medium | S | Done | 2.4 |
| 2.6 | Документ `_docs/scheduler.md` + ссылки | medium | S | Done | 2.1–2.5 |
| 2.7 | Фиксы cron-исполнения (изоляция истории, контекст, `AGENT_MAX_STEPS=30`) | high | S | Done | 2.3 |
| 3.1 | Spike: аудит RAG-пайплайна + ADR | high | M | Done | — |
| 3.2 | Task-префиксы эмбеддингов (`nomic`) | medium | M | Done | 3.1 |
| 4.1 | Актуализация `_docs/*` и roadmap | medium | M | Done | 1.1, 2.1–2.6, 3.1–3.2 |
| 4.2 | Презентабельность `README.md` + сверка гейтов | medium | M | Done | 4.1 |

> Обновляется при каждом переходе статуса и при добавлении/удалении задач.

## 10. История изменений спринта

- **2026-07-10** — спринт открыт, ветка `feature/14-scheduler-logs-rag` создана от `main`. Ключевые решения согласованы с пользователем: планировщик = APScheduler (не Celery, ADR-2); логи INFO+ в существующий GlitchTip (не ELK); векторная БД остаётся `sqlite-vec` (ADR-3), только улучшения качества RAG.
- **2026-07-20** — задача 1.1 закрыта: `SENTRY_EVENT_LEVEL` (default `INFO`) добавлен в `Settings` с валидатором, `setup_sentry` использует настраиваемый `event_level`, `.env.example` обновлён, тесты в `tests/observability/test_event_level.py`, доки в `observability.md` §5 и `current-state.md` §1.7.
- **2026-07-20** — задача 2.1 закрыта: `ScheduledTaskStore` (sqlite, `scheduled_tasks` в `data/memory.db`) с `ScheduledTask` dataclass, 12 тестов в `tests/services/test_scheduled_tasks.py`.
- **2026-07-20** — задача 2.2 закрыта: `SchedulerService` (APScheduler, `MemoryJobStore`, rehydrate из store), Settings (`scheduler_enabled`/`scheduler_timezone`/`scheduler_max_jobs_per_user`), lifecycle в `app/main.py`, 9 тестов в `tests/services/test_scheduler.py`.
- **2026-07-20** — задача 2.3 закрыта: `run_scheduled_task` (orchestrator без событий шины, trace_id/user_id binding, sanitize, mark_run ok/error), `make_telegram_notifier` (bot.send_message, split_long_message, html.escape), 5 тестов в `tests/services/test_scheduler_runner.py`.
- **2026-07-20** — задача 2.4 закрыта: tools `schedule_task`/`list_scheduled_tasks`/`cancel_scheduled_task` (ToolContext + scheduler, Executor прокидывает scheduler), `SchedulerService.store` property, 11 тестов в `tests/tools/test_schedule_task.py`. `_docs/tools.md` будет обновлён в задаче 2.6.
- **2026-07-20** — задача 2.5 закрыта: скилл `scheduler` (`app/skills/scheduler/SKILL.md`) — таблица маппинга времени в cron, порядок действий, безопасность. SkillRegistry подхватывает.
- **2026-07-20** — задача 2.6 закрыта: `_docs/scheduler.md` (архитектура, поток, безопасность, конфиг, tools, скилл, ADR-2, ограничения MVP), ссылки в `_docs/README.md` и `_docs/architecture.md`. `check_doc_links` зелёный.
- **2026-07-20** — задача 3.1 закрыта: ADR-4 (аудит RAG: task-префиксы внедрить (3.2), L2 оставить, TTL → roadmap Этап 17, sqlite-vec подтверждён), `_docs/roadmap.md` (Этап 17 + отказ cosine), `_docs/memory.md` §3.2 (заметки о префиксах и метрике).
- **2026-07-20** — задача 3.2 закрыта: `embedding_document_prefix` / `embedding_query_prefix` в Settings + `.env.example`, Archiver применяет document-префикс, memory_search и session_bootstrap — query-префикс, текст чанка в БД без префикса, 2 новых теста в test_archiver.py, обновлены test_memory_search.py и test_session_bootstrap.py, `_docs/memory.md` §3.2 обновлён.
- **2026-07-20** — задача 1.2 закрыта: `enable_logs=True` + `auto_session_tracking=False` в `sentry_sdk.init`, `SENTRY_EVENT_LEVEL` дефолт изменён на `ERROR`, добавлены `SENTRY_LOG_LEVEL` (дефолт `INFO`, настраиваемый порог для Logs/breadcrumbs) и `SENTRY_ENABLE_LOGS` в Settings + `.env.example`, `_docs/observability.md` §5 обновлён (разделение Logs vs Issues), 5 новых тестов в test_event_level.py, обновлены test_setup_sentry.py и test_error_capture.py.
- **2026-07-20** — задача 1.3 закрыта: `SENTRY_TRACES_SAMPLE_RATE` дефолт поднят до `0.1` (Performance), `_cron_checkin` в `scheduler_runner.py` отправляет heartbeat в GlitchTip Crons (`in_progress`/`ok`/`error`), 4 новых теста в test_scheduler_runner.py, `_docs/observability.md` §5 обновлён (Performance, Crons).
- **2026-07-21** — задача 2.7 оформлена постфактум (Done): формализация двух фиксов cron-исполнения по итогам ручного тестирования — изоляция истории (`history` в `handle_user_task`, `run_scheduled_task` передаёт `history=[]`, commit `cbe02c07`) и контекст исполнения + `AGENT_MAX_STEPS` 15→30 (`scheduler_runner.py`, `config.py`, доки, commit `0cacd7ce`). Код и тесты уже в ветке; добавлена запись в доску (см. `process.md` §3 п.4).
- **2026-07-21** — задача 4.1 закрыта: аудит и актуализация `_docs/*` — `current-state.md` §1.10 (планировщик), §1.2 (RAG task-префиксы), §1.7 (GlitchTip Logs/Issues, Performance/Crons); `stack.md` §9 (env `SENTRY_*`, `SCHEDULER_*`, `EMBEDDING_*_PREFIX`); `tools.md` §4.16–4.18 (tools планировщика); `architecture.md` §8.6 (notifier); `roadmap.md` Этап 18 (расширения планировщика); исправлен баг дефолта `SCHEDULER_MAX_JOBS_PER_USER` в `scheduler.md` (5 → 20). Гейты `check_doc_links`/`check_env_sync`/`check_sprint_sync` зелёные.
- **2026-07-21** — задача 4.2 закрыта: `README.md` актуализирован (планировщик в «Возможности» и стеке, tools планировщика, task-префиксы RAG, разделение GlitchTip Logs/Issues + Crons, спринт 14 в списке, ссылка на `_docs/scheduler.md`); бейджи проверены (репозиторий `radif-ru/ai-multi-agent-system`, coverage 88% совпадает с фактом). `preflight.sh` полностью зелёный (flake8, pytest `--cov-fail-under=80` → 88.11%, все 6 гейтов).
- **2026-07-21** — **спринт закрыт**: все 14 задач в `Done`, Acceptance Criteria закрыты, `preflight.sh` зелёный (flake8, pytest 88.11%, 6 гейтов). По итогам аудита работы предыдущей LLM: код этапов 1–3 качественный, внеспринтовые фиксы оформлены задачей 2.7, документация (`_docs/*`, `README.md`) синхронизирована с фактическим состоянием (задачи 4.1–4.2). Merge в `main` — за пользователем (см. `process.md` §2 п.8).
