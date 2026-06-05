# Спринт 09. MAX-адаптер

- **Источник:** ТЗ пользователя (запрос от 2026-06-04); `_docs/roadmap.md` Этап 6 «MAX-адаптер»; `_docs/architecture.md` §8.4 «Новый адаптер (console, web, MAX)».
- **Ветка:** `feature/09-max-adapter` (от `main`; см. `_board/process.md` §2 п.2).
- **Открыт:** 2026-06-04
- **Закрыт:** —
- **Статус:** Active

## 1. Цель спринта

Подключить мессенджер **MAX** (`dev.max.ru/docs-api`) как новый канал поверх существующей доменной модели — без изменений в `core` / `agents` / `tools` / `memory`. Адаптер тонкий: принимает текст, команды и файловые вложения, вызывает единый контракт `core.handle_user_task(text, user_id, chat_id)` и отдаёт ответ обратно в MAX. Это реализует давно запланированный Этап 6 roadmap и доказывает расширяемость, заложенную в `architecture.md` §8.4 (NFR-11).

Спринт сознательно начинается с **актуализации документации по уже закрытым спринтам** (README устарел в позиционировании, см. Этап 1), а завершается **повторной актуализацией** `README.md`, `_docs/roadmap.md` и `_docs/current-state.md` уже под MAX (Этап 5) — этого явно требует ТЗ: после выполнения основных задач документация должна отражать новый канал.

## 2. Скоуп и non-goals

### В скоупе

- **Документация (до интеграции):** актуализация `README.md` и связанных документов под фактическое состояние после спринтов 01–08 (мульти-канальность Telegram + console, реализованный multi-agent, опечатки в ссылках).
- **Конфиг и канал:** поля `MAX_*` в `Settings`, поддержка `channel="max"` в `app/users/` и событиях (`User.channel` — строковая колонка, миграция БД не нужна).
- **Транспорт:** собственный async-клиент `MaxClient` на `httpx` (без сторонних SDK) — `get_me`, `get_updates` (long polling), `send_message`, скачивание вложений; `Authorization: <token>`-заголовок; маскирование токена в логах.
- **Приёмник:** polling-цикл и точка входа `app/max_main.py`, по образцу `app/main.py` (`_build_components` + `_wire_telegram` + graceful shutdown).
- **Текст и команды:** обработка произвольного текста через `core.handle_user_task`; команды через общий `CommandRegistry` / `CommandContext` (`channel="max"`).
- **Файловые входы:** документы (PDF/TXT/MD), фотографии и голосовые — через существующий конвейер (`read_document` / `Vision` / `Transcriber`) с изоляцией файлов по пользователю в `Settings.tmp_base_dir`.
- **Тесты:** unit на моках `httpx` (без сети), по образцу `tests/adapters/telegram/` и `tests/test_main.py`.
- **Документация (после интеграции):** `README.md`, `_docs/roadmap.md` (снять Этап 6), `_docs/current-state.md`, `_docs/architecture.md`, `_docs/project-structure.md`, `.env.example`.

### Вне скоупа (non-goals)

- **Webhook-режим для MAX** — остаётся в `_docs/roadmap.md` Этап 7 (MAX-документация рекомендует webhook для production, но MVP осознанно на long polling, как Telegram; см. CON-4).
- **Кросс-канальная унификация пользователя** (`external_id → internal_user_id` между Telegram и MAX) — `_docs/roadmap.md` Этап 5; здесь MAX-пользователь отдельный по ключу `(channel, external_id)`.
- **Стриминг ответа / индикация шагов** (roadmap Этапы 1–2), throttling (Этап 8).
- **Изменения в `core` / `agents` / `tools` / `memory`** — адаптер не трогает доменные слои.
- **Видео и геолокация** (roadmap Этап 15).
- Любые правки **закрытых** спринтов `_board/sprints/00..08` (архив, см. `process.md` §2 п.5).

## 3. Acceptance Criteria спринта

