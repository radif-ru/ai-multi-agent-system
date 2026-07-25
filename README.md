# ai-multi-agent-system

[![tests](https://github.com/radif-ru/ai-multi-agent-system/actions/workflows/test.yml/badge.svg)](https://github.com/radif-ru/ai-multi-agent-system/actions/workflows/test.yml)
[![coverage 88%](https://img.shields.io/badge/coverage-88%25-brightgreen.svg)](https://github.com/radif-ru/ai-multi-agent-system/actions/workflows/test.yml)
[![flake8](https://img.shields.io/badge/flake8-passing-brightgreen.svg)](https://github.com/radif-ru/ai-multi-agent-system/actions/workflows/test.yml)
[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/downloads/)
[![Ollama](https://img.shields.io/badge/LLM-Ollama-black.svg)](https://ollama.com)
[![sqlite-vec](https://img.shields.io/badge/vectors-sqlite--vec-blue.svg)](https://github.com/asg017/sqlite-vec)
[![aiogram 3](https://img.shields.io/badge/Telegram-aiogram%203-26A5E4.svg)](https://docs.aiogram.dev/)
[![APScheduler](https://img.shields.io/badge/scheduler-APScheduler-red.svg)](https://apscheduler.readthedocs.io/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![last commit](https://img.shields.io/github/last-commit/radif-ru/ai-multi-agent-system)](https://github.com/radif-ru/ai-multi-agent-system/commits)
[![repo size](https://img.shields.io/github/repo-size/radif-ru/ai-multi-agent-system)](https://github.com/radif-ru/ai-multi-agent-system)
[![issues](https://img.shields.io/github/issues/radif-ru/ai-multi-agent-system)](https://github.com/radif-ru/ai-multi-agent-system/issues)

**Локальная мульти-агентная система** на self-hosted LLM через [Ollama](https://ollama.com). Принимает задачу от пользователя и **выполняет цикл `thought → action → observation`** до финального ответа: думает, выбирает инструмент, наблюдает результат, повторяет. Ответ модели в цикле — строго JSON (`{"thought", "action", "args"}` либо `{"final_answer"}`).

Ключевые свойства:

- **Мульти-канальность.** Один и тот же доменный контракт `core.handle_user_task(text, user_id, chat_id)` обслуживает три канала: **Telegram** ([aiogram 3](https://docs.aiogram.dev/), long polling), **консоль** (REPL) и **MAX** ([dev.max.ru/docs-api](https://dev.max.ru/docs-api), long polling). Адаптеры тонкие — добавление нового канала не трогает `core` / `agents` / `tools` / `memory`.
- **Мульти-модельность.** Под разные задачи — разные локальные модели, а не одна: LLM для агентного цикла/рассуждений (`OLLAMA_DEFAULT_MODEL`, default `qwen3.5:4b`, переключается per-user через `/model`), embedding-модель для семантической памяти (`EMBEDDING_MODEL`, default `nomic-embed-text`), vision-модель для описания изображений (`VISION_MODEL`, default `gemma3:4b`, см. [`_docs/vision-models.md`](./_docs/vision-models.md)) и `faster-whisper` для распознавания речи.
- **Мультимодальность.** Принимает не только текст, но и файлы разных модальностей: документы (PDF/TXT/MD, с OCR через Tesseract), голосовые сообщения (распознавание `faster-whisper`) и изображения (vision-модель + OCR). Всё обрабатывается единым агентным циклом.
- **Мульти-агентность.** Роли Planner / Executor / Critic с режимами рефлексии `OFF | NORMAL | DEEP` (`AGENT_REFLECTION_MODE`, default `OFF` — поведение MVP), graceful degradation при сбоях, переключение per-user командой `/mode`. Подробнее — [`_docs/multi-agent.md`](./_docs/multi-agent.md).
- **Гибрид LLM + инструменты.** Детерминированные и фактические операции агент делегирует специализированным tools, а не «придумывает»: точная арифметика (`calculator`), OCR текста с изображений (Tesseract — `ocr_image` / `read_document`), погода (`weather` → wttr.in), веб-поиск и HTTP (`web_search` / `http_request`), семантический поиск по памяти (`memory_search`), чтение почты (`email_list` / `email_read`) и Яндекс.Диска (`disk_list` / `disk_download`), запуск скриптов скиллов (`run_skill_script`). LLM отвечает за рассуждения и выбор инструмента; для изображений OCR (точная транскрипция текста) и vision-модель (описание сцены) дополняют друг друга.

Стек: [`ollama`](https://ollama.com) (LLM + embeddings + vision) + [`aiogram 3`](https://docs.aiogram.dev/) + [`httpx`](https://www.python-httpx.org/) (MAX-клиент) + [`sqlite-vec`](https://github.com/asg017/sqlite-vec) (долгосрочная семантическая память) + [`APScheduler`](https://apscheduler.readthedocs.io/) (cron-планировщик задач) + `pydantic-settings` + `pytest`. Всё локально — **без облачных LLM-API**.

## Оглавление

- [Возможности](#возможности)
- [Требования](#требования)
- [Целевая система и тюнинг под неё](#целевая-система-и-тюнинг-под-неё)
- [Установка](#установка)
- [Настройка](#настройка)
- [Запуск](#запуск)
- [Команды бота](#команды-бота)
- [Структура проекта](#структура-проекта-целевая)
- [Тесты](#тесты)
- [Graphify](#graphify)
- [Инженерная дисциплина и процессы](#инженерная-дисциплина-и-процессы)
- [Документация](#документация)
- [Ограничения и принципы](#ограничения-и-принципы)
- [История спринтов](#история-спринтов)

## Возможности

Реализовано в спринтах 01 (MVP Agent), 02 (Память и файловые входы), 03 (Баги и консольный режим), 04 (Событийная модель и модуль Users), 05 (Безопасность и OCR-рефакторинг), 06 (Надёжность диалога и observability), 07 (Multi-agent: Planner + Critic), 08 (Hardening и зачистка), 09 (MAX-адаптер), 10 (Аудит качества и устранение техдолга), 11 (Производительность и эффективность LLM), 12 (Качество, безопасность и процессы), 13 (Интеграции почты и диска, скиллы со скриптами) и 14 (Планировщик задач, логи в GlitchTip, качество RAG). Индекс спринтов — [`_board/plan.md`](./_board/plan.md). Фактическое состояние кода — [`_docs/current-state.md`](./_docs/current-state.md).

### Агентный цикл и Multi-agent

- **Агентный цикл** `thought → action → observation` со строгим JSON-форматом, лимитом `AGENT_MAX_STEPS` и лимитом размера output'а — [`app/agents/executor.py`](./app/agents/executor.py), [`app/agents/protocol.py`](./app/agents/protocol.py).
- **Multi-agent** (Planner + Executor + Critic) с режимами `OFF | NORMAL | DEEP` (`AGENT_REFLECTION_MODE`, `AGENT_REFLECTION_MAX_ITERATIONS`), graceful degradation при ошибках Planner/Critic, команда `/mode` для per-user override — [`app/agents/planner.py`](./app/agents/planner.py), [`app/agents/critic.py`](./app/agents/critic.py), [`app/core/orchestrator.py`](./app/core/orchestrator.py); подробнее в [`_docs/multi-agent.md`](./_docs/multi-agent.md).
- **Локальные LLM под разные задачи** через Ollama: `qwen3.5:4b` (по умолчанию для агентного цикла/чата), `nomic-embed-text` (эмбеддинги для семантической памяти), `gemma3:4b` (vision-описание изображений, см. `_docs/vision-models.md`); активная чат-модель переключается per-user (`/model`). Клиент с `chat` и `embed` — [`app/services/llm.py`](./app/services/llm.py).

### Инструменты (Tools)

Агент делегирует им то, что нельзя «придумывать»; сгруппированы по назначению — [`app/tools/`](./app/tools), подробнее [`_docs/tools.md`](./_docs/tools.md):

- *точные вычисления*: `calculator` (детерминированная арифметика вместо галлюцинаций);
- *работа с файлами и изображениями*: `read_file`, `read_document` (PDF/TXT/MD + OCR через Tesseract), `ocr_image` (точная транскрипция текста с картинок), `describe_image` (описание сцены vision-моделью);
- *внешние данные*: `web_search` (DuckDuckGo `ddgs`), `http_request`, `weather` (wttr.in с фолбэком на веб-поиск);
- *почта и диск*: `email_list` / `email_read` (IMAP read-only, Яндекс + Gmail), `disk_list` / `disk_download` (Яндекс.Диск);
- *память и навыки*: `memory_search` (семантический поиск по архиву), `load_skill`, `run_skill_script` (sandbox-запуск скриптов скилла);
- *планировщик*: `schedule_task` / `list_scheduled_tasks` / `cancel_scheduled_task` (повторяющиеся cron-задачи из Telegram на естественном языке).

### Каналы

- **Telegram-интерфейс** на aiogram 3 (long polling), команды `/start`, `/help`, `/new`, `/reset`, `/models`, `/model`, `/prompt`, `/search_engines`, `/search_engine`, `/mode` + обработчик произвольного текста и файлов — [`app/adapters/telegram/handlers/`](./app/adapters/telegram/handlers).
- **Консольный адаптер** — REPL-цикл с теми же командами без Telegram — [`app/adapters/console/adapter.py`](./app/adapters/console/adapter.py), точка входа [`app/console_main.py`](./app/console_main.py); см. [`_docs/console-adapter.md`](./_docs/console-adapter.md).
- **MAX-адаптер** ([dev.max.ru/docs-api](https://dev.max.ru/docs-api)) — канал `channel="max"` поверх той же доменной модели: тонкий async-клиент `MaxClient` на `httpx` (`get_me` / `get_updates` long polling / `send_message`, авторизация заголовком `Authorization: <token>`, токен маскируется в логах), текст/команды/вложения (документ/фото/голос) через тот же конвейер и общий `CommandRegistry` — [`app/adapters/max/`](./app/adapters/max), точка входа [`app/max_main.py`](./app/max_main.py).
- **Файловые входы**: документы (PDF/TXT/MD), голосовые сообщения (Voice/Audio), фотографии (Photo) — [`app/adapters/telegram/files.py`](./app/adapters/telegram/files.py), [`app/services/transcribe.py`](./app/services/transcribe.py), [`app/services/vision.py`](./app/services/vision.py).

### Память

- **Краткосрочная память** per-user (in-memory FIFO + in-session суммаризация + полный лог сессии + контекст файлов для reply) — [`app/services/conversation.py`](./app/services/conversation.py), [`app/services/summarizer.py`](./app/services/summarizer.py).
- **Долгосрочная семантическая память** на `sqlite-vec`: `/new` суммирует сессию, режет на чанки, пишет с embedding'ом в `data/memory.db`; поиск через `memory_search`. Для качества RAG применяются task-префиксы `nomic-embed-text` (`search_document:` при индексации, `search_query:` при поиске — см. ADR-4) — [`app/services/memory.py`](./app/services/memory.py), [`app/services/archiver.py`](./app/services/archiver.py).
- **Авто-подгрузка архива** при старте новой сессии через `SemanticMemory.search` — [`app/core/orchestrator.py`](./app/core/orchestrator.py).
- **Журнал диалога** (`dialog_journal` в `data/memory.db`, append-only) и фоновое восстановление незаархивированных сессий при старте — [`app/services/dialog_journal.py`](./app/services/dialog_journal.py), [`app/services/journal_recovery.py`](./app/services/journal_recovery.py); раздел `_docs/memory.md` §4.

### Планировщик и навыки

- **Планировщик задач (cron)** — повторяющиеся задачи из Telegram на естественном языке («проверяй почту каждый день в 9:00»): [`APScheduler`](https://apscheduler.readthedocs.io/) в процессе бота, расписания персистятся в `data/memory.db` и переживают рестарт, результат приходит сообщением в Telegram; изоляция от живой сессии, лимит задач на пользователя, sanitize prompt — [`app/services/scheduler.py`](./app/services/scheduler.py), [`app/services/scheduler_runner.py`](./app/services/scheduler_runner.py), подробнее [`_docs/scheduler.md`](./_docs/scheduler.md).
- **Skills** из [`app/skills/`](./app/skills): markdown с `Description:` в первой строке или YAML frontmatter; описания инжектятся в системный промпт, полное тело — через tool `load_skill`; скиллы могут содержать детерминированные скрипты в `scripts/` (запуск через `run_skill_script`) — [`app/services/skills.py`](./app/services/skills.py), [`_docs/skills.md`](./_docs/skills.md).

### Пользователи и безопасность

- **Пользователи и событийная шина**: модуль Users с персистентным SQLite-`UserRepository` (таблица `users` в `data/memory.db`, стабильный `user.id` между рестартами) + `EventBus` для развязки компонентов (события `UserCreated`, `MessageReceived`, `ResponseGenerated`, `ConversationArchived`) — [`app/users/`](./app/users), [`app/core/events.py`](./app/core/events.py).
- **Безопасность** по контракту «sanitize на входе → bastion на выходе»: `InputSanitizer` (prompt injection) на входе всех адаптеров, `ResponseSanitizer` (маскировка системных путей/секретов) на выходе, `FileIdMapper` (маскировка путей в ответах), **per-user область видимости файлов** (в Telegram/MAX `read_file` ограничен каталогом пользователя `data/tmp/<user_id>`; консоль — флаг `CONSOLE_FILE_SCOPE`), allowlist для опасных tools в режиме «secure by default» (пустой allowlist = запрет, явное разрешение через `.env`) — [`app/security/`](./app/security), подробнее [`_docs/security.md`](./_docs/security.md).

### Инфраструктура

- **Prompts** (`app/prompts/`): системный промпт агента и промпт суммаризации в markdown — [`app/services/prompts.py`](./app/services/prompts.py).
- **Настройки на пользователя** (выбранная модель, промпт) — [`app/services/model_registry.py`](./app/services/model_registry.py).
- **Логирование** через `TimedRotatingFileHandler` (ежедневная ротация, хранение ~14 дней) + middleware на каждый update; структурные JSON-логи со сквозным `trace_id` и опциональный error tracking в self-hosted GlitchTip (`SENTRY_DSN`): ошибки → **Issues** (порог `SENTRY_EVENT_LEVEL`, default `ERROR`), логи `DEBUG+` → вкладка **Logs** (`SENTRY_LOG_LEVEL`, default `DEBUG` для dev; в prod — `INFO`), плюс performance-трассировки — [`app/core/logging_config.py`](./app/core/logging_config.py), [`app/observability/`](./app/observability), [`docker-compose.observability.yml`](./docker-compose.observability.yml). Подробнее — [`_docs/observability.md`](./_docs/observability.md).
- **CI** на GitHub Actions (push/PR) — шесть гейтов: `flake8`, синхронизация `Settings` ↔ `.env.example` (`check_env_sync`), синхронизация `_board/plan.md` ↔ файлов спринтов (`check_sprint_sync`), проверка относительных ссылок в markdown (`check_doc_links`), проверка формата и зеркал скиллов/промптов ассистента (`check_agents_sync`) и `pytest` с жёстким порогом покрытия (`--cov-fail-under=80`) — [`.github/workflows/test.yml`](./.github/workflows/test.yml), [`scripts/`](./scripts).
- **Сборка приложения** (DI, polling, graceful shutdown) — [`app/main.py`](./app/main.py), точка входа [`app/__main__.py`](./app/__main__.py).
- **Unit-тесты** через моки ([`tests/`](./tests)): без реального Telegram / Ollama / сети; `sqlite-vec` — на `tmp_path`.

## Требования

- **Python** 3.14+.
- **Ollama** (`https://ollama.com`) с предзагруженными моделями `qwen3.5:4b`, `nomic-embed-text` и `gemma3:4b` (или другая vision-модель, см. `_docs/vision-models.md`).
- **Telegram bot token** от [@BotFather](https://t.me/BotFather) — для Telegram-канала.
- **MAX bot token** (`MAX_BOT_TOKEN`) — для MAX-канала; получается на [business.max.ru](https://business.max.ru/self) (Чат-боты → Интеграция → Получить токен). Опционален: при пустом значении MAX-канал не запускается.
- **tesseract-ocr** (опционально, для OCR в PDF): `sudo apt-get install tesseract-ocr tesseract-ocr-rus`
- **Почта** (опционально): пароли приложений для IMAP — Яндекс (`YANDEX_MAIL_USER` + `YANDEX_MAIL_APP_PASSWORD`, [пароль приложения](https://id.yandex.ru/security/app-passwords)) и/или Gmail (`GMAIL_USER` + `GMAIL_APP_PASSWORD`, [пароль приложения](https://myaccount.google.com/apppasswords)). При пустых кредах почтовые tools возвращают подсказку.
- **Яндекс.Диск** (опционально): OAuth-токен (`YANDEX_DISK_TOKEN`) — создайте своё приложение на [oauth.yandex.ru](https://oauth.yandex.ru/) с правами `cloud_api:disk.read` и получите токен по [инструкции](https://yandex.ru/dev/disk/api/concepts/quickstart.html). При пустом токене disk-tools возвращают подсказку.
- ОС: Linux / WSL2 / macOS. Windows нативно — не приоритет.

## Целевая система и тюнинг под неё

Дефолты в `.env.example` (размер контекста, параллелизм, выбор моделей, `keep_alive`, бюджет VRAM) **подобраны под мощную локальную систему**, на которой ведётся разработка. Это отдельная машина под локальный ИИ: тяжёлые задачи (LLM, эмбеддинги, vision, дообучение) гоняются локально, без облака — данные не покидают устройство, нет внешних API-ключей и лимитов (подробнее о железе — [radif.ru/#hardware](https://radif.ru/#hardware)):

- **Ноутбук:** ASUS ROG Strix SCAR 18 — флагманская мобильная рабочая платформа (быстрая DDR5-память, NVMe SSD (PCIe 5.0 x4), производительное охлаждение).
- **GPU:** NVIDIA GeForce RTX 5090 Laptop — **24 ГБ GDDR7 VRAM**. Это ключевой ресурс: вся LLM-нагрузка (chat, эмбеддинги, vision) идёт через GPU, а 24 ГБ позволяют держать модель резидентной (`OLLAMA_KEEP_ALIVE=30m`), большой контекст (`OLLAMA_NUM_CTX=32768`) и параллельные сессии (`LLM_MAX_CONCURRENCY=2`).
- **CPU:** Intel Core Ultra 9 275HX (Arrow Lake-HX) — 24 ядра / 24 потока + интегрированный NPU (Intel AI Boost). Быстрый prefill контекста, параллельная транскрипция речи (`faster-whisper`) и OCR (Tesseract). *Примечание:* текущий стек гоняет LLM на GPU через Ollama; NPU — задел на будущие сценарии локального ускорения.
- **SSD:** Kingston FURY Renegade G5 4 ТБ (SFYR2S/4T0) — флагманский NVMe-накопитель формата M.2 с интерфейсом PCIe 5.0 x4 и архитектурой 3D TLC NAND. Рекордная производительность для ресурсоёмких приложений, игр и работы с большими объёмами данных.
- **Экран:** 18″ 2.5K WQXGA (2560×1600, 16:10), ROG Nebula HDR Mini-LED, 240 Гц, 1200 нит, 100% DCI-P3 — комфорт для долгой работы с кодом и точная цветопередача для vision-задач.
- **Порты:** 2× Thunderbolt 5 (USB-C), 3× USB 3.2 Gen 2 Type-A, HDMI 2.1, 2.5G LAN — в том числе для подключения внешних ускорителей.

Поэтому дефолты «щедрые»: большой `OLLAMA_NUM_CTX`, высокий порог суммаризации (`AGENT_MAX_CONTEXT_CHARS=90000`), крупные документы целиком в контексте (`MAX_DOCUMENT_CHARS=80000`), резидентная модель и бюджет VRAM 24 ГБ для предупреждений (`OLLAMA_VRAM_BUDGET_GB=24.0`).

### Если ваша система слабее

Уменьшите ключевые значения в `.env` и выберите модели полегче. Пример для системы с ~8 ГБ VRAM:

```dotenv
# Меньше контекст и параллелизм — экономия VRAM
OLLAMA_NUM_CTX=8192
LLM_MAX_CONCURRENCY=1
OLLAMA_KEEP_ALIVE=0           # выгружать модель сразу после ответа
OLLAMA_VRAM_BUDGET_GB=8       # порог предупреждения о тяжёлой модели в /model
AGENT_MAX_CONTEXT_CHARS=24000
MAX_DOCUMENT_CHARS=16000

# Модели полегче
OLLAMA_DEFAULT_MODEL=qwen3.5:0.8b
VISION_MODEL=moondream2        # лёгкая vision-модель (см. _docs/vision-models.md)
```

Ориентир: размер модели не должен превышать свободный VRAM. Команда `/models` показывает размеры моделей, а `/model <имя>` предупреждает о тяжёлых. На CPU-only Ollama работает, но медленно — берите самые маленькие модели и `OLLAMA_NUM_CTX` ≤ 4096.

## Установка

```bash
git clone https://github.com/radif-ru/ai-multi-agent-system.git
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

3. Полный список переменных окружения — в `_docs/stack.md` §9 и в самом `.env.example` (поля прокомментированы). Важно: для обработки больших файлов порог суммаризации контекста `AGENT_MAX_CONTEXT_CHARS` (default 90000) согласован с `OLLAMA_NUM_CTX=32768` и `MAX_DOCUMENT_CHARS=80000`, чтобы большой документ попадал в контекст без преждевременной суммаризации (см. `_docs/agent-loop.md` §4).

## Запуск

**Через `scripts/run.sh` (рекомендуется):**

Скрипт запускает бот в собственной группе процессов с `trap` на graceful shutdown — Ctrl+C или SIGTERM завершает всё дерево процессов (бот + ollama serve).

```bash
# Telegram-бот (по умолчанию)
./scripts/run.sh

# MAX-бот
CHANNEL=max ./scripts/run.sh

# Консольный режим
CHANNEL=console ./scripts/run.sh

# Без автоматического запуска Ollama (если уже запущен)
START_OLLAMA=false ./scripts/run.sh
```

**Прямой запуск:**

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

`pytest-cov` — обязательная зависимость: `pytest` всегда измеряет покрытие `app/` и **падает, если оно ниже порога** `--cov-fail-under=80` (задан в `pyproject.toml`; тот же гейт работает в CI). Подробнее — [`_docs/testing.md`](./_docs/testing.md).

```bash
pytest -q                                # тесты + гейт покрытия
pytest --cov-report=term-missing         # детальный отчёт по непокрытым строкам
```

Тесты не делают сетевых вызовов — `aiogram.Bot`, `Message`, `ollama.AsyncClient`, `sqlite-vec` мокаются (см. `_docs/testing.md`). Регрессионные тесты для длительных операций (например, `Archiver.archive`) маркируются маркером `slow` и могут быть пропущены в CI.

## Graphify

[Graphify](https://github.com/safishamsi/graphify) — инструмент для построения графа кода. Используется для навигации по зависимостям и структуре проекта.

### Установка

```bash
uv tool install graphify          # установить graphify
graphify hook install             # установить git-хук (авто-обновление графа при коммите)
```

### Команды

| Команда | Описание |
|---------|----------|
| `graphify update` | Ручное обновление графа (после рефакторинга, добавления/удаления модулей) |
| `graphify hook install` | Установить git-хук для авто-обновления при коммите |
| `graphify hook uninstall` | Удалить git-хук |

Граф генерируется в `graphify-out/` (в `.gitignore`, не коммитится). Исключения — в `.graphifyignore` (code-only graph: документы, медиа, конфиги исключены). Подробности — `_docs/stack.md` §14.

## Инженерная дисциплина и процессы

Проект ведётся как инженерный продукт: правила разработки, документация и дисциплины AI-ассистента зафиксированы и проверяются автоматически — это снижает регрессии и делает вклад любого агента/человека предсказуемым.

- **Правила и процесс спринтов** — [`_board/`](./_board): [`process.md`](./_board/process.md) (жизненный цикл спринта/задачи, ветки `feature/<NN>-...`, DoD, целесообразный порядок задач, маршрутизация находок), [`plan.md`](./_board/plan.md) (индекс спринтов), файлы спринтов в [`_board/sprints/`](./_board/sprints). Правила разработки (git, стиль, async, ошибки, секреты, тесты, документация) — [`_docs/instructions.md`](./_docs/instructions.md).
- **Проектная документация** — [`_docs/`](./_docs): архитектура, агентный цикл, память, tools, безопасность, observability и др. (индекс — [`_docs/README.md`](./_docs/README.md)).
- **Скиллы и промпты для AI-ассистента разработки** — [`.agents/`](./.agents): переиспользуемые промпты ([`.agents/prompts/`](./.agents/prompts)) и скиллы-дисциплины ([`.agents/skills/`](./.agents/skills)) — архитектура, async, тесты, обработка ошибок, защита от prompt injection, документация, git, автоматизация, отладка, **подготовка и ревью pull request (MR)**.
- **Скрипты в скиллах** — детерминированная часть скилла выполняется кодом, а не ИИ: у бота — `app/skills/<name>/scripts/` через sandbox-tool `run_skill_script` ([`_docs/skills.md`](./_docs/skills.md)), у ассистента — `.agents/skills/<name>/scripts/` (например, [`preflight.sh`](./.agents/skills/git-discipline/scripts/preflight.sh) — весь ритуал проверок перед коммитом одной командой). Так автоматизация остаётся надёжной и воспроизводимой, а токены LLM тратятся на суждения, а не на механику.
- **Единые правила для всех AI-инструментов** — единственный источник истины [`AGENTS.md`](./AGENTS.md) зеркалится относительными симлинками ([`CLAUDE.md`](./CLAUDE.md), [`GEMINI.md`](./GEMINI.md), [`QWEN.md`](./QWEN.md), `.github/copilot-instructions.md`); Cursor (`.cursor/rules/`) и Windsurf/Devin (`.devin/rules/`) — через файл-указатель; скиллы — в `.claude/skills/`. Подробнее — [`.agents/README.md`](./.agents/README.md).
- **Автоматический контроль качества (в CI, без ИИ)** — `flake8`, `pytest` с порогом покрытия `--cov-fail-under=80` и скрипты-гейты [`scripts/`](./scripts): `check_env_sync` (нет конфигов мимо `.env`), `check_doc_links` (нет битых/абсолютных ссылок в markdown), `check_sprint_sync` (`plan.md` не расходится с файлами спринтов), `check_agents_sync` (формат и зеркала скиллов/промптов ассистента, живёт в `.agents/skills/skill-authoring/scripts/`).
- **Безопасность по умолчанию** — sanitize на входе / bastion на выходе, per-user область видимости файлов, allowlist опасных tools, маскирование секретов в логах — [`_docs/security.md`](./_docs/security.md).

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
- ⏰ [`_docs/scheduler.md`](./_docs/scheduler.md) — планировщик регулярных задач (APScheduler, cron, доставка в Telegram).
- 🔐 [`_docs/security.md`](./_docs/security.md) — sanitize/bastion, per-user область видимости файлов, allowlist tools, маскирование секретов.
- 🗂️ [`_board/README.md`](./_board/README.md) — процесс спринтов и задач.
- 📌 [`_docs/current-state.md`](./_docs/current-state.md) — фактическое состояние кода (читать перед правками).
- 🗺️ [`_docs/roadmap.md`](./_docs/roadmap.md) — этапы развития (capability graph, внешние онлайн-LLM, web-адаптер, MAX-webhook и др.).
- 📋 [`_docs/decisions.md`](./_docs/decisions.md) — журнал архитектурных решений (ADR): контекст, варианты, решение, последствия.
- 🤖 [`.agents/README.md`](./.agents/README.md) — переиспользуемые промпты и скиллы для **AI-ассистента разработки**; здесь же разделение: `app/skills/` — runtime-скиллы бота, `.agents/skills/` — дисциплины ассистента.

## Ограничения и принципы

- Только **локальная LLM** через Ollama, никаких облачных API.
- Только **long polling** для всех каналов (Telegram и MAX), без webhook (см. `_docs/architecture.md` §2). MAX-документация рекомендует webhook для production — это вынесено в `_docs/roadmap.md`.
- **In-memory** история текущей сессии, **долгосрочная** память — только саммари (не сырые сообщения), для приватности.
- Поддерживаются файловые входы: документы (PDF/TXT/MD), голосовые сообщения (Voice/Audio), фотографии (Photo) — через `faster-whisper` (опционально) и Ollama vision API (опционально).
- Документация и сообщения коммитов ведутся **на русском**, технические идентификаторы — латиницей.

## История спринтов

Полный индекс и история спринтов — в [`_board/plan.md`](./_board/plan.md). Планируемые этапы (capability graph, внешние онлайн-LLM, web-адаптер, MAX-webhook и др.) — в [`_docs/roadmap.md`](./_docs/roadmap.md).
