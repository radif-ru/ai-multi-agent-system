# Спринт 15. Расширения почты, диска и планировщика

- **Источник:** ТЗ пользователя (чтение вложений email + доставка планировщика в console/MAX + черновики писем + upload на Диск + bot-команды /schedule + парсер времени + демо скриншоты) + `_docs/roadmap.md` Этап 16 (почта/диск добор) + Этап 18 (расширения планировщика) + `_docs/current-state.md` §1.9/§1.10.
- **Ветка:** `feature/15-mail-disk-scheduler-ext` (от `main`; см. `_board/process.md` §2, п.2).
- **Открыт:** 2026-07-24
- **Закрыт:** —

## 1. Цель спринта

Расширить интеграции почты и диска, и завершить MVP планировщика. Конкретно:

- **Вложения email** — модель читает PDF/документы/изображения из писем через `read_document`.
- **Черновики писем** — скилл `email_draft` для генерации черновика ответа по контексту.
- **Upload на Диск** — `disk_upload` tool для загрузки файлов на Яндекс.Диск.
- **Crons** — убрать Crons API (GlitchTip не поддерживает), оставить heartbeat-логирование.
- **Доставка планировщика** — console и MAX (сейчас только Telegram).
- **Bot-команды /schedule** — команды как альтернатива natural-language tools.
- **Парсер времени** — естественный парсер «каждый день в 9 утра» → cron в коде (сейчас делает LLM).
- **Демо скриншоты** — иллюстрации возможностей для README.

## 2. Скоуп и non-goals

### В скоупе

- **Вложения email:** `_extract_body` → `(body, attachments)`; `_save_attachments` → `data/tmp/` + `FileIdMapper`; `email_read` → `attachments` в JSON; скилл `email-assistant` обновлён.
- **Черновики писем:** скилл `email_draft` — генерация черновика ответа по контексту письма (без отправки).
- **Upload на Диск:** `disk_upload` tool — загрузка файла из `data/tmp/` на Яндекс.Диск через REST API.
- **Crons:** убрать `_cron_checkin`, заменить на heartbeat-логирование.
- **Планировщик console/MAX:** `make_console_notifier`, `make_max_notifier`, поле `channel` в `ScheduledTask`, tools обновлены.
- **Bot-команды /schedule:** команды `/schedule` / `/schedules` как альтернатива/дополнение к tools.
- **Парсер времени:** детерминированный парсер естественного языка → cron в коде (`app/services/cron_parser.py`).
- **Демо скриншоты:** скриншоты работы бота в `docs/screenshots/`, вставка в README.
- **Документация:** актуализация `_docs/*`, `README.md`.

### Вне скоупа (non-goals)

- **Отправка писем** (`email_send` — SMTP) → `_docs/roadmap.md` Этап 16 (остаётся backlog).
- **Google Диск** (OAuth) → `_docs/roadmap.md` Этап 16.
- **Webhook-режим** — не трогаем.
- **Docker / docker-compose** → `_docs/roadmap.md` Этап 9.

## 3. Acceptance Criteria спринта

- [ ] `email_read` возвращает `attachments` с `file_id`; модель читает вложения через `read_document`.
- [ ] Скилл `email_draft` генерирует черновик ответа на письмо по контексту.
- [ ] `disk_upload` загружает файлы на Яндекс.Диск.
- [ ] Crons API убран; heartbeat-логирование вместо него.
- [ ] Планировщик доставляет результаты в console и MAX (не только Telegram).
- [ ] Bot-команды `/schedule` / `/schedules` работают как альтернатива tools.
- [ ] Парсер времени преобразует «каждый день в 9 утра» → `0 9 * * *` без LLM.
- [ ] Демо скриншоты добавлены в README.
- [ ] Документация актуализирована, все CI-гейты зелёные: `flake8`, `pytest -q` c `--cov-fail-under=80`, `check_env_sync`, `check_sprint_sync`, `check_doc_links`, `check_agents_sync`.
- [ ] Все задачи спринта — `Done`, сводная таблица актуальна.

---

## 4. Этап 1. Вложения email

Цель: модель может читать вложения писем через `read_document`, как файлы из Telegram.