- [ ] `README.md` и связанные документы актуализированы под состояние после спринтов 01–08: проект описан как мульти-агентная система с адаптерами Telegram + console, исправлена опечатка ссылки `./pp/skills` → `./app/skills`, список возможностей/спринтов соответствует `_docs/current-state.md`.
- [ ] В `Settings` есть поля `MAX_*`; `.env.example` дополнен; `UserRepository.get_or_create("max", ...)` возвращает пользователя с `channel="max"`.
- [ ] `MaxClient` (на `httpx`, без сторонних SDK) реализует `get_me` / `get_updates` / `send_message` / скачивание вложений; токен не попадает в логи (через `mask_secrets`); внешние вызовы логируются как `external.call/ok/fail`.
- [ ] `app/max_main.py` собирается и запускает long polling; smoke `python -c "from app.max_main import main; print(main)"` проходит; graceful shutdown закрывает клиентов.
- [ ] Текстовое сообщение из MAX проходит `sanitize_user_input` → `core.handle_user_task` → ответ в MAX; длинный ответ режется под лимит; публикуются `MessageReceived` / `ResponseGenerated` с `channel="max"`.
- [ ] Команды (`/start`, `/help`, `/new`, `/reset`, `/models`, `/model`, `/prompt`, `/mode`, `/search_engines`, `/search_engine`) работают через общий `CommandRegistry`.
- [ ] Документ / фото / голосовое из MAX скачиваются с проверкой размера и изоляцией по `user_id`, маршрутизируются в существующий конвейер (`read_document` / `Vision` / `Transcriber`); при недоступности faster-whisper / vision — корректные fallback-сообщения.
- [ ] `README.md`, `_docs/roadmap.md` (Этап 6 снят), `_docs/current-state.md`, `_docs/architecture.md`, `_docs/project-structure.md` обновлены под MAX-адаптер; «битых» ссылок нет.
- [ ] `pytest -q` и `flake8 app tests` зелёные; для задач, меняющих код в `app/`, есть unit-тесты на новое поведение (моки `httpx`, без сети).
- [ ] Все задачи спринта — `Done`, сводная таблица актуальна.

## 4. Этап 1. Актуализация документации перед интеграцией

Привести `README.md` и связанные документы к фактическому состоянию после спринтов 01–08 (ТЗ: «README как будто устарел… это можно сделать сразу перед новым спринтом»). Этап чисто-документационный.

### Задача 1.1. Актуализировать README под мульти-канальность и спринты 01–08

- **Статус:** Done
- **Приоритет:** high
- **Объём:** S
- **Зависит от:** —
- **Связанные документы:** `README.md`, `_docs/current-state.md`, `_docs/console-adapter.md`, `_docs/multi-agent.md`.
- **Затрагиваемые файлы:** `README.md`.

#### Описание

README позиционирует проект как «Telegram-бот», хотя по факту это мульти-агентная система с **двумя** адаптерами (Telegram + console) и реализованным multi-agent (спринт 07). Технические дефолты (`qwen3.5:4b`, `nomic-embed-text`, `gemma3:4b`, режимы рефлексии) совпадают с `app/config.py` — их **не трогаем** (минимализм, AGENTS.md §3).

1. Поправить вводный абзац: проект — локальный AI-агент с адаптерами Telegram и console (не только Telegram-бот).
2. Снять формулировки «на будущее» там, где функционал уже реализован (multi-agent), не теряя список планов.
3. Исправить опечатку ссылки `./pp/skills` → `./app/skills` (стр. ~24).
4. Сверить разделы «Возможности» и «История спринтов» с `_docs/current-state.md` (01–08) — без избыточного переписывания.

#### Definition of Done

- [x] README не называет проект исключительно «Telegram-ботом»; упомянуты оба адаптера и реализованный multi-agent (вводный абзац + буллет «Консольный адаптер»).
- [x] Ссылка на скиллы в README ведёт на `./app/skills` (в исходнике был гомоглиф в `./` перед `pp/skills`; исправлено, проверено `grep -n "app/skills)"`). Примечание: `grep "pp/skills"` неинформативен — это подстрока `app/skills`.
- [x] Список возможностей/спринтов соответствует `_docs/current-state.md` (добавлен буллет консоли, `/mode` в перечень команд Telegram).
- [x] **Документация обновлена** — да (это документационная задача).
- [x] **Тесты добавлены / обновлены** — `n/a` (только `README.md`).
- [x] `git status` чист, артефакты не закоммичены.

