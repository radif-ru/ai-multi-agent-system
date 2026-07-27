# Roadmap — что планируется

Документ хранит **только будущее** — этапы развития проекта со статусом `Planned` или `Backlog`, которые ещё не запущены ни одним спринтом. На основе этого списка собираются файлы новых спринтов в `_board/sprints/<NN>-<short-name>.md` (см. `_board/process.md` §6).

## Роль документа

- **Только Planned / Backlog.** Закрытые этапы здесь **не дублируются** — их история в `_board/plan.md` (таблица «Закрытые») и в файлах закрытых спринтов `_board/sprints/<NN>-*.md`. Активный спринт — в `_board/plan.md` (таблица «Активные»).
- **Не дублирует** `_docs/current-state.md` (фактическое состояние кода `app/`) и `_board/plan.md` (индекс спринтов).
- **Этапы не нумеруются.** Идентификатор этапа — его заголовок; ссылки из других документов оформляются как `` `_docs/roadmap.md` § «Web-адаптер» ``. Порядок разделов не означает приоритет. Причина — сквозная нумерация ломала ссылки при каждой вставке или удалении этапа (см. `_board/process.md` §8.2).
- **Когда правится** — см. `_board/process.md` §8.2:
  - появилась новая планируемая задача/этап вне текущего спринта → добавить сюда;
  - запланированный этап стартовал спринтом → удалить отсюда (история в `_board/plan.md`).

Статусы этапов:

- `Planned` — этап запланирован, есть конкретный план задач, ожидает открытия спринта.
- `Backlog` — этап в очереди без жёстких сроков и без детализации; кандидат на спринт по запросу.

---

## Stream-индикация шагов агента

**Статус:** Backlog.

Сейчас пользователь видит только финальный ответ, а в промежутке — индикатор «печатает…». Для долгих циклов (5+ шагов) это слабая обратная связь.

- [ ] Edit-сообщение в Telegram: `Шаг 1: <thought>… Шаг 2: <thought>…`
- [ ] При финальном ответе — заменить шаги полным результатом.
- [ ] Лимит длины edit-сообщения (≤ 4096); при переполнении — отдельное сообщение.

## Стриминг ответа Ollama

**Статус:** Backlog.

`OllamaClient.chat` сейчас вызывается с `stream=False`. Включение стриминга позволит показывать частичный `final_answer` сразу, пока он генерируется.

- [ ] `chat_stream` метод в `OllamaClient`.
- [ ] Адаптация Executor: при `final_answer`-шаге — стриминг в Telegram.
- [ ] При `action`-шаге — собираем полный ответ, парсим JSON.

**Зависит от:** § «Stream-индикация шагов агента» (UX-фундамент для шагов).

## Capability graph для multi-agent

**Статус:** Backlog.

Базовый multi-agent (Planner + Executor + Critic, режимы `OFF | NORMAL | DEEP`) закрыт спринтом 07 — см. `_docs/multi-agent.md` и `_board/sprints/07-multi-agent.md`. Текущий Planner возвращает **линейный** план; в Executor шаги склеиваются в один `goal`. Расширение:

- [ ] Planner возвращает DAG шагов вместо линейного списка (`Plan` с зависимостями).
- [ ] Переиспользование результатов узлов через плейсхолдеры `{{nodeId}}` в описаниях шагов.
- [ ] Параллельное выполнение независимых ветвей DAG.
- [ ] Расширенный JSON-протокол Planner (контракт см. `_docs/multi-agent.md` §2.1) с обратной совместимостью с линейным планом.

## Web-адаптер

**Статус:** Planned.

Архитектурно адаптеры подключаются единым контрактом `core.handle_user_task(text, user_id, chat_id)` (см. `architecture.md` §8.4). Telegram, консоль и MAX уже реализованы (см. `_docs/current-state.md` §1.4).

- [ ] FastAPI/aiohttp + simple HTML chat-страница, общается с `core` напрямую (тот же event loop).
- [ ] Унифицированный `user_id` cross-channel (например, через таблицу `external_id → internal_user_id`).
- [ ] **Per-user видимость файлов:** Web-адаптер должен наследовать ту же per-user модель `read_file`, что и мессенджеры (корень = `Settings.get_user_tmp_dir(user_id)`, сборка с `read_file_user_scoped=True`). См. `_docs/security.md` §4.2.

