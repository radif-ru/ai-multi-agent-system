# Наблюдаемость

Единый раздел про логи, трассировку и (в следующих задачах спринта 06) error tracking. Источник истины по коду — `app/logging_config.py`, `app/utils/tracing.py`, `app/middlewares/logging_mw.py`.

## 1. Структурные JSON-логи

Все логи приложения — валидные JSON-объекты, по одной записи на строку. Формирует `JsonFormatter` (`app/logging_config.py`), подключён как к `StreamHandler` (консоль), так и к `RotatingFileHandler` (файл `LOG_FILE`, по умолчанию `logs/agent.log`).

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

`ContextFilter` (`app/logging_config.py`) автоматически подмешивает значения в каждую запись лога. Прокидывать их вручную через `extra=` не нужно; это имеет смысл только чтобы явно переопределить (например, в фоновой задаче с другим trace_id).

Где устанавливается:

- **Telegram**: `LoggingMiddleware` (`app/middlewares/logging_mw.py`) — на каждый `Update` генерируется новый `trace_id` и биндится `user_id`; оба сбрасываются в `finally` (в том числе при исключении в handler).
- **Console adapter**: `ConsoleAdapter.run` (`app/adapters/console/adapter.py`) — на каждую введённую команду или текст свежий `trace_id`, сбрасывается после обработки.
- **Фоновая архивация (recovery)**: планируется как отдельная задача (см. спринт 06 этап 4.3 / будущие спринты) — пока `recover_pending_journals` пишет логи без `trace_id` (`null`).

## 3. Границы внешних вызовов

Все сервисы, дёргающие внешние ресурсы, пишут согласованные записи вокруг каждого вызова:

- `external.call service=<name> ...` — перед вызовом (info).
- `external.ok service=<name> dur_ms=<n> ...` — успешное завершение (info).
- `external.fail service=<name> dur_ms=<n> error=<str> ...` — ошибка (error).

Поля в `extra`: `service`, `duration_ms`, `status`, плюс сервис-специфичные (`model`, `host`, `engine`, `http_status`, `len_in/len_out`, `n_results` …). Сырые payload'ы и сами ответы LLM/поиска в логи не попадают.

Точки установки (`grep -n external.call app`):

- `app/services/llm.py` — `service=ollama`, `kind=chat|embed`.
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

## 5. Error tracking (GlitchTip)

(задачи 5.1–5.3 спринта 06) — `sentry-sdk` с hook'ом `before_send`, прокидывающим `trace_id` и `user_id` в событие. Self-host через `docker-compose.observability.yml`.
