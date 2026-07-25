# Наблюдаемость

Единый раздел про логи, трассировку и (в следующих задачах спринта 06) error tracking. Источник истины по коду — `app/core/logging_config.py`, `app/utils/tracing.py`, `app/middlewares/logging_mw.py`.

## 1. Структурные JSON-логи

Все логи приложения — валидные JSON-объекты, по одной записи на строку. Формирует `JsonFormatter` (`app/core/logging_config.py`), подключён как к `StreamHandler` (консоль), так и к `TimedRotatingFileHandler` (файл `LOG_FILE`, по умолчанию `logs/agent.log`; ротация ежедневно в полночь UTC, хранятся 14 последних ротированных файлов, более старые удаляются автоматически).

### Формат записи

```json
{
  "timestamp": "2026-05-11T12:34:56.123456+00:00",
  "level": "INFO",
  "service": "ai-multi-agent-system",
  "name": "app.services.llm",
  "message": "llm kind=chat model=qwen3.5:4b len_in=...",
  "trace_id": "a1b2c3d4e5f6",
  "user_id": 12345,
  "extra": { "duration_ms": 420, "status": "ok" }
}
```

Поля:

- `timestamp` — ISO-8601 UTC, с микросекундами.
- `level` — `DEBUG | INFO | WARNING | ERROR | CRITICAL`.
- `service` — константа `ai-multi-agent-system`.
- `name` — имя логгера (обычно `__name__` модуля).
- `message` — собственно текст записи.
- `trace_id` — короткий (12 hex) идентификатор текущего внешнего действия. `null`, если контекст не установлен.
- `user_id` — идентификатор пользователя, если биндится на этом уровне (`null` иначе).
- `extra` — произвольные поля, переданные через `logger.info(..., extra={"duration_ms": 42})`. Стандартные атрибуты `LogRecord` исключаются автоматически.
- `exc_info` / `stack_info` — текстовый дамп исключения / стека, если есть.

### Проверка

```bash
jq -c . < logs/agent.log | head -5
```

Если строка невалидна — `jq` завершится ошибкой.

## 2. Трассировка (`trace_id`)

`app/utils/tracing.py` хранит `trace_id` и `user_id` в `contextvars.ContextVar`. Это даёт автоматическую изоляцию по `asyncio.Task`: каждая корутина, обрабатывающая отдельное сообщение, получает свой идентификатор, а параллельные обработки не перемешиваются.

API:

```python
from app.utils.tracing import new_trace_id, bind_trace_id, reset_trace_id, get_trace_id
from app.utils.tracing import bind_user_id, reset_user_id

trace_token = bind_trace_id(new_trace_id())
user_token = bind_user_id(user_id)
try:
    ...  # вся обработка: handler → executor → llm → tools
finally:
    reset_user_id(user_token)
    reset_trace_id(trace_token)
```

`ContextFilter` (`app/core/logging_config.py`) автоматически подмешивает значения в каждую запись лога. Прокидывать их вручную через `extra=` не нужно; это имеет смысл только чтобы явно переопределить (например, в фоновой задаче с другим trace_id).

Где устанавливается:

- **Telegram**: `LoggingMiddleware` (`app/middlewares/logging_mw.py`) — на каждый `Update` генерируется новый `trace_id` и биндится `user_id`; оба сбрасываются в `finally` (в том числе при исключении в handler). `user_id`/`chat_id` берутся из `data["event_from_user"]` / `data["event_chat"]` — их подкладывает встроенный `UserContextMiddleware` aiogram до вызова inner-middleware на `dispatcher.update` (у самого `Update` атрибутов `from_user`/`chat` нет, они есть только у вложенных событий).
- **Console adapter**: `ConsoleAdapter.run` (`app/adapters/console/adapter.py`) — на каждую введённую команду или текст свежий `trace_id`, сбрасывается после обработки.
- **Фоновая архивация (recovery)**: планируется как отдельная задача (см. спринт 06 этап 4.3 / будущие спринты) — пока `recover_pending_journals` пишет логи без `trace_id` (`null`).

## 3. Границы внешних вызовов

Все сервисы, дёргающие внешние ресурсы, пишут согласованные записи вокруг каждого вызова:

- `external.call service=<name> ...` — перед вызовом (info).
- `external.ok service=<name> dur_ms=<n> ...` — успешное завершение (info).
- `external.fail service=<name> dur_ms=<n> error=<str> ...` — ошибка (error).