## Webhook вместо polling (Telegram и MAX)

**Статус:** Backlog.

CON-4 запрещает webhook в MVP, но это кандидат на отдельный спринт. Особенно актуально для MAX: его документация (`dev.max.ru/docs-api`) прямо рекомендует webhook для production (long polling ограничен по скорости и сроку хранения событий); подписка — через `POST /subscriptions`.

- [ ] aiogram webhook server (aiohttp) для Telegram.
- [ ] MAX webhook через `POST /subscriptions` (HTTPS + сертификат доверенного ЦС, по требованиям API).
- [ ] Конфиг: `WEBHOOK_URL`, `WEBHOOK_SECRET`.
- [ ] TLS-настройка (через nginx или встроенный — на усмотрение).
- [ ] Совместимая работа: можно стартануть либо в polling, либо в webhook через флаг `BOT_MODE=polling|webhook`.

## Throttling middleware

**Статус:** Backlog.

Защита от спама / лавинообразных запросов.

- [ ] Простой leaky-bucket по `user_id`: максимум N сообщений в M секунд.
- [ ] Параметры в `.env` (`THROTTLE_MAX_PER_MINUTE`).
- [ ] При превышении — мягкий ответ «слишком часто», без блокировки.

## Скиллы для практических задач

**Статус:** Backlog (инкрементально).

После того, как `app/skills/` инфраструктура работает, наполняем библиотеку.

- [ ] `web_research` — пошаговый рисёрч с гибридной стратегией (поиск → отбор источников → извлечение → синтез).
- [ ] `summary_long_text`, `tutorial_step_by_step` и пр.

Уже реализованные скиллы — `_docs/skills.md` §8 (список) и `_board/plan.md` (история по спринтам).

## Docker / docker-compose

**Статус:** Backlog.

- [ ] `Dockerfile` для бота (multi-stage build: deps + runtime).
- [ ] `docker-compose.yml`: контейнер бота + контейнер Ollama (с GPU-passthrough опционально).
- [ ] Volume для `data/` (sqlite-vec БД переживает рестарт контейнера).
- [ ] `Makefile` (или `justfile`) с командами `make up`, `make down`, `make logs`.

## Sandboxed tools

**Статус:** Backlog.

Для tools, которые опасно запускать без изоляции (shell, произвольное чтение/запись ФС, sql-execute).

- [ ] `app/tools/sandboxed/` со своим контрактом `SandboxedTool`.
- [ ] Изоляция через `subprocess` + `chroot` / `firejail` / `podman` (на усмотрение).
- [ ] Whitelist команд / путей — конфигурируется через `.env`.

## Точный токенайзер

**Статус:** Backlog.

Сейчас `estimate_tokens = chars / 4`. Для слабых моделей с маленьким окном это иногда неточно.

- [ ] `tiktoken` или HuggingFace tokenizer.
- [ ] Конфиг: `TOKENIZER_MODEL` (по умолчанию синхронизирован с LLM).
- [ ] Использовать в логах и в lint'ах перед `chat`-вызовом, чтобы предупреждать о переполнении контекста.

## Hot-reload скиллов и промптов

**Статус:** Backlog.

Сейчас правка `app/skills/` и `app/prompts/` требует рестарта процесса. Watcher на эти каталоги (через `watchdog`) автоматически перезагружает регистры.

- [ ] `SkillRegistry.watch(...)`.
- [ ] `PromptLoader.watch(...)`.

## Per-skill / per-task memory

**Статус:** Backlog.

Сейчас вся семантическая память — общий пул чанков. Расширения:

- [ ] Метка `skill_name` на чанках, фильтр по ней в `memory_search`.
- [ ] Краткое саммари каждой выполненной задачи (с tool calls + observations) для будущего Critic'а.

**Опирается на** уже реализованный multi-agent (Planner + Critic) — см. `_docs/multi-agent.md`.

## Файловые входы — добор

**Статус:** Backlog.

Базовые файловые входы (Document, Voice, Photo, OCR PDF) уже реализованы в закрытых спринтах. Здесь — оставшиеся форматы:

- [ ] Видео (frame-extraction → vision → описание).
- [ ] Geolocation-сообщения.

## Интерактивное исследование длинного контекста

**Статус:** Backlog. **Источник:** ADR-1 (`_docs/decisions.md`).

Tool `context_explore` поверх существующего `Summarizer` — операции `peek`, `grep`, `summarize` по чанкам длинного контекста (почтовые ящики, документы, логи).

- [ ] Tool `context_explore` с операциями `peek` / `grep` / `summarize`.
- [ ] Переиспользование `Summarizer` (чанкинг + map-reduce).
- [ ] Опасный tool → `_DANGEROUS_TOOLS` с allowlist.

## Интеграции почты и диска — добор

**Статус:** Backlog. **Источник:** спринт 13 (read-only реализован, отложенное — сюда).

Текущее состояние: read-only IMAP (`email_list` / `email_read` с вложениями, чтение вложений через `read_document`), скилл `email_draft`, Яндекс.Диск на чтение и запись (`disk_list` / `disk_download` / `disk_upload`). Отложенные фичи:

- [ ] Отправка писем (`email_send` — SMTP, Яндекс + Gmail).
- [ ] Google Диск (OAuth, `gdrive_list` / `gdrive_download` / `gdrive_upload`).

## TTL/cleanup долгосрочной памяти

**Статус:** Backlog. **Источник:** ADR-4 (`_docs/decisions.md`).

Индекс `ix_memory_created` существует, но очистки старых чанков нет. Для single-user рост архива медленный, но при длительной эксплуатации БД растёт без ограничений.

- [ ] Конфиг `MEMORY_TTL_DAYS` (default: 0 = отключено).
- [ ] Фоновая задача (или при `/new`) удаляет чанки старше TTL из `memory_chunks` + `memory_vec`.
- [ ] Логирование количества удалённых чанков.

## Планировщик — отмена задачи из команды

**Статус:** Backlog. **Источник:** аудит спринта 15 (задача 4.1 описывала `/schedules cancel <id>`, но реализованы только `/schedule` и `/schedules`).

Сейчас отменить задачу можно только через агента (tool `cancel_scheduled_task`) — детерминированного пути из команды нет.

- [ ] `/schedules cancel <id>` — отмена своей задачи (scope по `user_id`, как в tool).
- [ ] Понятный ответ при чужом / несуществующем `id`.

## Отказанные этапы

- **Внешние онлайн-LLM (облачные API)** — отказ. Local-first — не временное ограничение MVP, а свойство продукта: данные не покидают машину, нет внешних ключей, лимитов и платы за токены (`requirements.md` CON-2 и NFR-6, `architecture.md` §2, `instructions.md` §11). Гибкость обеспечивается сменой **локальной** модели (`/model`, `OLLAMA_AVAILABLE_MODELS`), а не сменой провайдера. Пересмотр — только по явному решению пользователя со снятием CON-2.
- **n8n как оркестратор** — отказ (ADR-2, `_docs/decisions.md`). n8n избыточен для single-user local-first: дублирует `EventBus`, orchestrator, tools; добавляет Docker-зависимость и поверхность атаки. Cron — APScheduler внутри процесса; webhook — FastAPI-адаптер (§ «Webhook вместо polling (Telegram и MAX)»). Пересмотр — при многопользовательности.
- **Смена метрики `memory_vec` на cosine** — отказ (ADR-4, `_docs/decisions.md`). `nomic-embed-text` выдаёт нормализованные векторы: L2 и cosine монотонно связаны, ранжирование идентично. Миграция `memory_vec` неоправданна для single-user. Пересмотр — при смене embedding-модели на ненормализованную.

---

## Принципы планирования

- Один активный спринт за раз (см. `_board/process.md` §2 п.1).
- Новый спринт = новая ветка `feature/<NN>-<short-name>` от свежей `main` (см. `_board/process.md` §2 п.9 и §6).
- Спринт оценивается в задачах, не в часах. Каждая задача проходит DoD из шаблона `_board/process.md` §4.2.
- При обнаружении легаси / нюанса — записываем в `_docs/current-state.md` §2; не правим попутно.
- Правила обновления самого `roadmap.md` — `_board/process.md` §8.2.