### Задача 1.1. Сохранение вложений и возврат file_id

- **Статус:** Done
- **Приоритет:** high
- **Объём:** M
- **Зависит от:** —
- **Связанные документы:** `_docs/tools.md` §4.12; `_docs/current-state.md` §1.9; `_docs/roadmap.md` Этап 16.
- **Затрагиваемые файлы:** `app/services/mail.py`, `app/tools/email_read.py`, `app/skills/email-assistant/SKILL.md`, `tests/services/test_mail.py`.

#### Описание

`_extract_body` в `app/services/mail.py` сейчас пропускает части с `Content-Disposition: attachment`. Нужно:

1. Изменить `_extract_body` — возвращать `(body, attachments)` где `attachments` — список `{filename, content_type, size, payload}`.
2. Добавить `_save_attachments(attachments, user_id)` — сохраняет файлы в `data/tmp/` и регистрирует через `FileIdMapper`, возвращает `[{filename, file_id, content_type, size}]` без payload.
3. Обновить `_read_sync` / `read_message` — вызывать `_save_attachments`, возвращать `attachments` в результате.
4. Обновить `app/tools/email_read.py` — description упоминает `attachments` и `read_document`.
5. Обновить `app/skills/email-assistant/SKILL.md` — добавить `read_document` в инструменты, шаг 4 алгоритма — чтение вложений через `read_document` с `file_id`; убрать `disk_download` из «Когда не использовать».

#### Definition of Done

- [ ] `_extract_body` возвращает `(body, attachments)`; `_save_attachments` сохраняет файлы и регистрирует `file_id`.
- [ ] `email_read` возвращает `attachments` в JSON без payload.
- [ ] Скилл `email-assistant` обновлён: `read_document` для вложений, `disk_download` убран.
- [ ] Тесты зелёные: 6 новых тестов на вложения, существующие обновлены.
- [ ] **Документация обновлена**: `_docs/tools.md` §4.12, `_docs/current-state.md` §1.9, `_docs/skills.md`.
- [ ] `flake8 app tests` зелёный.
- [ ] `git status` чист.

---

## 5. Этап 2. Crons + доставка планировщика в console/MAX

Цель: убрать Crons API (GlitchTip не поддерживает), расширить доставку планировщика на console и MAX.

### Задача 2.1. Убрать Crons API, оставить heartbeat-логирование

- **Статус:** Done
- **Приоритет:** high
- **Объём:** S
- **Зависит от:** —
- **Связанные документы:** `_docs/observability.md` §5; `_docs/scheduler.md`; `_docs/current-state.md` §1.7.
- **Затрагиваемые файлы:** `app/services/scheduler_runner.py`, `tests/services/test_scheduler_runner.py`, `_docs/observability.md`, `_docs/scheduler.md`.

#### Описание

GlitchTip не поддерживает Crons API (в отличие от Sentry). `_cron_checkin` в `scheduler_runner.py` отправляет checkin'ы, которые никуда не доходят. Нужно:

1. Убрать `_cron_checkin` из `scheduler_runner.py`.
2. Заменить на обычное `logger.info` heartbeat-логирование (start/ok/error) — эти логи уже уходят в GlitchTip Logs через `SENTRY_LOG_LEVEL=INFO`.
3. Обновить тесты — убрать тесты на `_cron_checkin`, добавить проверку heartbeat-логов.
4. Обновить `_docs/observability.md` §5 — убрать упоминание Crons.
5. Обновить `_docs/scheduler.md` — убрать Crons из описания.

#### Definition of Done

- [ ] `_cron_checkin` убран; heartbeat-логирование на его месте.
- [ ] Тесты обновлены: `_cron_checkin` тесты удалены, heartbeat-тесты добавлены.
- [ ] `_docs/observability.md` §5, `_docs/scheduler.md` обновлены.
- [ ] `flake8 app tests` зелёный.
- [ ] `git status` чист.

### Задача 2.2. Доставка планировщика в console и MAX