### Задача 1.2. Синхронизировать прочие документы и ссылки

- **Статус:** Done
- **Приоритет:** medium
- **Объём:** S
- **Зависит от:** Задача 1.1
- **Связанные документы:** `_docs/current-state.md`, `_docs/README.md`, `_docs/project-structure.md`, `_board/process.md` §8.1 п.6.
- **Затрагиваемые файлы:** `_docs/current-state.md`, `_docs/README.md`, `_docs/project-structure.md` (по необходимости).

#### Описание

Точечно сверить остальные документы с кодом по итогам спринтов 01–08 и поправить только реальные расхождения (не рефакторить ради рефакторинга).

1. Проверить `_docs/current-state.md` §1 на полноту по спринту 08 (hardening) — дополнить, если есть пробел.
2. Проверить навигацию `_docs/README.md` и дерево `_docs/project-structure.md` на «битые»/устаревшие ссылки.
3. Прогнать синхронизацию ссылок по `process.md` §8.1 п.6 (`grep` по перенесённым/переименованным разделам), не трогая закрытые спринты.

#### Definition of Done

- [x] Найденные расхождения устранены: `_docs/README.md` стр. 3 (позиционирование: адаптеры Telegram + console, multi-agent реализован) и стр. 28 (полный список tools); `_docs/current-state.md` §1.5 (SQLite-персистентность `UserRepository`, спринт 08).
- [x] `grep` по ключевым ссылкам не находит «битых» путей; `./pp/skills` (гомоглиф) отсутствует в `README.md`/`_docs/`, путь `app/skills` существует. `_docs/project-structure.md` проверен — адаптеры console/telegram присутствуют, MAX-записи добавятся в Этапе 5; правок не требует.
- [x] **Документация обновлена** — да.
- [x] **Тесты добавлены / обновлены** — `n/a` (только `_docs/`).
- [x] `git status` чист.

## 5. Этап 2. Каркас MAX-адаптера: конфиг, клиент, точка входа

Транспортный фундамент: конфиг, канал `"max"`, async-клиент на `httpx`, polling-цикл и точка входа. Доменные слои не меняются.

### Задача 2.1. Конфиг MAX и поддержка канала "max"

- **Статус:** Done
- **Приоритет:** high
- **Объём:** S
- **Зависит от:** —
- **Связанные документы:** `_docs/stack.md` §9, `_docs/architecture.md` §3.2, `_docs/events.md`, `_docs/current-state.md` §1.5.
- **Затрагиваемые файлы:** `app/config.py`, `.env.example`, `app/users/repository.py` (проверка), `tests/test_config.py`, `tests/users/test_repository.py`.

#### Описание

1. В `Settings` добавить: `max_bot_token: str | None`, `max_api_base_url: str` (default `https://botapi.max.ru` — **сверить с** `dev.max.ru/docs-api`), `max_poll_timeout: int` (long polling), `max_max_file_mb: int` (default 20).

> **Сверка с API (2026-06-05):** реальный хост — `https://platform-api.max.ru` (не `botapi.max.ru`); взят как default `max_api_base_url`. Авторизация — заголовок `Authorization: <token>` (query не поддерживается). Дефолт `max_poll_timeout=30` (по API).
2. В `.env.example` добавить закомментированные `MAX_BOT_TOKEN`, `MAX_API_BASE_URL`, `MAX_POLL_TIMEOUT`, `MAX_MAX_FILE_MB` с пояснениями (токен — через MasterBot, раздел «Чат-боты → Интеграция → Получить токен»).
3. Убедиться, что `UserRepository.get_or_create("max", external_id, display_name)` работает (колонка `channel` — строка, схема БД не меняется); события `MessageReceived` / `ResponseGenerated` принимают `channel="max"`.

#### Definition of Done