Поля в `extra`: `service`, `duration_ms`, `status`, плюс сервис-специфичные (`model`, `host`, `engine`, `http_status`, `len_in/len_out`, `n_results`, `queue_wait_ms` …). Сырые payload'ы и сами ответы LLM/поиска в логи не попадают.

Точки установки (`grep -n external.call app`):

- `app/services/llm.py` — `service=ollama`, `kind=chat|embed`. Дополнительно пишет `queue_wait_ms` — время ожидания слота общего gate (`LLM_MAX_CONCURRENCY`); полезно для диагностики конкуренции live vs `journal_recovery`. Для `chat` также пишет `think` (reasoning-токены), `out_tok` (количество сгенерированных токенов из `eval_count`), `tok_per_s` (скорость генерации токенов/с из `eval_duration`).
- `app/services/transcribe.py` — `service=transcribe`.
- `app/services/vision.py` — `service=vision`.
- `app/services/ocr.py` — `service=ocr`.
- `app/tools/http_request.py` — `service=http_request`, `host`.
- `app/tools/web_search.py` — `service=web_search`, `engine`.

## 4. Маскирование секретов

`app/utils/secrets.py::mask_secrets(d)` рекурсивно заменяет значения секретных ключей на `"***"`:

- Ключи, содержащие `token`, `secret`, `password`, `passwd`, `api_key`/`apikey`, `authorization`.
- Точные имена `auth`, `bearer`, `key`, `x-api-key` (регистронезависимо).

Использовать **перед** тем как положить структуру в `extra=` (или при логировании заголовков/конфигов). URL и тела HTTP-ответов по текущим настройкам в логи не пишутся — тем самым заголовок `Authorization` туда не уезжает. Тесты: `tests/utils/test_secrets.py`.

## 5. Error tracking (GlitchTip / Sentry)

`app/observability/__init__.py::setup_sentry(settings)` — единственная точка инициализации `sentry-sdk`. Вызывается в `app/main.py::main` и `app/console_main.py::main` сразу после `setup_logging(settings)`. Если `SENTRY_DSN` пуст (по умолчанию) — функция ничего не делает, `sentry_sdk.init(...)` не вызывается, сеть не дёргается; бот стартует как обычно.

### Конфигурация (`.env`)