- **Статус:** Done
- **Приоритет:** high
- **Объём:** M
- **Зависит от:** 2.1
- **Связанные документы:** `_docs/scheduler.md`; `_docs/current-state.md` §1.10; `_docs/roadmap.md` Этап 18.
- **Затрагиваемые файлы:** `app/services/scheduler_runner.py`, `app/services/scheduled_tasks.py`, `app/services/scheduler.py`, `app/console_main.py`, `app/max_main.py`, `app/config.py`, `tests/services/test_scheduler.py`, `tests/services/test_scheduler_runner.py`.

#### Описание

Сейчас доставка результатов планировщика — только Telegram (`make_telegram_notifier`). Нужно:

1. Добавить `make_console_notifier` и `make_max_notifier` по образцу `make_telegram_notifier`.
2. Добавить поле `channel` в `ScheduledTask` (default `"telegram"`), миграция схемы `scheduled_tasks`.
3. Выбор notifier'а по `task.channel` в `run_scheduled_task`.
4. Tools `schedule_task` — добавить аргумент `channel` (`telegram|console|max`).
5. Lifecycle: scheduler запускается в `console_main.py` и `max_main.py` (сейчас только `main.py`).
6. Обновить тесты.

#### Definition of Done

- [ ] `make_console_notifier` и `make_max_notifier` реализованы.
- [ ] `ScheduledTask.channel` добавлен; выбор notifier по каналу.
- [ ] `schedule_task` tool принимает `channel`.
- [ ] Scheduler запускается в console и MAX.
- [ ] Тесты зелёные: новые тесты на console/MAX notifier, обновлённые на channel.
- [ ] **Документация обновлена**: `_docs/scheduler.md`, `_docs/current-state.md` §1.10, `_docs/tools.md`.
- [ ] `flake8 app tests` зелёный.
- [ ] `git status` чист.

---

## 6. Этап 3. Расширения почты и диска

Цель: черновики писем и загрузка файлов на Диск.

### Задача 3.1. Скилл email_draft — черновик ответа на письмо

- **Статус:** Done
- **Приоритет:** medium
- **Объём:** M
- **Зависит от:** 1.1
- **Связанные документы:** `_docs/roadmap.md` Этап 16; `_docs/skills.md`; `_docs/current-state.md` §1.9.
- **Затрагиваемые файлы:** `app/skills/email_draft/SKILL.md`, `app/skills/email_draft/skill.json`, `_docs/skills.md`, `_docs/current-state.md`.

#### Описание

Скилл `email_draft` — генерация черновика ответа на письмо по контексту. Без отправки (отправка — separate roadmap item). Нужно:

1. Создать `app/skills/email_draft/SKILL.md` — инструкция: прочитать письмо через `email_read`, проанализировать контекст, сгенерировать черновик ответа (тема, тело, тон).
2. Создать `app/skills/email_draft/skill.json` — метаданные скилла.
3. Обновить `_docs/skills.md` — добавить `email_draft` в список примеров.
4. Обновить `_docs/current-state.md` §1.9 — упомянуть скилл.
5. Обновить `_docs/roadmap.md` Этап 16 — отметить `email_draft` как реализованное.

#### Definition of Done

- [ ] Скилл `email_draft` создан и подхватывается `SkillRegistry`.
- [ ] `_docs/skills.md`, `_docs/current-state.md` §1.9 обновлены.
- [ ] `_docs/roadmap.md` Этап 16 — `email_draft` отмечен `[x]`.
- [ ] `check_agents_sync`, `check_doc_links` зелёные.
- [ ] `flake8 app tests` зелёный.
- [ ] `git status` чист.

### Задача 3.2. disk_upload — загрузка файлов на Яндекс.Диск

- **Статус:** Done
- **Приоритет:** medium
- **Объём:** M
- **Зависит от:** —
- **Связанные документы:** `_docs/roadmap.md` Этап 16; `_docs/current-state.md` §1.9; `_docs/tools.md` §4.13–4.14.
- **Затрагиваемые файлы:** `app/services/yandex_disk.py`, `app/tools/disk_upload.py`, `app/tools/registry.py`, `tests/services/test_yandex_disk.py`, `tests/tools/test_disk_upload.py`.

#### Описание

Сейчас `YandexDiskReader` — read-only (list/download). Нужно добавить upload:

1. Добавить метод `upload(path, local_file_path)` в `YandexDiskReader` — REST API `PUT /v1/disk/resources/upload?path=...` → получение upload URL → `PUT` файла.
2. Создать `app/tools/disk_upload.py` — tool для загрузки файла из `data/tmp/` на Диск по `file_id` (через `FileIdMapper`).
3. Зарегистрировать tool в `ToolRegistry`.
4. Обновить `_docs/tools.md` — добавить `disk_upload`.
5. Обновить `_docs/current-state.md` §1.9 — упомянуть upload.
6. Обновить `_docs/roadmap.md` Этап 16 — отметить `disk_upload` как реализованное.
7. Тесты на upload (моки httpx).

#### Definition of Done

- [ ] `YandexDiskReader.upload` реализован.
- [ ] `disk_upload` tool создан и зарегистрирован.
- [ ] Тесты зелёные: моки на upload API.
- [ ] **Документация обновлена**: `_docs/tools.md`, `_docs/current-state.md` §1.9, `_docs/roadmap.md` Этап 16.
- [ ] `flake8 app tests` зелёный.
- [ ] `git status` чист.

---

## 7. Этап 4. Bot-команды /schedule и парсер времени

Цель: команды `/schedule` / `/schedules` как альтернатива tools, детерминированный парсер времени.

### Задача 4.1. Bot-команды /schedule / /schedules

- **Статус:** Done
- **Приоритет:** medium
- **Объём:** M
- **Зависит от:** 2.2
- **Связанные документы:** `_docs/roadmap.md` Этап 18; `_docs/scheduler.md`; `_docs/commands.md`.
- **Затрагиваемые файлы:** `app/adapters/telegram/handlers/commands.py`, `app/adapters/console/adapter.py`, `app/adapters/max/adapter.py`, `tests/adapters/test_schedule_commands.py`.

#### Описание

Команды как альтернатива/дополнение к natural-language tools:

1. `/schedule <cron> <text>` — поставить задачу (или `/schedule <естественный язык>`, если парсер 4.2 готов).
2. `/schedules` — список задач пользователя.
3. `/schedules cancel <id>` — отменить задачу.
4. Регистрация в `CommandRegistry` для Telegram, console и MAX.
5. Обновить `_docs/commands.md` — добавить команды.
6. Обновить `_docs/scheduler.md` — упомянуть команды.
7. Обновить `_docs/roadmap.md` Этап 18 — отметить bot-команды как реализованные.

#### Definition of Done

- [ ] Команды `/schedule`, `/schedules` работают в Telegram, console и MAX.
- [ ] `CommandRegistry` обновлён.
- [ ] Тесты зелёные: тесты на команды.
- [ ] **Документация обновлена**: `_docs/commands.md`, `_docs/scheduler.md`, `_docs/roadmap.md` Этап 18.
- [ ] `flake8 app tests` зелёный.
- [ ] `git status` чист.

### Задача 4.2. Естественный парсер времени в cron

- **Статус:** Done
- **Приоритет:** medium
- **Объём:** M
- **Зависит от:** —
- **Связанные документы:** `_docs/roadmap.md` Этап 18; `_docs/scheduler.md`; `app/skills/scheduler/SKILL.md`.
- **Затрагиваемые файлы:** `app/services/cron_parser.py`, `tests/services/test_cron_parser.py`, `app/skills/scheduler/SKILL.md`, `_docs/scheduler.md`.

#### Описание

Сейчас маппинг «каждый день в 9 утра» → cron делает LLM по скиллу `scheduler`. Нужно добавить детерминированный парсер:

1. Создать `app/services/cron_parser.py` — парсер естественного языка → 5-польный cron.
2. Поддерживаемые паттерны: «каждый день в N», «каждый понедельник в N», «по будням в N», «каждый час», «каждые N часов», «каждую неделю», «каждое N число месяца».
3. Fallback: если паттерн не распознан — возвращать `None`, LLM продолжает делать маппинг (graceful).
4. Обновить скилл `scheduler` — указать что парсер доступен, но LLM может его использовать как fallback.
5. Тесты на все паттерны + unsupported.
6. Обновить `_docs/scheduler.md` — упомянуть парсер.
7. Обновить `_docs/roadmap.md` Этап 18 — отметить парсер как реализованный.

