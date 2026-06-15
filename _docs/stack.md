# Технологический стек

## 1. Runtime

- **Python** — 3.14+. Нужен нативный `asyncio`, `tomllib`, совместимость с актуальными aiogram / pydantic / sqlite-vec.
- **OS** — Linux / WSL2 Ubuntu / macOS. Windows нативно — не приоритет (см. ASM-1).

## 2. Telegram

- **aiogram** — `^3.4` (актуальная v3.x). Async, Router-based, встроенные middleware, удобный `Dispatcher.start_polling`.
  - `aiogram.client.default.DefaultBotProperties` для `parse_mode`.
  - `aiogram.filters.Command` для команд.
- Режим получения апдейтов — **long polling** (`dp.start_polling(bot)`), без webhook (CON-4).

## 3. LLM-слой (Ollama)

- **Ollama** — локальный runtime. REST API на `http://localhost:11434`.
- **Модели**:
  - LLM: `qwen3.5:4b` (по умолчанию). Меняется через `OLLAMA_DEFAULT_MODEL` / `OLLAMA_AVAILABLE_MODELS`.
  - Embedding: `nomic-embed-text` (768 dimensions, по умолчанию). Меняется через `EMBEDDING_MODEL` + `EMBEDDING_DIMENSIONS`.
  - Vision: `llava:7b` (для описания изображений). Меняется через `VISION_MODEL`.
- **Клиент**: официальная `ollama` (async-вариант — `ollama.AsyncClient`).

### Обоснование выбора

- `ollama` library — типизированные ответы, async-клиент, поддержка `chat` и `embeddings` в одном API.
- `qwen3.5:4b` — указана в ТЗ; разумный размер для агентного цикла на CPU.
- `nomic-embed-text` — стабильно справляется с русским, 768d удобно ложится в `sqlite-vec` (ширина — не предельная для KNN).

## 4. Векторная БД (долгосрочная память)

- **`sqlite-vec`** — `>=0.1`. Преемник `sqlite-vss`; pure-C SQLite-расширение, ставится через `pip install sqlite-vec`, грузится через `sqlite_vec.load(connection)`.
- Хранит и метаданные, и векторы в одном `.db`-файле (по пути `MEMORY_DB_PATH`).

### Почему не FAISS / Chroma

См. `_docs/memory.md` §3.1 и решение в `_board/sprints/00-bootstrap.md` § «Решения по архитектуре».

## 5. Веб-поиск

- **`ddgs`** (бывшая `duckduckgo-search`) — `>=9.0`. Без API-ключей. Синхронный API, оборачиваем `asyncio.to_thread`.

## 6. HTTP-клиент

- **`httpx`** — `>=0.27`. Async-клиент для tool `http_request` и для тестов LLM-маппинга ошибок (`httpx.TimeoutException`, `httpx.ConnectError`).

## 7. Конфигурация

- **`pydantic-settings`** — `^2.1`. Загрузка `.env`, валидация типов, дефолты.
- **`python-dotenv`** — автоматически подтянется через `pydantic-settings[dotenv]`; явная установка не обязательна.

## 8. Логирование

- Стандартный **`logging`** + `logging.handlers.TimedRotatingFileHandler` (ежедневная ротация в полночь UTC, хранение ~14 дней).
- Конфигурация через `dictConfig` в `app/core/logging_config.py`.
- Формат — **структурный JSON**: поля `timestamp`, `level`, `service`, `name`, `message`, `trace_id`, `user_id`, опционально `extra`/`exc_info`/`stack_info`. Детали — в `_docs/observability.md` §1.
- `trace_id` и `user_id` прокидываются автоматически через `contextvars` (см. `app/utils/tracing.py`, `_docs/observability.md` §2).
- Уровень — из `LOG_LEVEL` (`DEBUG` по умолчанию).
- Файл — из `LOG_FILE` (например, `logs/agent.log`), каталог `logs/` в `.gitignore`.

## 9. Переменные окружения (`.env`)

`.env.example` коммитится, `.env` — в `.gitignore`. Полный список с комментариями — в `.env.example` в корне репо.

