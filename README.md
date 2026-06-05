# ai-multi-agent-system

[![tests](https://github.com/radif-ru/ai_multi_agent_system/actions/workflows/test.yml/badge.svg)](https://github.com/radif-ru/ai_multi_agent_system/actions/workflows/test.yml)

**Локальная мульти-агентная система** на self-hosted LLM через [Ollama](https://ollama.com). Принимает задачу от пользователя и **выполняет цикл `thought → action → observation`** до финального ответа: думает, выбирает инструмент, наблюдает результат, повторяет. Ответ модели в цикле — строго JSON (`{"thought", "action", "args"}` либо `{"final_answer"}`).

Ключевые свойства:

- **Мульти-канальность.** Один и тот же доменный контракт `core.handle_user_task(text, user_id, chat_id)` обслуживает три канала: **Telegram** ([aiogram 3](https://docs.aiogram.dev/), long polling), **консоль** (REPL) и **MAX** ([dev.max.ru/docs-api](https://dev.max.ru/docs-api), long polling). Адаптеры тонкие — добавление нового канала не трогает `core` / `agents` / `tools` / `memory`.
- **Мульти-моделность.** Под разные задачи — разные локальные модели, а не одна: LLM для агентного цикла/рассуждений (`OLLAMA_DEFAULT_MODEL`, default `qwen3.5:4b`, переключается per-user через `/model`), embedding-модель для семантической памяти (`EMBEDDING_MODEL`, default `nomic-embed-text`), vision-модель для описания изображений (`VISION_MODEL`, default `gemma3:4b`, см. [`_docs/vision-models.md`](./_docs/vision-models.md)) и `faster-whisper` для распознавания речи.
- **Мульти-агентность.** Роли Planner / Executor / Critic с режимами рефлексии `OFF | NORMAL | DEEP` (`AGENT_REFLECTION_MODE`, default `OFF` — поведение MVP), graceful degradation при сбоях, переключение per-user командой `/mode`. Подробнее — [`_docs/multi-agent.md`](./_docs/multi-agent.md).
- **Гибрид LLM + инструменты.** Детерминированные и фактические операции агент делегирует специализированным tools, а не «придумывает»: точная арифметика (`calculator`), OCR текста с изображений (Tesseract — `ocr_image` / `read_document`), погода (`weather` → wttr.in), веб-поиск и HTTP (`web_search` / `http_request`), семантический поиск по памяти (`memory_search`). LLM отвечает за рассуждения и выбор инструмента; для изображений OCR (точная транскрипция текста) и vision-модель (описание сцены) дополняют друг друга.

Стек: [`ollama`](https://ollama.com) (LLM + embeddings + vision) + [`aiogram 3`](https://docs.aiogram.dev/) + [`httpx`](https://www.python-httpx.org/) (MAX-клиент) + [`sqlite-vec`](https://github.com/asg017/sqlite-vec) (долгосрочная семантическая память) + `pydantic-settings` + `pytest`. Всё локально — **без облачных LLM-API**.

## Возможности

Реализовано в спринтах 01 (MVP Agent), 02 (Память и файловые входы), 03 (Баги и консольный режим), 04 (Событийная модель и модуль Users), 05 (Безопасность и OCR-рефакторинг), 06 (Надёжность диалога и observability), 07 (Multi-agent: Planner + Critic), 08 (Hardening и зачистка) и 09 (MAX-адаптер). Индекс спринтов — [`_board/plan.md`](./_board/plan.md). Фактическое состояние кода — [`_docs/current-state.md`](./_docs/current-state.md).

- **Агентный цикл** `thought → action → observation` со строгим JSON-форматом, лимитом `AGENT_MAX_STEPS` и лимитом размера output’а — [`app/agents/executor.py`](./app/agents/executor.py), [`app/agents/protocol.py`](./app/agents/protocol.py).
- **Multi-agent** (Planner + Executor + Critic) с режимами `OFF | NORMAL | DEEP` (`AGENT_REFLECTION_MODE`, `AGENT_REFLECTION_MAX_ITERATIONS`), graceful degradation при ошибках Planner/Critic, команда `/mode` для per-user override — [`app/agents/planner.py`](./app/agents/planner.py), [`app/agents/critic.py`](./app/agents/critic.py), [`app/core/orchestrator.py`](./app/core/orchestrator.py); подробнее в [`_docs/multi-agent.md`](./_docs/multi-agent.md).
- **Локальные LLM под разные задачи** через Ollama: `qwen3.5:4b` (по умолчанию для агентного цикла/чата), `nomic-embed-text` (эмбеддинги для семантической памяти), `gemma3:4b` (vision-описание изображений, см. `_docs/vision-models.md`); активная чат-модель переключается per-user (`/model`). Клиент с `chat` и `embed` — [`app/services/llm.py`](./app/services/llm.py).
- **Tools (инструменты)** — агент делегирует им то, что нельзя «придумывать»; сгруппированы по назначению — [`app/tools/`](./app/tools), подробнее [`_docs/tools.md`](./_docs/tools.md):
  - *точные вычисления*: `calculator` (детерминированная арифметика вместо галлюцинаций);
  - *работа с файлами и изображениями*: `read_file`, `read_document` (PDF/TXT/MD + OCR через Tesseract), `ocr_image` (точная транскрипция текста с картинок), `describe_image` (описание сцены vision-моделью);
  - *внешние данные*: `web_search` (DuckDuckGo `ddgs`), `http_request`, `weather` (wttr.in с фолбэком на веб-поиск);
  - *память и навыки*: `memory_search` (семантический поиск по архиву), `load_skill`.
- **Telegram-интерфейс** на aiogram 3 (long polling), команды `/start`, `/help`, `/new`, `/reset`, `/models`, `/model`, `/prompt`, `/search_engines`, `/search_engine`, `/mode` + обработчик произвольного текста и файлов — [`app/adapters/telegram/handlers/`](./app/adapters/telegram/handlers).
- **Консольный адаптер** — REPL-цикл с теми же командами без Telegram — [`app/adapters/console/adapter.py`](./app/adapters/console/adapter.py), точка входа [`app/console_main.py`](./app/console_main.py); см. [`_docs/console-adapter.md`](./_docs/console-adapter.md).
- **MAX-адаптер** ([dev.max.ru/docs-api](https://dev.max.ru/docs-api)) — канал `channel="max"` поверх той же доменной модели: тонкий async-клиент `MaxClient` на `httpx` (`get_me` / `get_updates` long polling / `send_message`, авторизация заголовком `Authorization: <token>`, токен маскируется в логах), текст/команды/вложения (документ/фото/голос) через тот же конвейер и общий `CommandRegistry` — [`app/adapters/max/`](./app/adapters/max), точка входа [`app/max_main.py`](./app/max_main.py).
- **Файловые входы**: документы (PDF/TXT/MD), голосовые сообщения (Voice/Audio), фотографии (Photo) — [`app/adapters/telegram/files.py`](./app/adapters/telegram/files.py), [`app/services/transcribe.py`](./app/services/transcribe.py), [`app/services/vision.py`](./app/services/vision.py).
- **Краткосрочная память** per-user (in-memory FIFO + in-session суммаризация + полный лог сессии + контекст файлов для reply) — [`app/services/conversation.py`](./app/services/conversation.py), [`app/services/summarizer.py`](./app/services/summarizer.py).
- **Долгосрочная семантическая память** на `sqlite-vec`: `/new` суммирует сессию, режет на чанки, пишет с embedding'ом в `data/memory.db`; поиск через `memory_search` — [`app/services/memory.py`](./app/services/memory.py), [`app/services/archiver.py`](./app/services/archiver.py).
- **Авто-подгрузка архива** при старте новой сессии через `SemanticMemory.search` — [`app/core/orchestrator.py`](./app/core/orchestrator.py).
- **Skills** из [`app/skills/`](./app/skills): markdown с `Description:` в первой строке или YAML frontmatter; описания инжектятся в системный промпт, полное тело — через tool `load_skill` — [`app/services/skills.py`](./app/services/skills.py).
- **Пользователи и событийная шина**: модуль Users с персистентным SQLite-`UserRepository` (таблица `users` в `data/memory.db`, стабильный `user.id` между рестартами) + `EventBus` для развязки компонентов (события `UserCreated`, `MessageReceived`, `ResponseGenerated`, `ConversationArchived`) — [`app/users/`](./app/users), [`app/core/events.py`](./app/core/events.py).
- **Безопасность**: `InputSanitizer` (prompt injection), `FileIdMapper` (маскировка путей), `ResponseSanitizer` (фильтрация системной информации), allowlist для опасных tools в режиме «secure by default» (пустой allowlist = запрет, явное разрешение через `.env`) — [`app/security/`](./app/security).
- **Prompts** (`app/prompts/`): системный промпт агента и промпт суммаризации в markdown — [`app/services/prompts.py`](./app/services/prompts.py).
- **Настройки на пользователя** (выбранная модель, промпт) — [`app/services/model_registry.py`](./app/services/model_registry.py).
- **Логирование** через `TimedRotatingFileHandler` (ежедневная ротация, хранение ~14 дней) + middleware на каждый update; структурные JSON-логи со сквозным `trace_id` и опциональный error tracking в self-hosted GlitchTip (`SENTRY_DSN`) — [`app/core/logging_config.py`](./app/core/logging_config.py), [`app/observability/`](./app/observability), [`docker-compose.observability.yml`](./docker-compose.observability.yml). Подробнее — [`_docs/observability.md`](./_docs/observability.md).
- **Журнал диалога** (`dialog_journal` в `data/memory.db`, append-only) и фоновое восстановление незаархивированных сессий при старте — [`app/services/dialog_journal.py`](./app/services/dialog_journal.py), [`app/services/journal_recovery.py`](./app/services/journal_recovery.py); раздел `_docs/memory.md` §4.
- **CI** на GitHub Actions: `pytest -q` + `flake8` на push/PR — [`.github/workflows/test.yml`](./.github/workflows/test.yml).
- **Сборка приложения** (DI, polling, graceful shutdown) — [`app/main.py`](./app/main.py), точка входа [`app/__main__.py`](./app/__main__.py).
- **Unit-тесты** через моки ([`tests/`](./tests)): без реального Telegram / Ollama / сети; `sqlite-vec` — на `tmp_path`.

## Требования

- **Python** 3.14+.
- **Ollama** (`https://ollama.com`) с предзагруженными моделями `qwen3.5:4b`, `nomic-embed-text` и `gemma3:4b` (или другая vision-модель, см. `_docs/vision-models.md`).
- **Telegram bot token** от [@BotFather](https://t.me/BotFather) — для Telegram-канала.
- **MAX bot token** (`MAX_BOT_TOKEN`) — для MAX-канала; получается на [business.max.ru](https://business.max.ru/self) (Чат-боты → Интеграция → Получить токен). Опционален: при пустом значении MAX-канал не запускается.
- **tesseract-ocr** (опционально, для OCR в PDF): `sudo apt-get install tesseract-ocr tesseract-ocr-rus`
- ОС: Linux / WSL2 / macOS. Windows нативно — не приоритет.

## Установка

```bash
git clone <repo-url>
cd ai-multi-agent-system

python -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

## Настройка

1. Скопировать шаблон конфигурации и отредактировать секреты:

   ```bash
   cp .env.example .env
   # вписать TELEGRAM_BOT_TOKEN, при необходимости поменять модели/пути
   ```

2. Загрузить модели в Ollama:

   ```bash
   ollama pull qwen3.5:4b
   ollama pull nomic-embed-text
   ollama pull gemma3:4b
   ollama list   # убедиться, что все модели доступны
   ```

3. Полный список переменных окружения — в `_docs/stack.md` §9 и в самом `.env.example` (поля прокомментированы). Важно: для обработки больших файлов рекомендуется настроить `AGENT_MAX_CONTEXT_CHARS` (default 8000) для автоматической суммаризации контекста, чтобы LLM всегда могла ответить.

## Запуск

**Telegram-бот:**

```bash
ollama serve & .venv/bin/python -m app
```

**MAX-бот:**

```bash
ollama serve & .venv/bin/python -m app.max_main
```

Требует `MAX_BOT_TOKEN` в `.env`; при пустом токене канал не стартует. Каналы независимы: Telegram и MAX запускаются отдельными процессами.

**Консольный режим:**

```bash
ollama serve & .venv/bin/python -m app.console_main
```

Консольный режим — REPL-цикл с теми же командами (`/start`, `/help`, `/new`, `/reset`, `/models`, `/model`, `/prompt`, `/exit`), но без Telegram. См. `_docs/console-adapter.md`.

## Команды бота

| Команда            | Параметры       | Что делает                                                               |
|--------------------|-----------------|--------------------------------------------------------------------------|
| `/start`           | —               | Приветствие, краткая инструкция, список команд.                          |
| `/help`            | —               | Подробная справка.                                                       |
| `/new`             | —               | Архивирует текущую сессию (саммари → чанки → `sqlite-vec`), открывает новую. |
| `/reset`           | —               | Очищает текущую in-memory историю и per-user настройки. Архив **не трогает**. |
| `/models`          | —               | Список `OLLAMA_AVAILABLE_MODELS` с пометкой активной.                    |
| `/model <name>`    | имя модели      | Переключить активную LLM для пользователя.                               |
| `/prompt [<text>]` | текст \| пусто  | Задать системный промпт; без аргумента — сброс к default из `app/prompts/`. |
| `/search_engines`  | —               | Список доступных поисковиков с пометкой активного.                       |
| `/search_engine <name>` | имя        | Переключить активный поисковик для пользователя.                         |
| `/mode [off\|normal\|deep]` | режим \| пусто | Показать или переключить режим рефлексии multi-agent (per-user).         |
| *произвольный текст* | —             | Запустить агентный цикл с этой задачей; вернуть финальный ответ.         |

Подробное поведение каждой команды — в `_docs/commands.md`.

## Структура проекта (целевая)

```
ai-multi-agent-system/
├── _docs/        # проектная документация (см. _docs/README.md)
├── _board/       # доска задач: спринты + процесс
├── .agents/      # промпты и скиллы для AI-ассистента разработки (не runtime бота)
├── app/skills/      # markdown-скиллы (SKILL.md в каждой подпапке)
├── app/prompts/     # системные промпты в markdown
├── app/          # код приложения (агент, tools, adapters: telegram/console/max)
├── tests/        # unit-тесты, зеркалят app/
├── data/         # runtime-данные: SQLite с sqlite-vec (в .gitignore)
└── logs/         # файлы логов (в .gitignore)
```

Полное дерево с пояснениями — `_docs/project-structure.md`.

## Тесты

```bash
pytest -q
```

Покрытие (если установлен `pytest-cov`):

```bash
pytest --cov=app --cov-report=term-missing
```

Тесты не делают сетевых вызовов — `aiogram.Bot`, `Message`, `ollama.AsyncClient`, `sqlite-vec` мокаются (см. `_docs/testing.md`). Регрессионные тесты для длительных операций (например, `Archiver.archive`) маркируются маркером `slow` и могут быть пропущены в CI.

## Документация

- 📘 [`_docs/README.md`](./_docs/README.md) — индекс проектной документации.
- 🏗️ [`_docs/architecture.md`](./_docs/architecture.md) — компоненты, агентный цикл, RAG, расширяемость.
- 🔁 [`_docs/agent-loop.md`](./_docs/agent-loop.md) — формат JSON ответа, шаги цикла, лимиты.
- 🤝 [`_docs/multi-agent.md`](./_docs/multi-agent.md) — Planner + Executor + Critic, режимы рефлексии, fallback'ы, команда `/mode`.
- 🧠 [`_docs/memory.md`](./_docs/memory.md) — краткосрочная и долгосрочная память, контекст файлов.
- 🧰 [`_docs/tools.md`](./_docs/tools.md) — реестр инструментов и контракт нового tool.
- 🪄 [`_docs/skills.md`](./_docs/skills.md) — формат `app/skills/<name>/SKILL.md`.
- 💬 [`_docs/commands.md`](./_docs/commands.md) — команды бота.
- 🛠️ [`_docs/console-adapter.md`](./_docs/console-adapter.md) — консольный режим (REPL-цикл, запуск).
- 🛠️ [`_docs/instructions.md`](./_docs/instructions.md) — правила разработки (включая обязательные тесты перед коммитом).
- 🧪 [`_docs/testing.md`](./_docs/testing.md) — стратегия и категории тестов, моки, покрытие.
- 🔭 [`_docs/observability.md`](./_docs/observability.md) — структурные JSON-логи, `trace_id`, маскирование секретов, error tracking (GlitchTip).
- 📋 [`_board/README.md`](./_board/README.md) — процесс спринтов и задач.
- 📌 [`_docs/current-state.md`](./_docs/current-state.md) — фактическое состояние кода (читать перед правками).
- 🗺️ [`_docs/roadmap.md`](./_docs/roadmap.md) — этапы развития (capability graph, внешние онлайн-LLM, web-адаптер, MAX-webhook и др.).
- 🤖 [`.agents/README.md`](./.agents/README.md) — переиспользуемые промпты и скиллы для **AI-ассистента разработки**; здесь же разделение: `app/skills/` — runtime-скиллы бота, `.agents/skills/` — дисциплины ассистента.

## Ограничения и принципы

- Только **локальная LLM** через Ollama, никаких облачных API.
- Только **long polling** для всех каналов (Telegram и MAX), без webhook (см. `_docs/architecture.md` §2). MAX-документация рекомендует webhook для production — это вынесено в `_docs/roadmap.md`.
- **In-memory** история текущей сессии, **долгосрочная** память — только саммари (не сырые сообщения), для приватности.
- Поддерживаются файловые входы: документы (PDF/TXT/MD), голосовые сообщения (Voice/Audio), фотографии (Photo) — через `faster-whisper` (опционально) и Ollama vision API (опционально).
- Документация и сообщения коммитов ведутся **на русском**, технические идентификаторы — латиницей.

## История спринтов

Полный индекс и история спринтов — в [`_board/plan.md`](./_board/plan.md). Планируемые этапы (capability graph, внешние онлайн-LLM, web-адаптер, MAX-webhook и др.) — в [`_docs/roadmap.md`](./_docs/roadmap.md).