#### Definition of Done

- [ ] `cron_parser.py` создан, поддерживает базовые паттерны.
- [ ] Fallback на LLM при нераспознанном паттерне.
- [ ] Тесты зелёные: тесты на все паттерны + unsupported.
- [ ] **Документация обновлена**: `_docs/scheduler.md`, `_docs/roadmap.md` Этап 18.
- [ ] `flake8 app tests` зелёный.
- [ ] `git status` чист.

---

## 8. Этап 5. Демо скриншоты и документация

Цель: демо скриншоты для README, финальная актуализация документации, все гейты зелёные.

### Задача 5.1. Демо скриншоты

- **Статус:** ToDo
- **Приоритет:** low
- **Объём:** S
- **Зависит от:** 1.1, 2.2, 3.1, 4.1
- **Связанные документы:** `README.md`.
- **Затрагиваемые файлы:** `docs/screenshots/`, `README.md`.

#### Описание

Добавить демо скриншоты работы бота в README:

1. Создать каталог `docs/screenshots/`.
2. Сделать скриншоты: чтение почты с вложениями, планировщик в Telegram, черновик письма, disk_upload.
3. Вставить скриншоты в README.md в раздел «Возможности» или отдельный раздел «Демо».
4. Скриншоты — PNG, оптимизированные (не больше 200 КБ каждый).

#### Definition of Done

- [ ] Каталог `docs/screenshots/` создан, скриншоты добавлены.
- [ ] README.md обновлён — скриншоты вставлены.
- [ ] `check_doc_links` зелёный (ссылки на скриншоты валидны).
- [ ] `git status` чист.

### Задача 5.2. Актуализация _docs, roadmap, README + гейты

- **Статус:** ToDo
- **Приоритет:** medium
- **Объём:** M
- **Зависит от:** 1.1, 2.1, 2.2, 3.1, 3.2, 4.1, 4.2, 5.1
- **Связанные документы:** `_docs/roadmap.md` Этап 16, 18; `_docs/current-state.md` §1.9, §1.10; `_docs/skills.md`; `README.md`.
- **Затрагиваемые файлы:** `_docs/roadmap.md`, `_docs/current-state.md`, `_docs/skills.md`, `_docs/tools.md`, `_docs/observability.md`, `_docs/scheduler.md`, `_docs/stack.md`, `README.md`.

#### Описание

Финальная синхронизация всей документации под новые фичи:

1. `_docs/roadmap.md` — отметить реализованное в Этапах 16 и 18.
2. `_docs/current-state.md` — обновить §1.9 (вложения, email_draft, disk_upload), §1.10 (channel, bot-команды, парсер), §1.7 (убрать Crons).
3. `_docs/skills.md` — обновить описания `email-assistant`, `email_draft`.
4. `_docs/tools.md` — обновить §4.12 (email_read attachments), §4.13–4.14 (disk_upload), §4.16–4.18 (schedule channel).
5. `_docs/observability.md` §5 — убрать Crons.
6. `_docs/scheduler.md` — channel delivery, bot-команды, парсер, убрать Crons.
7. `_docs/stack.md` — обновить env-переменные если есть новые.
8. `README.md` — упомянуть все новые фичи.
9. Все гейты: `flake8`, `pytest`, `check_doc_links`, `check_env_sync`, `check_sprint_sync`, `check_agents_sync`.

#### Definition of Done

- [ ] Все перечисленные документы актуализированы.
- [ ] `check_doc_links`, `check_env_sync`, `check_sprint_sync`, `check_agents_sync` зелёные.
- [ ] `flake8 app tests` зелёный.
- [ ] `pytest -q` с `--cov-fail-under=80` зелёный.
- [ ] `git status` чист.

---

## 9. Этап 6. Техдолг из stash (постфактум)

Цель: оформить незакоммиченные правки из до-спринтного stash как задачи спринта (process.md §3 п.4).

### Задача 6.1. fix(protocol): final_answer + thought — валидный финал