| Переменная                  | Назначение                                                      | Default                  |
|-----------------------------|------------------------------------------------------------------|---------------------------|
| `TELEGRAM_BOT_TOKEN`        | Токен бота от @BotFather. **Обязательная.**                      | —                         |
| `MAX_BOT_TOKEN`             | Токен MAX-бота (business.max.ru). Пусто = MAX-канал не запускается. | —                       |
| `MAX_API_BASE_URL`          | Базовый URL MAX Bot API (`dev.max.ru/docs-api`).                | `https://platform-api.max.ru` |
| `MAX_POLL_TIMEOUT`          | Тайм-аут long polling `GET /updates`, секунды.                  | `30`                      |
| `MAX_MAX_FILE_MB`           | Лимит размера скачиваемого из MAX файла, МБ.                     | `20`                      |
| `OLLAMA_BASE_URL`           | URL локального Ollama API.                                       | `http://localhost:11434`  |
| `OLLAMA_DEFAULT_MODEL`      | LLM по умолчанию (должна быть в `OLLAMA_AVAILABLE_MODELS`).      | `qwen3.5:4b`              |
| `OLLAMA_AVAILABLE_MODELS`   | Список разрешённых LLM через запятую.                            | `qwen3.5:4b`              |
| `OLLAMA_TIMEOUT`            | Таймаут одного запроса к Ollama, секунды.                        | `120`                     |
| `OLLAMA_THINK`             | Reasoning-токены «думающей» модели (`true`/`false`). По умолчанию выключено: быстрее, rationale агента и так в поле `thought`. | `false`                   |
| `OLLAMA_KEEP_ALIVE`        | Как долго Ollama держит модель резидентной между запросами (`30m`, `1h`, `0` = выгружать сразу). Убирает холодные перезагрузки. | `30m`                     |
| `OLLAMA_TEMPERATURE`       | Температура сэмплирования для `chat` (вынесена из хардкода). `0.0` — детерминированный вывод. | `0.0`                     |
| `OLLAMA_VRAM_BUDGET_GB`    | Бюджет VRAM (ГБ) для мягкого предупреждения в `/model` о тяжёлой модели (`>= 90%` бюджета). `0` — выключить. | `24.0`                    |
| `EMBEDDING_MODEL`           | Модель эмбеддингов (Ollama).                                     | `nomic-embed-text`        |
| `EMBEDDING_DIMENSIONS`      | Размерность вектора (зависит от модели).                         | `768`                     |
| `EMBEDDING_CONCURRENCY`     | Параллелизм при вычислении embedding для чанков (оптимизация /new). | `5`                       |
| `LLM_MAX_CONCURRENCY`      | Лимит одновременных вызовов к Ollama (`chat`+`embed`) на весь процесс (gate против пайл-апов). | `2`                       |
| `SEARCH_ENGINE_DEFAULT`     | Поисковик по умолчанию.                                         | `duckduckgo`              |
| `SEARCH_ENGINES_AVAILABLE`  | Список доступных поисковиков через запятую.                      | `duckduckgo`              |
| `AGENT_MAX_STEPS`           | Лимит шагов агентного цикла.                                     | `10`                      |
| `AGENT_MAX_OUTPUT_CHARS`    | Лимит размера ответа модели за один шаг (защита от мусора).     | `8000`                    |
| `AGENT_MAX_REPAIR_ATTEMPTS` | Переспросов модели при срыве формата ответа перед `LLMBadResponse` (не даёт `thought` утечь вместо ответа, см. `_docs/agent-loop.md` §2.4). `0` — выключить. | `2`                       |
| `AGENT_REFLECTION_MODE`     | Режим multi-agent рефлексии (`OFF\|NORMAL\|DEEP`), см. `_docs/multi-agent.md`. | `OFF`     |
| `AGENT_REFLECTION_MAX_ITERATIONS` | Верхняя граница итераций Critic в режиме `DEEP`.          | `2`                       |
| `HISTORY_MAX_MESSAGES`      | Жёсткий лимит сообщений in-memory истории на пользователя.       | `20`                      |
| `HISTORY_SUMMARY_THRESHOLD` | Порог in-session суммаризации (`> 0`, `<= HISTORY_MAX_MESSAGES`).| `10`                      |
| `MEMORY_DB_PATH`            | Путь к `.db`-файлу с `sqlite-vec`. Каталог создаётся автоматически. | `data/memory.db`        |
| `MEMORY_CHUNK_SIZE`         | Размер чанка саммари при `/new`, символы.                        | `1500`                    |
| `MEMORY_CHUNK_OVERLAP`      | Перекрытие соседних чанков, символы.                             | `150`                     |
| `MEMORY_SEARCH_TOP_K`       | Сколько чанков возвращать tool'ом `memory_search`.               | `5`                       |
| `SESSION_BOOTSTRAP_ENABLED` | Авто-подгрузка архива в первый ход новой сессии (см. `_docs/memory.md` §3.6). | `true`         |
| `SESSION_BOOTSTRAP_TOP_K`   | Сколько чанков подмешивать при авто-подгрузке.                   | `3`                       |
| `JOURNAL_RECOVERY_CONCURRENCY` | Параллелизм фонового восстановления висящих сессий (`1` = последовательно, оставляет слот под live). | `1`                       |
| `JOURNAL_RECOVERY_MIN_CHARS` | Порог суммарного `content` сессии: «мусор» ниже порога закрывается без LLM-вызова (`0` отключает). | `50`                      |
| `JOURNAL_RECOVERY_START_DELAY` | Пауза перед запуском фонового восстановления, секунды (`0` = без задержки). | `20`                      |
| `AGENT_SYSTEM_PROMPT_PATH`  | Путь к markdown-файлу системного промпта агента.                 | `app/prompts/agent_system.md`|
| `LOG_LEVEL`                 | Уровень логов (`DEBUG\|INFO\|WARNING\|ERROR`).                   | `DEBUG`                   |
| `LOG_FILE`                  | Путь к файлу логов.                                              | `logs/agent.log`          |
| `LOG_LLM_CONTEXT`           | Логировать полный JSON контекста перед LLM-запросом.             | `true`                    |