- [x] `Settings` подхватывает `MAX_*` из окружения; валидация не падает при пустом `MAX_BOT_TOKEN` (канал просто не запускается).
- [x] `tests/users/test_repository.py` покрывает `get_or_create("max", ...)` → `channel="max"`, стабильный `user.id` между вызовами.
- [x] `.env.example` дополнен; секрет не хардкодится.
- [x] **Документация обновлена** — `_docs/stack.md` §9 (поля `MAX_*`).
- [x] **Тесты добавлены / обновлены** — да (`tests/test_config.py`, `tests/users/test_repository.py`).
- [x] `git status` чист.

### Задача 2.2. MaxClient на httpx (get_me / get_updates / send_message)

- **Статус:** Done
- **Приоритет:** high
- **Объём:** M
- **Зависит от:** Задача 2.1
- **Связанные документы:** `dev.max.ru/docs-api` (методы `GET /me`, `GET /updates`, `POST /messages`), `_docs/observability.md` §3–§4, `app/utils/secrets.py`, `app/services/llm.py` (образец async-клиента и логирования внешних вызовов).
- **Затрагиваемые файлы:** `app/adapters/max/__init__.py`, `app/adapters/max/client.py`, `tests/adapters/max/__init__.py`, `tests/adapters/max/test_client.py`.

#### Описание

Тонкий async-клиент над MAX Bot REST API (без сторонних SDK; `httpx` уже в зависимостях — `app/tools/http_request.py`, `ollama`).

1. Один общий `httpx.AsyncClient` на адаптер; заголовок `Authorization: <token>` (передача токена в query не поддерживается MAX).
2. Методы: `get_me()` (smoke/идентификация), `get_updates(marker, timeout, limit)` (long polling), `send_message(chat_id|user_id, text)`.
3. Собственные исключения (`MaxUnavailable`, `MaxTimeout`, `MaxBadResponse`) по образцу `LLMUnavailable` / `LLMTimeout`.
4. Структурные логи `external.call` / `external.ok` / `external.fail` (поля `service="max"`, `duration_ms`, `status`); токен/секреты — через `mask_secrets`.

#### Definition of Done

- [x] `tests/adapters/max/test_client.py` мокает `httpx` (без сети): `get_me`, `get_updates` (с `marker`), `send_message`; ошибки сети/таймаут → собственные исключения.
- [x] Тест проверяет, что токен **не** попадает в текст лога (через `mask_secrets`).
- [x] **Документация обновлена** — упоминание клиента в `_docs/architecture.md` §3.13 (черновик, финал — в Этапе 5).
- [x] **Тесты добавлены / обновлены** — да; `pytest -q` зелёный.
- [x] `git status` чист.

### Задача 2.3. Polling-цикл и точка входа app/max_main.py

- **Статус:** Done
- **Приоритет:** high
- **Объём:** M
- **Зависит от:** Задача 2.2
- **Связанные документы:** `_docs/architecture.md` §3.1, §8.4, §8.5; `app/main.py` (`_build_components`, `_wire_telegram`, graceful shutdown), `app/console_main.py` (образец отдельной точки входа), `_docs/memory.md` §4.4 (`recover_pending_journals`).
- **Затрагиваемые файлы:** `app/max_main.py`, `app/adapters/max/adapter.py`, `tests/test_max_main.py`.

#### Описание

1. Переиспользовать channel-agnostic сборку зависимостей (как `app/main.py::_build_components`); добавить `_wire_max(...)` — аналог `_wire_telegram`, собирающий `MaxClient` + диспетчер апдейтов.
2. Long polling loop: `get_updates(marker=...)` в цикле, продвижение `marker`, передача апдейтов в диспетчер; ошибки сети — лог + backoff, цикл не падает.
3. Graceful shutdown (SIGTERM/SIGINT): отмена polling-задачи, закрытие `MaxClient` / `llm` / `semantic_memory` / `users` / `dialog_journal`.
4. Фоновое `recover_pending_journals(...)` параллельно с polling (как в `app/main.py`).
5. Точка входа `app/max_main.py::main` + `run()` с top-level логированием необработанных исключений (как `app/main.py`, см. `current-state.md` §3).

#### Definition of Done