- **Статус:** ToDo
- **Приоритет:** high
- **Объём:** S
- **Зависит от:** —
- **Связанные документы:** `_docs/agent-loop.md` §2.4.
- **Затрагиваемые файлы:** `app/agents/protocol.py`, `tests/agents/test_protocol.py`.

#### Описание

Модель часто пишет `thought` рядом с готовым `final_answer`. Старый код бросал `LLMBadResponse` (mixed format). Новый — берёт `final_answer`, игнорируя `thought`. Пустой `final_answer` + action-поля — шаг с действием.

#### Definition of Done

- [ ] `parse_agent_response` принимает `final_answer` + `thought` как финал.
- [ ] Пустой `final_answer` + action — шаг с действием.
- [ ] Тесты зелёные: 3 новых теста в `test_protocol.py`.
- [ ] `flake8` зелёный.

### Задача 6.2. chore(config): AGENT_MAX_REPAIR_ATTEMPTS 2→3

- **Статус:** ToDo
- **Приоритет:** medium
- **Объём:** S
- **Зависит от:** —
- **Связанные документы:** `_docs/agent-loop.md` §2.4; `_docs/stack.md`.
- **Затрагиваемые файлы:** `.env.example`, `_docs/agent-loop.md`, `_docs/stack.md`, `tests/test_config.py`, `tests/agents/test_executor.py`, `tests/agents/test_roles_share_think.py`, `tests/test_dialog_memory.py`, `tests/test_multi_agent_e2e.py`.

#### Описание

Повышение дефолта `AGENT_MAX_REPAIR_ATTEMPTS` с 2 до 3 — больше шансов модели восстановить формат ответа. Обновить `.env.example`, `_docs/stack.md`, `_docs/agent-loop.md`, и все тесты с хардкодом `2`.

#### Definition of Done

- [ ] `.env.example`, `_docs/stack.md`, `_docs/agent-loop.md` — дефолт 3.
- [ ] Все тесты с хардкодом `agent_max_repair_attempts` обновлены.
- [ ] `pytest`, `flake8` зелёные.

### Задача 6.3. fix(tools): PDF с пустым паролем + GlitchTip Crons правка

- **Статус:** ToDo
- **Приоритет:** medium
- **Объём:** S
- **Зависит от:** —
- **Связанные документы:** `_docs/observability.md` §5.
- **Затрагиваемые файлы:** `app/tools/read_document.py`, `requirements.txt`, `_docs/observability.md`, `.github/workflows/test.yml`.

#### Описание

`ReadDocumentTool` — расшифровка PDF с пустым паролем через `reader.decrypt("")`. Добавить `cryptography` в `requirements.txt`. Правка `_docs/observability.md` — GlitchTip не поддерживает Sentry Crons API, heartbeat через логирование.

#### Definition of Done

- [ ] `read_document.py` — `reader.decrypt("")` для зашифрованных PDF.
- [ ] `cryptography` в `requirements.txt`.
- [ ] `_docs/observability.md` — правка про GlitchTip Crons.
- [ ] `flake8` зелёный.

---

## 10. Риски и смягчение

| # | Риск | Смягчение |
|---|------|-----------|
| 1 | Вложение — prompt injection (PDF/документ с инструкциями) | `read_document` возвращает данные как observation; `ResponseSanitizer` на выходе Executor; тело письма уже помечено как недоверенные данные. |
| 2 | Большой вложенный файл переполняет контекст | `read_document` уже имеет `MAX_DOCUMENT_CHARS`; `MAIL_BODY_MAX_CHARS` ограничивает тело. |
| 3 | Миграция схемы `scheduled_tasks` (новое поле `channel`) | `ALTER TABLE ADD COLUMN` с default `"telegram"` — существующие задачи не ломаются. |
| 4 | MAX notifier падает при пустом `MAX_BOT_TOKEN` | Проверка токена при создании notifier; fallback на логирование. |
| 5 | Console notifier блокирует ввод пользователя | Не блокирует: вывод через `print` в отдельной задаче, не в REPL-цикле. |
| 6 | disk_upload — большой файл превышает лимит API | Лимит на размер файла (`TELEGRAM_MAX_FILE_MB`); проверка перед upload. |
| 7 | Парсер времени не покрывает все паттерны | Fallback на LLM (скилл `scheduler`); парсер расширяется итеративно. |
| 8 | Bot-команды конфликтуют с existing handlers | Регистрация в `CommandRegistry` до `messages.router`; тесты на приоритет. |