| Переменная | Дефолт | Назначение |
|---|---|---|
| `SENTRY_DSN` | *(пусто)* | DSN self-hosted GlitchTip (Sentry-совместимый). Пустое значение = error tracking выключен. |
| `SENTRY_ENVIRONMENT` | `dev` | Тег `event.environment`: `dev` / `staging` / `prod`. |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.1` | Доля запросов с performance-трассировкой (вкладка **Performance**). `0.0` = выключено, `1.0` = все запросы. По умолчанию `0.1` (10%) — баланс между видимостью и нагрузкой. |
| `SENTRY_EVENT_LEVEL` | `ERROR` | Минимальный уровень логов, которые уезжают в GlitchTip как события **(Issues)** (`DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL`). По умолчанию `ERROR` — только ошибки и исключения создают Issues. |
| `SENTRY_LOG_LEVEL` | `INFO` | Минимальный уровень логов для **Logs API** и breadcrumbs (`DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL`). `DEBUG` включает отладочные логи в Logs — удобно для troubleshooting. |
| `SENTRY_ENABLE_LOGS` | `true` | Отправлять логи в GlitchTip **Logs** (отдельная вкладка, не Issues). Требует `sentry-sdk` >= 2.0 и GlitchTip с поддержкой Logs API. `false` = отключить (ошибки всё равно идут в Issues). |

Глобальные флаги `send_default_pii=False`, `auto_session_tracking=False` (GlitchTip не поддерживает sessions) и хук `before_send` (см. ниже) — зашиты в код, не конфигурируются.

### Хук `before_send`

`app.observability._before_send(event, hint)` обогащает каждое событие перед отправкой:

- `trace_id` из `contextvars` (см. §2) → `event.tags.trace_id` и `event.extra.trace_id`;
- `user_id` из `contextvars` → `event.user.id` (строкой).

Возврат `None` (который бы отменил отправку) не используется: хук не фильтрует события, только обогащает. Если контекст пуст — возвращается исходный event без изменений.

### Интеграции

**Разделение Logs vs Issues:**

- **Logs** (`enable_logs=True`, `SENTRY_LOG_LEVEL`): информационные логи уровня `SENTRY_LOG_LEVEL` (по умолчанию `INFO`) и выше направляются во вкладку **Logs** через Sentry Logs API. Не создают Issues. Управляется флагом `SENTRY_ENABLE_LOGS`. `SENTRY_LOG_LEVEL=DEBUG` включает отладочные логи.
- **Issues** (`LoggingIntegration`, `SENTRY_EVENT_LEVEL`): логи уровня `SENTRY_EVENT_LEVEL` (по умолчанию `ERROR`) и выше создают события во вкладке **Issues**. Уровни ниже порога идут в breadcrumbs. `DEBUG` можно включить через `SENTRY_LOG_LEVEL=DEBUG` — он пойдёт в Logs и breadcrumbs, но не в Issues.
- `auto_session_tracking=False` — GlitchTip не поддерживает sessions.

> **Важно:** Issues — для ошибок и исключений. Logs — для информационных логов. При дефолтных настройках (`SENTRY_EVENT_LEVEL=ERROR`, `SENTRY_LOG_LEVEL=INFO`, `SENTRY_ENABLE_LOGS=true`) INFO/WARNING идут в Logs, ERROR+ — в Issues. Если нужно видеть WARNING в Issues — поднять `SENTRY_EVENT_LEVEL=WARNING`.

### Performance

`SENTRY_TRACES_SAMPLE_RATE` (дефолт `0.1`) — доля запросов, для которых снимается performance-трассировка (вкладка **Performance** в GlitchTip). Трассировки показывают span'ы agent loop (LLM call → tools → response), что помогает диагностировать задержки. `0.0` = выключено, `1.0` = все запросы.

### Crons

> **GlitchTip не поддерживает Sentry Crons API** (в отличие от облачного Sentry). Раздел Crons отсутствует в интерфейсе. Heartbeat запланированных задач логируется через стандартное логирование (`scheduler.run status=start/ok/error` с `dur_ms`) и попадает во вкладку **Logs** (или **Issues** при ошибке).

### Self-hosted GlitchTip: локальный запуск

В репозитории лежит `docker-compose.observability.yml` — минимальный стек (postgres + redis + GlitchTip web + worker + migrate) для локальной разработки. Он не привязан к `docker-compose` самого бота (бот остаётся в этом спринте без контейнера).

Пошагово:

1. Поднять стек:

   ```bash
   docker compose -f docker-compose.observability.yml up -d
   ```

   Первый запуск тянет образы (~300 МБ) и выполняет миграции. Готовность:

   ```bash
   docker compose -f docker-compose.observability.yml logs -f web
   # ждём "Starting gunicorn" / "Listening at: http://0.0.0.0:8000"
   ```

2. Открыть <http://localhost:8100>. Зарегистрировать первого пользователя (он автоматически становится superuser).

3. Создать организацию и проект с платформой `Python`. После создания скопировать DSN из **Settings → Client Keys (DSN)**.

4. Прописать DSN в `.env` бота:

   ```dotenv
   SENTRY_DSN=http://<public_key>@localhost:8100/<project_id>
   SENTRY_ENVIRONMENT=dev
   ```

5. Перезапустить бота (`python -m app`) — в логах появится `sentry: инициализирован`.

Остановка без удаления данных:

```bash
docker compose -f docker-compose.observability.yml down
```

С удалением postgres/uploads:

```bash
docker compose -f docker-compose.observability.yml down -v
```

> **Прод/staging.** Перед выкаткой за пределы `localhost` заменить `SECRET_KEY` на случайный (сгенерировать `python -c "import secrets; print(secrets.token_urlsafe(50))"`), поменять `GLITCHTIP_DOMAIN`, настроить реальный `EMAIL_URL`. Текущий compose предназначен только для разработки.

### Проверка через ошибки

Smoke-тесты в `tests/observability/test_error_capture.py` подменяют реальный HTTP-transport на in-memory буфер (`_InMemoryTransport`) и прогоняют четыре класса искусственных ошибок:

1. Ручной `raise ValueError(...)`.
2. Ошибка в `asyncio.create_task(...)`.
3. Ошибка внешнего вызова (`httpx.TimeoutException`).
4. Ошибка данных (`json.JSONDecodeError`).

Для каждого сценария проверяется, что событие дошло до transport, `event.exception.values[-1].stacktrace` присутствует, а `event.tags.trace_id` совпадает с установленным через `bind_trace_id(...)`.