- [x] Smoke: `python -c "from app.max_main import main; print(main)"` и `python -c "import app.adapters.max.adapter"` проходят.
- [x] `tests/test_max_main.py` патчит сетевую часть (`_run_polling`) одной точкой (как `tests/test_main.py`): polling/backoff и ранний выход без токена отрабатывают без сети.
- [x] Диспетчер маршрутизирует апдейт по типу (текст / команда / вложение) — заглушки для текста/команд/файлов закрываются в Этапах 3–4 (`tests/adapters/max/test_adapter.py`).
- [x] **Документация обновлена** — черновик в `_docs/architecture.md` §3.13.
- [x] **Тесты добавлены / обновлены** — да.
- [x] `git status` чист.

> **Примечание по сборке:** `app/max_main.py` переиспользует `app.main._build_components` / `_Components` (channel-agnostic), добавляя `_wire_max` + `_run_polling` + собственный `_shutdown`. `get_me`-smoke при старте не вызывается (чтобы не требовать сети).

## 6. Этап 3. Текст и команды через MAX

Подключить основной пользовательский поток поверх каркаса Этапа 2.

### Задача 3.1. Обработчик текста → core.handle_user_task

- **Статус:** Done
- **Приоритет:** high
- **Объём:** M
- **Зависит от:** Задача 2.3
- **Связанные документы:** `_docs/architecture.md` §4 (поток текста), `app/adapters/telegram/handlers/messages.py` (образец), `_docs/security.md` (`sanitize_user_input`), `app/core/orchestrator.py`.
- **Затрагиваемые файлы:** `app/adapters/max/adapter.py` (или `handlers/messages.py`), `app/utils/text.py` (переиспользовать `split_long_message`), `tests/adapters/max/test_messages.py`.

#### Описание

1. Из апдейта извлечь текст, `user_id`, `chat_id`; получить/создать пользователя через `UserRepository`.
2. `sanitize_user_input(text, ...)`; опубликовать `MessageReceived` (`channel="max"`).
3. Вызвать `core.handle_user_task(text, user_id=..., chat_id=..., conversations=..., executor=..., planner=..., critic=..., ...)`.
4. Ошибки LLM-слоя (`LLMTimeout` / `LLMUnavailable` / `LLMBadResponse`) → человекочитаемые ответы (как в Telegram).
5. Опубликовать `ResponseGenerated`; ответ отправить через `MaxClient.send_message`, длинный — разбить через `split_long_message` под лимит MAX.

#### Definition of Done

- [x] `tests/adapters/max/test_messages.py`: входящий текстовый апдейт → вызов `handle_user_task` (мок) → `send_message` (мок); события `MessageReceived`/`ResponseGenerated` опубликованы с `channel="max"`.
- [x] Тест на разбиение длинного ответа и на маппинг ошибок LLM в подсказки.
- [x] **Документация обновлена** — черновик `_docs/architecture.md` §3.13 (поток текста MAX); финал — Этап 5.
- [x] **Тесты добавлены / обновлены** — да; `pytest -q` зелёный.
- [x] `git status` чист.

### Задача 3.2. Команды через общий CommandRegistry

- **Статус:** Progress
- **Приоритет:** high
- **Объём:** M
- **Зависит от:** Задача 3.1
- **Связанные документы:** `_docs/commands.md`, `app/commands/registry.py`, `app/commands/context.py`, `app/adapters/console/adapter.py` (образец вызова `CommandRegistry`).
- **Затрагиваемые файлы:** `app/adapters/max/adapter.py`, `tests/adapters/max/test_commands.py`.

#### Описание

1. Апдейты, начинающиеся с `/`, маршрутизировать в `CommandRegistry.execute(name, ctx, args=...)` с `CommandContext(channel="max", ...)`.
2. Поддержать тот же набор, что в console/telegram: `/start`, `/help`, `/new`, `/reset`, `/models`, `/model`, `/prompt`, `/mode`, `/search_engines`, `/search_engine`.
3. Если MAX Bot API поддерживает регистрацию списка команд в UI — зарегистрировать при старте; иначе ограничиться `/help`.
4. Неизвестная команда → подсказка (как в существующих адаптерах).