## 11. Сводная таблица задач спринта

| #   | Задача | Приоритет | Объём | Статус | Зависит от |
|-----|--------|:---------:|:-----:|:------:|:----------:|
| 1.1 | Сохранение вложений и возврат file_id | high | M | Done | — |
| 2.1 | Убрать Crons API, оставить heartbeat-логирование | high | S | Done | — |
| 2.2 | Доставка планировщика в console и MAX | high | M | Done | 2.1 |
| 3.1 | Скилл email_draft — черновик ответа на письмо | medium | M | Done | 1.1 |
| 3.2 | disk_upload — загрузка файлов на Яндекс.Диск | medium | M | Done | — |
| 4.1 | Bot-команды /schedule / /schedules | medium | M | Done | 2.2 |
| 4.2 | Естественный парсер времени в cron | medium | M | Done | — |
| 5.1 | Демо скриншоты | low | S | ToDo | 1.1, 2.2, 3.1, 4.1 |
| 5.2 | Актуализация _docs, roadmap, README + гейты | medium | M | ToDo | 1.1, 2.1, 2.2, 3.1, 3.2, 4.1, 4.2, 5.1 |
| 6.1 | fix(protocol): final_answer + thought — валидный финал | high | S | ToDo | — |
| 6.2 | chore(config): AGENT_MAX_REPAIR_ATTEMPTS 2→3 | medium | S | ToDo | — |
| 6.3 | fix(tools): PDF с пустым паролем + GlitchTip Crons правка | medium | S | ToDo | — |

> Обновляется при каждом переходе статуса и при добавлении/удалении задач.

## 12. История изменений спринта

- **2026-07-24** — спринт открыт, ветка `feature/15-mail-disk-scheduler-ext` создана от `main` (`cafc1d40c`).
- **2026-07-24** — задача 1.1 закрыта: `_extract_body` возвращает `(body, attachments)`, `_save_attachments` сохраняет в `data/tmp/` + `FileIdMapper`, `email_read` возвращает `attachments` с `file_id`, скилл `email-assistant` обновлён, 6 новых тестов в `tests/services/test_mail.py`.
- **2026-07-24** — задача 2.1 закрыта: `_cron_checkin` убран из `scheduler_runner.py`, заменён на heartbeat-логирование через `logger.info`, тесты обновлены.
- **2026-07-24** — задача 2.2 закрыта: `make_console_notifier` и `make_max_notifier` реализованы, `ScheduledTask.channel` добавлен, `schedule_task` tool принимает `channel`, scheduler запускается в `console_main.py` и `max_main.py`, тесты обновлены.
- **2026-07-24** — задача 3.1 закрыта: скилл `email_draft` создан (`app/skills/email_draft/SKILL.md`), `_docs/skills.md`, `_docs/current-state.md` §1.9, `_docs/roadmap.md` Этап 7 и 16 обновлены.
- **2026-07-24** — задача 3.2 закрыта: `YandexDiskReader.upload` реализован, `DiskUploadTool` создан и зарегистрирован в `main.py`, 4 новых теста в `test_yandex_disk.py`, документация обновлена.
- **2026-07-24** — задача 4.1 закрыта: команды `/schedule` и `/schedules` реализованы в `CommandRegistry`, `scheduler` добавлен в `CommandContext` и проброшен через все адаптеры, 9 новых тестов, `_docs/commands.md` обновлён.
- **2026-07-24** — задача 4.2 закрыта: `app/services/cron_parser.py` создан (8 паттернов + fallback), 19 тестов, скилл `scheduler` и `_docs/scheduler.md` обновлены, `_docs/roadmap.md` Этап 18 отмечен.
- **2026-07-25** — этап 6 добавлен: техдолг из до-спринтного stash оформлен как задачи 6.1 (protocol fix), 6.2 (repair_attempts 2→3), 6.3 (PDF decrypt + GlitchTip правка).
