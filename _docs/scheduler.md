# Планировщик задач

Назначение, архитектура и ограничения встроенного планировщика регулярных задач (спринт 14, задачи 2.1–2.5; расширения — спринт 15: multi-channel доставка, bot-команды, парсер естественного языка).

## Назначение

Пользователь может попросить агента выполнять задачу регулярно по расписанию — например, «проверяй почту каждый день в 9 утра» или «напоминай выпить воду каждые 2 часа». Планировщик создаёт cron-задачу, которая при срабатывании запускает агентный цикл с указанным prompt и доставляет результат через notifier, соответствующий каналу задачи (Telegram, консоль или MAX).

## Архитектура

### Компоненты

- **`ScheduledTaskStore`** (`app/services/scheduled_tasks.py`) — sqlite-хранилище задач в таблице `scheduled_tasks` (в `data/memory.db`). Хранит: `id`, `user_id`, `chat_id`, `channel`, `prompt`, `cron`, `timezone`, `enabled`, `last_run_at`, `last_status`.
- **`SchedulerService`** (`app/services/scheduler.py`) — обёртка над APScheduler `AsyncIOScheduler` с `MemoryJobStore`. Персистентность обеспечивается `ScheduledTaskStore`, а jobs пересоздаются из таблицы при `start()` (rehydrate). Раннер (`run_task`) — внедряемый callable, задаётся в `app/main.py` после сборки компонентов.
- **`run_scheduled_task`** (`app/services/scheduler_runner.py`) — раннер: биндит `trace_id`/`user_id`, санизирует prompt, вызывает `handle_user_task` (оркестратор), обрабатывает ошибки, доставляет результат через notifier.
- **`make_telegram_notifier`** (`app/services/scheduler_runner.py`) — фабрика notifier для Telegram: `bot.send_message` с `split_long_message` и `html.escape`.
- **`make_console_notifier`** (`app/services/scheduler_runner.py`) — фабрика notifier для консоли: печать результата в stdout.
- **`make_max_notifier`** (`app/services/scheduler_runner.py`) — фабрика notifier для MAX: `MaxClient.send_message` с разбивкой по лимиту API.

### Поток исполнения задания

```
CronTrigger срабатывает
  → SchedulerService._job_entrypoint(task_id)
    → store.get(task_id) → task
    → run_task(task)  # внедрённый раннер
      → run_scheduled_task(task, deps=RunnerDeps, notifier=notifier)
        → bind trace_id, user_id (contextvars)
        → sanitize_user_input(task.prompt)
        → handle_user_task(prompt, user_id, chat_id, ...)
        → mark_run(ok | error)
        → notifier(chat_id, result_text)
        → reset trace_id, user_id
```

### Изоляция от живой сессии

Задание выполняется через тот же `handle_user_task`, что и Telegram-хендлер, но:

- **События шины не публикуются** (нет `MessageReceived`/`ResponseGenerated`).
- **История диалога не пишется** — задание стартует с пустой историей, не вмешиваясь в активную сессию пользователя.
- **`trace_id`/`user_id`** биндятся через contextvars и сбрасываются в `finally`.

### Lifecycle

- `SchedulerService` создаётся в `_build_components` (`app/main.py`).
- `run_task` callback устанавливается в `main()` после создания bot'а.
- `scheduler.start()` вызывается в `main()` если `SCHEDULER_ENABLED=true`.
- `scheduler.shutdown()` — в `_shutdown_components`.

## Безопасность

- **Sanitize**: prompt задачи проходит `sanitize_user_input` (защита от prompt injection).
- **Лимит**: `SCHEDULER_MAX_JOBS_PER_USER` (по умолчанию 20) — `schedule_task` tool проверяет `store.count_by_user` перед созданием.
- **Scope по user_id**: `list_scheduled_tasks` и `cancel_scheduled_task` работают только с задачами текущего пользователя; нельзя отменить чужую задачу.
- **Не в `_DANGEROUS_TOOLS`**: tools планировщика не трогают ФС/сеть напрямую, работают только со своими задачами.

## Конфигурация

| Переменная | Default | Описание |
|---|---|---|
| `SCHEDULER_ENABLED` | `true` | Включить/выключить планировщик |
| `SCHEDULER_TIMEZONE` | `Europe/Moscow` | Часовой пояс для jobs |
| `SCHEDULER_MAX_JOBS_PER_USER` | `20` | Лимит задач на пользователя |

## Tools

Три tool'а по контракту `app/tools/base.py::Tool`, регистрируются в `ToolRegistry`:

- **`schedule_task`** (args: `prompt`, `schedule_text?`, `cron?`, `timezone?`) — создаёт задачу. Если передан `schedule_text` — вызывается `parse_cron` (детерминированный парсер); если не распознан — fallback на `cron`. Валидирует cron через `CronTrigger.from_crontab`, проверяет лимит, санизирует prompt.
- **`list_scheduled_tasks`** (args: нет) — список задач текущего пользователя.
- **`cancel_scheduled_task`** (args: `task_id`) — отмена задачи по ID (scope по `user_id`).

`ToolContext` дополнен атрибутом `scheduler` (прокидывается через `Executor`).

## Скилл

`app/skills/scheduler/SKILL.md` — инструкция агенту: когда использовать, таблица маппинга естественного языка в 5-польный cron, порядок действий, безопасность. Скилл инжектится в системный промпт через `SkillRegistry`.

### Детерминированный парсер

`app/services/cron_parser.py` — парсер естественного языка → 5-польный cron. Поддерживаемые паттерны: «каждый день в N», «по будням в N», «каждый час», «каждые N часов/минут», «каждый понедельник в N», «каждое N число месяца», «каждую неделю». Если паттерн не распознан — возвращает `None`, fallback на LLM (graceful). Тесты: `tests/services/test_cron_parser.py`.

## Решение: APScheduler, не Celery/n8n

Согласно [ADR-2](./decisions.md#adr-2-n8n-как-оркестратор-интеграций), n8n избыточен для single-user local-first системы: дублирует `EventBus`, orchestrator и tools, добавляет Docker-зависимость и поверхность атаки. APScheduler выбран как лёгкая библиотека, работающая внутри Python-процесса, без внешних зависимостей.

## Ограничения

- **Multi-channel доставка**: результат задания отправляется через notifier, соответствующий каналу задачи (`telegram` — `bot.send_message`, `console` — печать в stdout, `max` — `MaxClient.send_message`). Выбор notifier по `task.channel` в точке входа (`app/main.py`, `app/console_main.py`, `app/max_main.py`).
- **Cron-only**: детерминированный парсер `cron_parser.py` покрывает базовые паттерны («каждый день в N», «по будням в N», «каждый час» и т.д.); нераспознанные паттерны — fallback на LLM по скиллу `scheduler`.
- **MemoryJobStore**: jobs хранятся в памяти APScheduler, персистентность — только в sqlite-таблице. При рестарте jobs пересоздаются из store (rehydrate).
- **Нет webhook-триггеров**: только cron. Webhook — через FastAPI-адаптер (`_docs/roadmap.md` § «Webhook вместо polling (Telegram и MAX)»).