#### Definition of Done

- [ ] `tests/adapters/max/test_commands.py`: `/help` и `/mode` проходят через MAX-диспетчер (мок `CommandRegistry` или реальный реестр) и возвращают ответ; неизвестная команда → подсказка.
- [ ] Команда `/new` корректно вызывает архивирование с прогресс-коллбэком (как в console).
- [ ] **Документация обновлена** — `_docs/commands.md` (упоминание поддержки MAX, если поведение команд отличается; иначе `n/a`).
- [ ] **Тесты добавлены / обновлены** — да.
- [ ] `git status` чист.

## 7. Этап 4. Файловые входы MAX

Принять вложения MAX и пропустить их через существующий конвейер обработки файлов.

### Задача 4.1. Скачивание вложений MAX с изоляцией по пользователю

- **Статус:** ToDo
- **Приоритет:** medium
- **Объём:** M
- **Зависит от:** Задача 2.2
- **Связанные документы:** `dev.max.ru/docs-api` (вложения в апдейтах), `app/adapters/telegram/files.py` (образец `download_telegram_file`), `_docs/architecture.md` §6.1, `_docs/security.md` (изоляция/`FileIdMapper`).
- **Затрагиваемые файлы:** `app/adapters/max/files.py`, `tests/adapters/max/test_files.py`.

#### Описание

1. `download_max_file(...)`: по URL/токену вложения из апдейта скачать файл через `MaxClient`/`httpx`.
2. Проверка размера до/во время скачивания (`MAX_MAX_FILE_MB`) → `FileTooLargeError`.
3. Сохранение в `Settings.tmp_base_dir/{user_id}/` (изоляция по пользователю, защита от path traversal), как в Telegram.

#### Definition of Done

- [ ] `tests/adapters/max/test_files.py`: скачивание с замоканным `httpx`; превышение лимита → `FileTooLargeError`; файл сохраняется в подкаталог пользователя.
- [ ] Путь файла не выходит за `tmp_base_dir` (тест на изоляцию).
- [ ] **Документация обновлена** — черновик `_docs/architecture.md` §6 (MAX); финал — Этап 5.
- [ ] **Тесты добавлены / обновлены** — да.
- [ ] `git status` чист.

### Задача 4.2. Маршрутизация документов / фото / голоса в существующий конвейер

- **Статус:** ToDo
- **Приоритет:** medium
- **Объём:** M
- **Зависит от:** Задача 4.1, Задача 3.1
- **Связанные документы:** `_docs/architecture.md` §6.2–§6.4, `app/adapters/telegram/handlers/messages.py` (образцы `handle_document`/`handle_voice`/`handle_photo`), `app/services/vision.py`, `app/services/transcribe.py`, `app/tools/read_document.py`.
- **Затрагиваемые файлы:** `app/adapters/max/adapter.py` (или `handlers/files.py`), `tests/adapters/max/test_file_messages.py`.

#### Описание

Для каждого типа вложения сформировать goal и передать в `core.handle_user_task`, переиспользуя существующие сервисы (адаптер не дублирует логику обработки):

1. **Документ** (PDF/TXT/MD) → обогащённый goal с путём к файлу, агент читает через tool `read_document`.
2. **Фото** → `Vision.describe(path, caption)` → goal с описанием; при пустом `VISION_MODEL` — подсказка.
3. **Голос/аудио** → `Transcriber.transcribe(path)`; при отсутствии faster-whisper — fallback-сообщение.
4. Маскирование путей через `FileIdMapper`; контекст файла для reply — если MAX отдаёт reply-ссылку (иначе зафиксировать как ограничение в `current-state.md` §2).

#### Definition of Done

- [ ] `tests/adapters/max/test_file_messages.py`: три типа вложений с моками `download`/`Vision`/`Transcriber` → вызов `handle_user_task` с корректным goal.
- [ ] Fallback-сообщения при недоступности vision / faster-whisper покрыты тестом.
- [ ] **Документация обновлена** — черновик `_docs/architecture.md` §6 (MAX); финал — Этап 5.
- [ ] **Тесты добавлены / обновлены** — да; `pytest -q` зелёный.
- [ ] `git status` чист.