## 10. Тестирование

- **`pytest`** — `^8.0`.
- **`pytest-asyncio`** — `^0.23` (режим `asyncio_mode = "auto"` в `pyproject.toml`).
- **`pytest-mock`** — `^3.12`.
- Опционально: **`pytest-cov`** для отчёта покрытия.

Конфиг (`pyproject.toml`):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-ra -q"
```

## 11. Качество кода (рекомендовано, не обязательно для MVP)

- **`ruff`** — линтер + форматтер.
- **`mypy`** — статическая типизация (режим `--strict` на сервис-слое).
- **`pre-commit`** — хуки.

## 12. Менеджмент зависимостей

`requirements.txt` (минималистичный, под ТЗ):

```
aiogram>=3.4,<4
ollama>=0.3
pydantic-settings>=2.1,<3
sqlite-vec>=0.1
ddgs>=9.0
httpx>=0.27
pytest>=8
pytest-asyncio>=0.23
pytest-mock>=3.12
```

## 13. Локальные требования окружения

- Установлен **Ollama** (`https://ollama.com`), запущен сервис (`ollama serve` или systemd-юнит).
- Модели предварительно загружены: `ollama pull qwen3.5:4b`, `ollama pull nomic-embed-text`.
- Telegram-бот создан через `@BotFather`, токен сохранён в `.env`.
- Каталог `data/` создаётся автоматически при первой записи в `sqlite-vec` (или вручную: `mkdir data`).
- **Целевая система разработки:** RTX 5090 (24 ГБ VRAM) + Core Ultra 9 275HX. Дефолты `.env.example` (`OLLAMA_NUM_CTX`, `LLM_MAX_CONCURRENCY`, `OLLAMA_KEEP_ALIVE`, `OLLAMA_VRAM_BUDGET_GB`) подобраны под неё; на слабых системах их следует уменьшить (см. `README.md` § «Целевая система и тюнинг под неё»).

## 14. Чего в стеке нет (и не будет в MVP)

- БД, кроме `sqlite-vec` (один `.db`-файл). Никаких PostgreSQL, MongoDB, Redis.
- Облачных LLM (OpenAI, Anthropic и др.).
- Брокеров очередей.
- Docker / docker-compose (можно добавить позже, опционально).
- ORM, миграций (БД одна, схема на ~3 таблицы — ad-hoc DDL в коде).
- FastAPI / web framework — polling не требует входящего HTTP.