## 8. Этап 5. Актуализация документации после MAX

Закрывающий этап (ТЗ): отразить новый канал в основной документации. Чисто-документационный, зависит от Этапов 2–4.

### Задача 5.1. README + roadmap + plan под MAX

- **Статус:** ToDo
- **Приоритет:** high
- **Объём:** S
- **Зависит от:** Задача 3.2, Задача 4.2
- **Связанные документы:** `README.md`, `_docs/roadmap.md` (роль документа: запланированный этап стартовал → удалить отсюда), `_board/plan.md`, `_board/process.md` §8.2.
- **Затрагиваемые файлы:** `README.md`, `_docs/roadmap.md`.

#### Описание

1. `README.md`: добавить MAX в «Возможности», «Требования» (`MAX_BOT_TOKEN`), «Запуск» (`python -m app.max_main`), «Ограничения» при необходимости.
2. `_docs/roadmap.md`: снять **Этап 6 «MAX-адаптер»** (этап стартовал и закрыт спринтом 09; история — в `_board/plan.md` и файле спринта). При необходимости упомянуть MAX-webhook в Этапе 7.
3. Перенумерацию/ссылки на этапы roadmap синхронизировать (`process.md` §8.1 п.6).

#### Definition of Done

- [ ] `README.md` описывает запуск MAX-канала и требование `MAX_BOT_TOKEN`.
- [ ] `_docs/roadmap.md` больше не содержит Этап 6 как Planned/Backlog; ссылки на этапы согласованы.
- [ ] **Документация обновлена** — да.
- [ ] **Тесты добавлены / обновлены** — `n/a`.
- [ ] `git status` чист.

### Задача 5.2. current-state + architecture + project-structure + .env.example

- **Статус:** ToDo
- **Приоритет:** high
- **Объём:** M
- **Зависит от:** Задача 5.1
- **Связанные документы:** `_docs/current-state.md` §1 (шаблон записи подсистемы), `_docs/architecture.md` §3.x/§8.4, `_docs/project-structure.md`, `.env.example`, `requirements.txt`.
- **Затрагиваемые файлы:** `_docs/current-state.md`, `_docs/architecture.md`, `_docs/project-structure.md`, `.env.example`, `requirements.txt` (проверка).

#### Описание

1. `_docs/current-state.md` §1: добавить подсистему «MAX-адаптер» (`app/adapters/max/`, `app/max_main.py`) по шаблону записи; зафиксировать ограничения в §2/§3 при обнаружении (например, reply-контекст файлов, если MAX его не отдаёт).
2. `_docs/architecture.md`: довести черновики §3.x (MAX-адаптер), §4/§6 (потоки MAX), §8.4 (пример); отметить, что webhook для MAX — §8.5/roadmap.
3. `_docs/project-structure.md`: добавить `app/adapters/max/` и `app/max_main.py` в дерево.
4. `.env.example`: финализировать блок `MAX_*`; в `requirements.txt` подтвердить, что новых runtime-зависимостей нет (`httpx` уже присутствует).

#### Definition of Done

- [ ] `_docs/current-state.md`, `_docs/architecture.md`, `_docs/project-structure.md` отражают фактический код MAX-адаптера.
- [ ] `.env.example` содержит финальный блок `MAX_*`; `requirements.txt` без лишних зависимостей.
- [ ] `grep` по ссылкам не находит «битых» путей; навигация `_docs/README.md` согласована.
- [ ] **Документация обновлена** — да.
- [ ] **Тесты добавлены / обновлены** — `n/a`.
- [ ] `git status` чист.

## 9. Риски и смягчение

| # | Риск | Смягчение |
|---|------|-----------|
| 1 | Реальный MAX Bot API отличается от ожиданий (host, формат `updates`/вложений, имена полей). | На Задаче 2.2 свериться с `dev.max.ru/docs-api`; начать с `get_me` как smoke; формат вложений изолировать в Задаче 4.1. Все детали API проверяются при реализации, не выдумываются. |
| 2 | Long polling в MAX «не для production» (по их докам). | MVP осознанно на polling (как Telegram, CON-4); webhook вынесен в `roadmap.md` Этап 7 (non-goal). |
| 3 | Загрузка/скачивание файлов MAX многошаговая (upload URL → upload → attach). | Этап 4 изолирован и зависит от Этапа 3; при сложностях текст/команды работают без файлов (деградация, спринт остаётся ценным). |
| 4 | Дублирование кода с Telegram-адаптером. | Переиспользовать `core` / `CommandRegistry` / сервисы (`Vision`/`Transcriber`/`read_document`); адаптер тонкий — только транспорт и маршрутизация. |
| 5 | Утечка токена в логи/историю git. | `mask_secrets` на внешних вызовах; токен только из `.env`; тест на отсутствие токена в логах; `.env` в `.gitignore`. |
| 6 | Нет реального бота/токена MAX для ручной проверки. | Все unit-тесты — на моках `httpx` (без сети). Ручная проверка в реальном MAX — задача пользователя при наличии токена; при блокировке отметить соответствующую задачу `Blocked`. |

## 10. Сводная таблица задач спринта

| #   | Задача | Приоритет | Объём | Статус | Зависит от |
|-----|--------|:---------:|:-----:|:------:|:----------:|
| 1.1 | Актуализировать README под мульти-канальность и спринты 01–08 | high | S | Done | — |
| 1.2 | Синхронизировать прочие документы и ссылки | medium | S | Done | 1.1 |
| 2.1 | Конфиг MAX и поддержка канала "max" | high | S | Done | — |
| 2.2 | MaxClient на httpx (get_me / get_updates / send_message) | high | M | Done | 2.1 |
| 2.3 | Polling-цикл и точка входа app/max_main.py | high | M | Done | 2.2 |
| 3.1 | Обработчик текста → core.handle_user_task | high | M | Done | 2.3 |
| 3.2 | Команды через общий CommandRegistry | high | M | Progress | 3.1 |
| 4.1 | Скачивание вложений MAX с изоляцией по пользователю | medium | M | ToDo | 2.2 |
| 4.2 | Маршрутизация документов / фото / голоса в конвейер | medium | M | ToDo | 4.1, 3.1 |
| 5.1 | README + roadmap + plan под MAX | high | S | ToDo | 3.2, 4.2 |
| 5.2 | current-state + architecture + project-structure + .env.example | high | M | ToDo | 5.1 |

> Обновляется при каждом переходе статуса и при добавлении/удалении задач.

## 11. История изменений спринта

- **2026-06-04** — спринт открыт, ветка `feature/09-max-adapter` создана от `main`.
- **2026-06-05** — закрыта задача 3.1: обработчик текста MAX (`MaxUpdateDispatcher._handle_text`) — `sanitize_user_input` → `core.handle_user_task` → `MaxClient.send_message` с разбиением под лимит, события `channel="max"`, маппинг ошибок LLM; тесты `tests/adapters/max/test_messages.py` (коммит `feat(max): обработка текста через core.handle_user_task`).
- **2026-06-05** — Этап 2 закрыт (задачи 2.1–2.3): конфиг `MAX_*` + канал `"max"`, `MaxClient` на `httpx`, polling-цикл и точка входа `app/max_main.py` + диспетчер. Сверка с `dev.max.ru/docs-api`: хост `platform-api.max.ru`, `Authorization: <token>`. `pytest`/`flake8` зелёные.
- **2026-06-04** — закрыта задача 1.1: README актуализирован (позиционирование как локальный AI-агент с адаптерами Telegram + console, multi-agent как реализованный, буллет консольного адаптера, `/mode`); исправлен гомоглиф в ссылке на `app/skills` (коммит `docs(readme): актуализировать позиционирование и адаптеры, исправить ссылку app/skills`).
- **2026-06-04** — закрыта задача 1.2: синхронизированы `_docs/README.md` (позиционирование, полный список tools) и `_docs/current-state.md` §1.5 (SQLite-персистентность `UserRepository`); ссылки проверены (коммит `docs: синхронизировать _docs/README.md и current-state с состоянием после спринтов 01–08`). **Этап 1 закрыт.**
