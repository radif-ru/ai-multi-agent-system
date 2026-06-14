# Спринт 11. Производительность и эффективность LLM

- **Источник:** ТЗ пользователя (жалоба на долгие ответы агента + просьба оптимизировать под мощную систему и большие документы); `_docs/current-state.md` §3 (нюансы цикла, recovery, общий `OllamaClient`); `_docs/roadmap.md` Этап 2 (стриминг — вынесен в non-goals).
- **Ветка:** `feature/11-performance` (от `main`; см. `_board/process.md` §2, п.2).
- **Открыт:** 2026-06-10
- **Закрыт:** —

## 1. Цель спринта

Сократить время ответа агента в **разы** без потери качества и без перерасхода ресурсов. Диагностика (бенчмарк на RTX 5090, без конкуренции за GPU) показала, что главный пожиратель латентности — **reasoning-токены «думающей» модели** `qwen3.5:4b`, которые Ollama к тому же **выбрасывает** из `content`: цикл агента из 5 шагов занимает `35.5s` при think-on против `3.4s` при think-off (~10x). Усугубляют картину: конкуренция live-запросов с фоновым `journal_recovery` (наблюдалось зависание запроса на 197с), «шторм» восстановления 11+ висящих сессий на каждом старте, отсутствие `keep_alive` (холодная перезагрузка модели) и не вынесенные в `.env` параметры.

Спринт приводит конфигурацию в баланс «мощная система + большие многостраничные документы», выносит захардкоженные настройки в `.env`, устраняет конкуренцию за LLM и чинит recovery. Дополнительно закрывает мелкий долг по надёжной остановке процессов (lightweight-вариант вместо тяжёлой process-group архитектуры).

## 2. Скоуп и non-goals

### В скоупе

- Управление reasoning-токенами (`think`) на уровне `OllamaClient` и всех ролей (executor, summarizer, planner, critic).
- Сериализация/приоритизация доступа к Ollama (gate), снижение конкуренции live vs recovery.
- Починка `journal_recovery`: пропуск мусорных сессий, отложенный старт, ограничение параллелизма, одноразовая зачистка backlog.
- Тюнинг Ollama: `keep_alive`, `temperature`, согласование `num_ctx` и порога суммаризации под большие документы.
- Редизайн `.env` / `.env.example`: порядок, описания, новые ключи, балансные значения под RTX 5090.
- VRAM-гард при выборе тяжёлых моделей через `/model`.
- Lightweight-надёжность остановки: `scripts/run.sh` (trap), bounded shutdown, добивание дочернего `curl`.
- Наблюдаемость производительности: `out_tok`, `tok_per_s`, `think`, `queue_wait_ms` в логах.

### Вне скоупа (non-goals)

- **Стриминг ответа Ollama** (`_docs/roadmap.md` Этап 2) — отдельный UX-этап, зависит от stream-индикации шагов; не нужен после ~10x от think-off. Остаётся кандидатом в roadmap.
- Полноценная process-group / daemon-executor архитектура в коде — оверинжиниринг для текущего риска (см. Этап 6, выбран lightweight-вариант).
- Capability-graph multi-agent, внешние онлайн-LLM, webhook (roadmap Этапы 3–6).
- Смена модели по умолчанию или удаление тяжёлых моделей из `OLLAMA_AVAILABLE_MODELS` (только предупреждение).

## 3. Acceptance Criteria спринта

- [ ] Время ответа на типовой запрос сокращено в разы: цикл агента 5 шагов на `qwen3.5:4b` — единицы секунд (замер до/после зафиксирован).
- [ ] `think` управляется через `.env` (`OLLAMA_THINK`), по умолчанию выключен для агентного цикла и суммаризации; все роли используют общий клиент корректно.
- [ ] Фоновый `journal_recovery` не конкурирует с live-запросами и не «штормит»: мусорные сессии пропускаются, backlog не растёт между рестартами.
- [ ] Ollama-параметры (`keep_alive`, `temperature`, `num_ctx`) и порог суммаризации согласованы под большие документы; новые ключи доступны в `.env`.
- [ ] `.env.example` переоформлен (порядок, описания, новые ключи) и синхронизирован с `app/config.py`; локальный `.env` пользователя обновлён.
- [ ] Остановка приложения завершается без зависаний; есть `scripts/run.sh`.
- [ ] Все задачи спринта — `Done`, сводная таблица актуальна; `pytest -q` и `flake8 app tests` зелёные.

## 4. Этап 1. Управление reasoning-токенами (think)

Главный рычаг (~7–11x). `OllamaClient` получает флаг `think`; все роли наследуют его через общий клиент. Reasoning у агента и так выражен структурным полем `thought`, а `<think>` Ollama отбрасывает.

### Задача 1.1. Флаг `think` в `OllamaClient.chat` + настройка `OLLAMA_THINK`

- **Статус:** Done
- **Приоритет:** high
- **Объём:** S
- **Зависит от:** —
- **Связанные документы:** `_docs/architecture.md` §3.4; `_docs/stack.md` §9.
- **Затрагиваемые файлы:** `app/services/llm.py`, `app/config.py`, `app/main.py` (DI клиента).

#### Описание

`ollama` (0.6.2) поддерживает `think` нативно. Добавить:

1. В `Settings` — `ollama_think: bool = False` (env `OLLAMA_THINK`).
2. В `OllamaClient.__init__` — параметр `think: bool = False`, в `chat(...)` передавать `think=self._think` (с опциональным per-call override `think: bool | None = None` на будущее).
3. В `app/main.py` при создании `OllamaClient` пробросить `think=settings.ollama_think`.
4. `embed` не трогаем.

#### Definition of Done

- [x] `OLLAMA_THINK` управляет передачей `think` в Ollama; default `false`.
- [x] Smoke: при `false` ответ на короткий запрос приходит за доли секунды (зафиксировано в диагностике спринта §1: 5 шагов think-off `~3.4s` против think-on `35.5s` на RTX 5090).
- [x] **Документация обновлена**: `_docs/architecture.md` §3.4 (упоминание think), `_docs/stack.md` §9 (новый ключ).
- [x] **Тесты**: `tests/services/test_llm_client.py` — `think` прокидывается в мок-клиент; `pytest -q` зелёный.
- [x] `git status` чист.

### Задача 1.2. Все роли (executor/summarizer/planner/critic) учитывают think + замер

- **Статус:** Done
- **Приоритет:** high
- **Объём:** S
- **Зависит от:** Задача 1.1
- **Связанные документы:** `_docs/agent-loop.md`; `_docs/multi-agent.md`.
- **Затрагиваемые файлы:** `app/agents/executor.py`, `app/services/summarizer.py`, `app/agents/planner.py`, `app/agents/critic.py` (проверка, что используют общий клиент), `_docs/current-state.md`.

#### Описание

Все роли вызывают общий `OllamaClient`, поэтому think наследуется автоматически — задача: убедиться в этом тестом, зафиксировать замер до/после в `_docs/current-state.md` §6 (история) или §3.

#### Definition of Done

- [x] Тест подтверждает, что executor/summarizer/planner/critic идут через общий клиент с актуальным think (`tests/agents/test_roles_share_think.py`).
- [x] Замер «5 шагов think on vs off» задокументирован (`current-state.md` §3: `~35.5s` vs `~3.4s`).
- [x] **Документация обновлена**: `_docs/current-state.md`.
- [x] **Тесты**: `pytest tests/agents -q` зелёный.
- [x] `git status` чист.

## 5. Этап 2. Сериализация и приоритет доступа к LLM

Устранить пайл-апы (live + recovery), вызывавшие зависания до ~200с.

### Задача 2.1. Общий gate на LLM-вызовы + `queue_wait_ms`

- **Статус:** Done
- **Приоритет:** high
- **Объём:** M
- **Зависит от:** —
- **Связанные документы:** `_docs/architecture.md` §3.4; `_docs/observability.md`.
- **Затрагиваемые файлы:** `app/services/llm.py`, `app/config.py`.

#### Описание

1. `Settings.llm_max_concurrency: int = 2` (env `LLM_MAX_CONCURRENCY`; на 5090 две параллельные сессии к 4b с `num_ctx=32768` (~14 ГБ KV) умещаются в 24 ГБ).
2. В `OllamaClient` — внутренний `asyncio.Semaphore(llm_max_concurrency)`, оборачивающий `chat`/`embed`; замерять время ожидания в очереди и логировать `queue_wait_ms`.

#### Definition of Done

- [x] Конкурентные вызовы ограничены семафором; `queue_wait_ms` в `external.ok/fail`.
- [x] **Документация обновлена**: `_docs/architecture.md` §3.4, `_docs/observability.md` (+ `stack.md` §9 — новый ключ).
- [x] **Тесты**: семафор сериализует вызовы и уважает лимит, `queue_wait_ms` логируется (мок); `pytest -q` зелёный.
- [x] `git status` чист.

### Задача 2.2. Приоритет live над фоновым recovery

- **Статус:** Done
- **Приоритет:** high
- **Объём:** M
- **Зависит от:** Задача 2.1
- **Связанные документы:** `_docs/memory.md` §4.
- **Затрагиваемые файлы:** `app/services/journal_recovery.py`, `app/config.py`.

#### Описание

Recovery не должен занимать все слоты LLM. Ограничить его собственным лимитом (`JOURNAL_RECOVERY_CONCURRENCY=1`) и обрабатывать сессии последовательно с короткой паузой, оставляя слот для live-запросов.

#### Definition of Done

- [x] Recovery использует не более 1 слота; live-запрос не ждёт весь backlog (семафор `JOURNAL_RECOVERY_CONCURRENCY=1` + общий LLM-gate из 2.1).
- [x] **Документация обновлена**: `_docs/memory.md` §4 (+ `stack.md` §9 — новый ключ).
- [x] **Тесты**: `concurrency=1` сериализует сессии, `concurrency=2` уважает лимит (мок LLM/journal); `pytest -q` зелёный.
- [x] `git status` чист.

## 6. Этап 3. Починка `journal_recovery`

11+ висящих сессий (часть мусорные: 1 строка, 6–24 символа) гоняются через LLM на каждом старте и не закрываются. Чиним.

### Задача 3.1. Пропуск мусорных сессий (`JOURNAL_RECOVERY_MIN_CHARS`)

- **Статус:** Done
- **Приоритет:** high
- **Объём:** S
- **Зависит от:** —
- **Связанные документы:** `_docs/memory.md` §4.
- **Затрагиваемые файлы:** `app/services/journal_recovery.py`, `app/config.py`, `app/main.py`, `app/max_main.py`.

#### Описание

`Settings.journal_recovery_min_chars: int = 50`. Сессии с суммарным `content` меньше порога — `mark_archived` без LLM-суммаризации (нечего архивировать), чтобы они не повторялись.

#### Definition of Done

- [x] Мусорные сессии помечаются archived без LLM-вызова.
- [x] **Документация обновлена**: `_docs/memory.md` §4 (+ `stack.md` §9 — новый ключ).
- [x] **Тесты**: сессия < порога не вызывает summarizer; `pytest -q` зелёный.
- [x] `git status` чист.

### Задача 3.2. Отложенный старт recovery

- **Статус:** Done
- **Приоритет:** medium
- **Объём:** S
- **Зависит от:** Задача 3.1
- **Связанные документы:** `_docs/memory.md` §4.
- **Затрагиваемые файлы:** `app/services/journal_recovery.py`, `app/config.py`, `app/main.py`, `app/max_main.py`.

#### Описание

`Settings.journal_recovery_start_delay: float = 20.0` — пауза перед запуском recovery, чтобы не штормить Ollama сразу после старта (когда пользователь активен).

#### Definition of Done

- [x] Recovery стартует после задержки; значение настраивается.
- [x] **Документация обновлена**: `_docs/memory.md` §4 (+ `stack.md` §9 — новый ключ).
- [x] **Тесты**: `pytest -q` зелёный.
- [x] `git status` чист.

### Задача 3.3. Одноразовая зачистка текущего backlog

- **Статус:** Done
- **Приоритет:** medium
- **Объём:** S
- **Зависит от:** Задача 3.1
- **Связанные документы:** `_docs/memory.md` §4.
- **Затрагиваемые файлы:** `scripts/recover_backlog.py` (новый maintenance-скрипт).

#### Описание

Прогнать починенный recovery на текущей `data/memory.db`, убедиться, что backlog схлопнулся (мусор закрыт, реальные сессии заархивированы), и не растёт между рестартами.

#### Definition of Done

- [x] `pending` сессий не растёт между двумя рестартами (ручная проверка по sqlite). Прогон `python -m scripts.recover_backlog`: `pending` 11 → 0 (`sessions=11 archived=11 failed=0`; 6 мусорных закрыты без LLM, 5 реальных заархивированы), повторный прогон находит 0.
- [x] **Документация**: короткая заметка в `_docs/memory.md` §4.4 про `scripts/recover_backlog.py`.
- [x] **Тесты**: `n/a` (одноразовая операция; поведение покрыто 3.1/3.2).
- [x] `git status` чист (БД не коммитим).

## 7. Этап 4. Тюнинг Ollama и редизайн `.env`

Баланс под RTX 5090 (24 ГБ) и большие многостраничные документы.

### Задача 4.1. `OLLAMA_KEEP_ALIVE` и `OLLAMA_TEMPERATURE`

- **Статус:** Done
- **Приоритет:** high
- **Объём:** S
- **Зависит от:** —
- **Связанные документы:** `_docs/architecture.md` §3.4; `_docs/stack.md` §9.
- **Затрагиваемые файлы:** `app/services/llm.py`, `app/config.py`, `app/main.py`.

#### Описание

1. `Settings.ollama_keep_alive: str = "30m"` (env `OLLAMA_KEEP_ALIVE`) — держать модель резидентной между сообщениями (на 24 ГБ безопасно), убрать холодные перезагрузки.
2. `Settings.ollama_temperature: float = 0.0` (env `OLLAMA_TEMPERATURE`) — вынести из хардкода.
3. Пробросить оба в `OllamaClient.chat` (`keep_alive`, `options.temperature`).

#### Definition of Done

- [x] `keep_alive`/`temperature` управляются из `.env`; `ollama ps` показывает резидентную модель между запросами (`keep_alive` пробрасывается в каждый `chat`).
- [x] **Документация обновлена**: `_docs/architecture.md` §3.4, `_docs/stack.md` §9.
- [x] **Тесты**: значения прокидываются (мок); `pytest -q` зелёный.
- [x] `git status` чист.

### Задача 4.2. Согласовать `num_ctx` и порог суммаризации под документы

- **Статус:** Done
- **Приоритет:** medium
- **Объём:** S
- **Зависит от:** —
- **Связанные документы:** `_docs/memory.md` §3.3; `_docs/agent-loop.md` §4.
- **Затрагиваемые файлы:** `app/config.py` (дефолты), `.env`, `.env.example`.

#### Описание

Сейчас `OLLAMA_NUM_CTX=32768`, но `AGENT_MAX_CONTEXT_CHARS=50000` (~12.5k токенов) суммаризирует документ **раньше**, чем используется контекст. Для больших документов это теряет факты. Поднять `AGENT_MAX_CONTEXT_CHARS` (предложение `~90000`, ниже ёмкости 32k ctx с запасом на system+ответ) и согласовать `MAX_DOCUMENT_CHARS` (предложение `~80000`). `num_ctx=32768` оставить (умещается в VRAM, prefill быстрый). Значения тюнингуемые, зафиксировать обоснование.

#### Definition of Done

- [x] Большой документ попадает в контекст без преждевременной суммаризации: дефолты согласованы (`MAX_DOCUMENT_CHARS=80000` < `AGENT_MAX_CONTEXT_CHARS=90000` ≈ 22.5k токенов < ёмкости `OLLAMA_NUM_CTX=32768`), связь зафиксирована тестом `test_context_document_defaults_balanced`. Живой smoke на PDF/TXT — за пользователем (нужна запущенная модель).
- [x] **Документация обновлена**: `_docs/agent-loop.md` §4 (баланс контекста); синхронизированы устаревшие упоминания `default 8000` в `architecture.md`, `current-state.md`, `README.md`.
- [x] **Тесты**: `test_context_document_defaults_balanced` (изолированный env) + `pytest -q` зелёный. Жёсткий cross-validator намеренно не добавлен — реальный `.env` читается в `test_summarizer_subscriber.py`, валидатор мог бы упасть.
- [x] `git status` чист.

### Задача 4.3. Редизайн `.env.example` + синхронизация локального `.env`

- **Статус:** Done
- **Приоритет:** high
- **Объём:** M
- **Зависит от:** Задача 1.1, 2.1, 4.1 (новые ключи должны существовать в `Settings`)
- **Связанные документы:** `_docs/stack.md` §9; `_docs/instructions.md` (секреты).
- **Затрагиваемые файлы:** `.env.example` (коммитим), `.env` (локально, НЕ коммитим).

#### Описание

Переоформить `.env.example`: логичный порядок секций, понятные описания, добавить новые ключи (`OLLAMA_THINK`, `OLLAMA_KEEP_ALIVE`, `OLLAMA_TEMPERATURE`, `LLM_MAX_CONCURRENCY`, `JOURNAL_RECOVERY_MIN_CHARS`, `JOURNAL_RECOVERY_START_DELAY`, `JOURNAL_RECOVERY_CONCURRENCY`). Балансные значения под RTX 5090 + большие документы (см. задачи выше). Синхронно обновить локальный `.env` пользователя теми же значениями.

Предлагаемые балансные значения:

```
OLLAMA_THINK=false
OLLAMA_KEEP_ALIVE=30m
OLLAMA_TEMPERATURE=0.0
OLLAMA_NUM_CTX=32768
OLLAMA_TIMEOUT=180
LLM_MAX_CONCURRENCY=2
AGENT_MAX_STEPS=10
AGENT_MAX_CONTEXT_CHARS=90000
MAX_DOCUMENT_CHARS=80000
JOURNAL_RECOVERY_MIN_CHARS=50
JOURNAL_RECOVERY_START_DELAY=20
JOURNAL_RECOVERY_CONCURRENCY=1
```

#### Definition of Done

- [x] `.env.example` переоформлен, все ключи `Settings` представлены (проверка: `Settings.model_fields` → все в `.env.example`, MISSING: none), описания актуальны, добавлены секции «LLM gate» и «Journal recovery».
- [x] Локальный `.env` обновлён безопасным in-place скриптом (только балансные ключи, токен не тронут): `OLLAMA_TIMEOUT 120→180`, `AGENT_MAX_CONTEXT_CHARS 50000→90000`, `MAX_DOCUMENT_CHARS 50000→80000`, добавлены `OLLAMA_THINK/KEEP_ALIVE/TEMPERATURE`, `LLM_MAX_CONCURRENCY`, `JOURNAL_RECOVERY_*`. `Settings()` грузится без ошибок.
- [x] **Документация обновлена**: `_docs/stack.md` §9 (новые ключи `OLLAMA_KEEP_ALIVE`/`OLLAMA_TEMPERATURE` добавлены в 4.1; `LLM_MAX_CONCURRENCY`/`JOURNAL_RECOVERY_*` уже присутствовали).
- [x] **Тесты**: `n/a` (конфиг-файлы); `Settings()` грузится без ошибок, completeness-проверка ключей зелёная.
- [x] `git status` чист (`.env` не коммитится — в `.gitignore`).

### Задача 4.4. Сериализовать sqlite-доступ в `DialogJournal` (фикс гонки recovery)

- **Статус:** Done
- **Приоритет:** high
- **Объём:** S
- **Зависит от:** — (фикс латентного бага, обнаруженного в 4.3; см. `_docs/current-state.md` §2.3)
- **Связанные документы:** `_docs/current-state.md` §2.3; `_docs/memory.md` §4.4.
- **Затрагиваемые файлы:** `app/services/dialog_journal.py`, `tests/services/test_dialog_journal.py`.

#### Описание

`DialogJournal` держит одно `sqlite3.Connection`, а методы оборачиваются в `asyncio.to_thread`. При `JOURNAL_RECOVERY_CONCURRENCY > 1` несколько корутин одновременно бьют в соединение из разных потоков пула → `SQLITE_MISUSE` (флак `test_concurrency_respects_configured_limit`). Добавить `threading.Lock`, охватывающий тело sync-методов (`append`/`pending`/`read_conversation`/`mark_archived`), чтобы доступ к соединению сериализовался и `concurrency > 1` стал безопасным.

#### Definition of Done

- [x] Конкурентный доступ к `DialogJournal` не вызывает `SQLITE_MISUSE`: `threading.Lock` в `_*_sync`-методах; `test_concurrency_respects_configured_limit` зелёный 10/10 прогонов.
- [x] **Документация обновлена**: `_docs/current-state.md` §2.3 (статус → исправлено), `_docs/memory.md` §4.4.
- [x] **Тесты**: регрессионный `test_concurrent_access_does_not_misuse_sqlite`; `pytest -q` зелёный.
- [x] `git status` чист.

## 8. Этап 5. VRAM-гард для тяжёлых моделей

Переключение на `qwen3.6:35b` (23 ГБ) / `gpt-oss:20b` (13 ГБ) вызывает выгрузку/CPU-оффлоад. Предупреждаем.

### Задача 5.1. Предупреждение и размеры моделей в `/model` / `/models`

- **Статус:** ToDo
- **Приоритет:** low
- **Объём:** M
- **Зависит от:** —
- **Связанные документы:** `_docs/commands.md`.
- **Затрагиваемые файлы:** `app/commands/registry.py`, при необходимости `app/services/llm.py` (запрос `ollama list`).

#### Описание

В выводе `/models` показывать размер модели; при выборе модели через `/model`, если её размер близок/превышает свободный VRAM — мягкое предупреждение о возможной деградации скорости. Без жёсткого запрета.

#### Definition of Done

- [ ] `/models` показывает размеры; `/model <heavy>` выводит предупреждение.
- [ ] **Документация обновлена**: `_docs/commands.md`.
- [ ] **Тесты**: `pytest -q` зелёный (мок ollama list).
- [ ] `git status` чист.

## 9. Этап 6. Надёжная остановка (lightweight)

Вместо тяжёлой process-group архитектуры — минимальные меры: гарантированный выход и launcher.

### Задача 6.1. `scripts/run.sh` с trap

- **Статус:** ToDo
- **Приоритет:** medium
- **Объём:** S
- **Зависит от:** —
- **Связанные документы:** `README.md`.
- **Затрагиваемые файлы:** `scripts/run.sh` (новый), `README.md`.

#### Описание

Bash-launcher: запускает бот в собственной группе процессов, `trap` на `INT/TERM` валит всю группу (`kill -- -$$`), опционально поднимает/останавливает `ollama serve`. Решает «остановил → всё завершилось» без правок Python-архитектуры.

#### Definition of Done

- [ ] `scripts/run.sh` запускает бот; Ctrl+C завершает всё дерево; нет orphan-процессов (ручная проверка `ps`).
- [ ] **Документация обновлена**: `README.md` (раздел запуска).
- [ ] **Тесты**: `n/a` (shell-скрипт).
- [ ] `git status` чист.

### Задача 6.2. Bounded shutdown + добивание дочернего `curl`

- **Статус:** ToDo
- **Приоритет:** medium
- **Объём:** M
- **Зависит от:** —
- **Связанные документы:** `_docs/current-state.md` §3.
- **Затрагиваемые файлы:** `app/main.py`, `app/max_main.py`, `app/console_main.py`, `app/tools/weather.py`.

#### Описание

1. Обернуть `_shutdown_components` (и ожидание дефолтного executor) таймаутом, чтобы выход не висел на потоках `to_thread` (whisper/sqlite).
2. В `weather.py` гарантировать `process.kill()` при отмене/исключении, чтобы `curl` не оставался.

#### Definition of Done

- [ ] Остановка завершается за ограниченное время даже при активной транскрипции (smoke).
- [ ] `curl` не остаётся после отмены запроса погоды.
- [ ] **Документация обновлена**: `_docs/current-state.md` §3.
- [ ] **Тесты**: weather убивает подпроцесс при отмене (мок); `pytest -q` зелёный.
- [ ] `git status` чист.

## 10. Этап 7. Наблюдаемость производительности

Чтобы ловить регрессии скорости.

### Задача 7.1. Метрики генерации в `external.ok` LLM

- **Статус:** ToDo
- **Приоритет:** medium
- **Объём:** S
- **Зависит от:** Задача 1.1
- **Связанные документы:** `_docs/observability.md`.
- **Затрагиваемые файлы:** `app/services/llm.py`.

#### Описание

Логировать в `external.ok` (и где применимо `external.fail`): `out_tok` (eval_count), `tok_per_s`, `think`, `queue_wait_ms`. Поля Ollama доступны в ответе (`eval_count`, `eval_duration`).

#### Definition of Done

- [ ] Лог LLM содержит `out_tok`/`tok_per_s`/`think`/`queue_wait_ms`.
- [ ] **Документация обновлена**: `_docs/observability.md`.
- [ ] **Тесты**: формат лог-записи покрыт (мок); `pytest -q` зелёный.
- [ ] `git status` чист.

## 11. Риски и смягчение

| # | Риск | Смягчение |
|---|------|-----------|
| 1 | `think=off` снижает качество на сложных задачах | Флаг конфигурируем; структурный `thought` сохраняет рассуждение; можно включать на DEEP/per-role в будущем |
| 2 | `LLM_MAX_CONCURRENCY>1` + большой `num_ctx` → нехватка VRAM | Дефолт 2 при 24 ГБ безопасен (≈14 ГБ KV для 2× qwen4b@32k); значение тюнингуемо |
| 3 | Поднятый `AGENT_MAX_CONTEXT_CHARS` замедлит prefill на огромных документах | prefill быстрый (≈0.6с на 1.8k токенов); суммаризация остаётся как fallback; значение тюнингуемо |
| 4 | `keep_alive` держит VRAM занятым | На 24 ГБ приемлемо; значение настраивается, можно `0` для освобождения |
| 5 | Зачистка backlog затронет реальные сессии | Порог только по очень малому `content`; реальные сессии архивируются, а не удаляются |
| 6 | Изменение `.env` сломает запуск | `Settings()` грузится в smoke; `.env.example` синхронизирован; `.env` не коммитим |

## 12. Сводная таблица задач спринта

| #   | Задача | Приоритет | Объём | Статус | Зависит от |
|-----|--------|:---------:|:-----:|:------:|:----------:|
| 1.1 | Флаг `think` в `OllamaClient` + `OLLAMA_THINK` | high | S | Done | — |
| 1.2 | Все роли учитывают think + замер | high | S | Done | 1.1 |
| 2.1 | Общий gate на LLM + `queue_wait_ms` | high | M | Done | — |
| 2.2 | Приоритет live над recovery | high | M | Done | 2.1 |
| 3.1 | Пропуск мусорных сессий recovery | high | S | Done | — |
| 3.2 | Отложенный старт recovery | medium | S | Done | 3.1 |
| 3.3 | Зачистка текущего backlog | medium | S | Done | 3.1 |
| 4.1 | `OLLAMA_KEEP_ALIVE` / `OLLAMA_TEMPERATURE` | high | S | Done | — |
| 4.2 | Согласовать `num_ctx` и порог суммаризации | medium | S | Done | — |
| 4.3 | Редизайн `.env.example` + синх `.env` | high | M | Done | 1.1, 2.1, 4.1 |
| 4.4 | Сериализовать sqlite-доступ в `DialogJournal` | high | S | Done | — |
| 5.1 | VRAM-гард в `/model` / `/models` | low | M | ToDo | — |
| 6.1 | `scripts/run.sh` с trap | medium | S | ToDo | — |
| 6.2 | Bounded shutdown + добивание `curl` | medium | M | ToDo | — |
| 7.1 | Метрики генерации в логах LLM | medium | S | ToDo | 1.1 |

> Обновляется при каждом переходе статуса и при добавлении/удалении задач.

## 13. История изменений спринта

- **2026-06-10** — спринт открыт, ветка `feature/11-performance` создана от `main`.
- **2026-06-10** — закрыта задача 1.1: флаг `think` в `OllamaClient.chat` (+ per-call override) и настройка `OLLAMA_THINK` (default `false`), проброс в `app/main.py`, нижняя граница `ollama>=0.5`; документация (`architecture.md` §3.4, `stack.md` §9) и тесты обновлены.
- **2026-06-10** — закрыта задача 1.2: тест `tests/agents/test_roles_share_think.py` подтверждает наследование `think` всеми ролями через общий `OllamaClient`; замер think on/off зафиксирован в `current-state.md` §3.
- **2026-06-10** — закрыта задача 2.1: общий `asyncio.Semaphore`-gate в `OllamaClient` (`LLM_MAX_CONCURRENCY`, default 2) на `chat`/`embed` + метрика `queue_wait_ms` в `external.ok/fail`; доки (`architecture.md` §3.4, `observability.md`, `stack.md` §9) и тесты обновлены.
- **2026-06-10** — закрыта задача 2.2: `recover_pending_journals` ограничен `JOURNAL_RECOVERY_CONCURRENCY` (default 1, семафор на обработку сессии), чтобы фоновое восстановление оставляло слот под live-запрос; доки (`memory.md` §4.4, `stack.md` §9) и тесты обновлены. **Этап 2 завершён.**
- **2026-06-14** — закрыта задача 3.1: `recover_pending_journals(min_chars=0)` пропускает «мусорные» сессии с суммарным `content` ниже `JOURNAL_RECOVERY_MIN_CHARS` (env, default 50, валидатор `>=0`) — `mark_archived` без LLM-вызова; проброс в `app/main.py` и `app/max_main.py`; доки (`memory.md` §4.4, `stack.md` §9) и тесты обновлены.
- **2026-06-14** — закрыта задача 3.2: `recover_pending_journals(start_delay=0.0)` выдерживает паузу `JOURNAL_RECOVERY_START_DELAY` (env, default 20с, валидатор `>=0`) через `asyncio.sleep` перед обходом сессий, чтобы не штормить Ollama на старте; проброс в `app/main.py` и `app/max_main.py`; доки (`memory.md` §4.4, `stack.md` §9) и тесты обновлены.
- **2026-06-14** — закрыта задача 3.3: добавлен maintenance-скрипт `scripts/recover_backlog.py` (переиспользует `_build_components` + `recover_pending_journals`, глушит httpcore/httpx, печатает итог баннером). Прогон на боевой `data/memory.db`: `pending` 11 → 0 (`sessions=11 archived=11 failed=0`; 6 мусорных закрыты без LLM, 5 реальных заархивированы). Заметка в `memory.md` §4.4. **Этап 3 завершён.**
- **2026-06-14** — закрыта задача 4.1: `OllamaClient` принимает `temperature` и `keep_alive`, оба пробрасываются в каждый `chat` (`keep_alive`-аргумент + `options.temperature`); вынесены в `.env` как `OLLAMA_TEMPERATURE` (default `0.0`) и `OLLAMA_KEEP_ALIVE` (default `30m`), проброс в `app/main.py`; `chat(temperature=None)` берёт значение из конструктора с per-call override; доки (`architecture.md` §3.4, `stack.md` §9) и тесты (`test_llm_client.py`, `test_config.py`) обновлены.
- **2026-06-14** — закрыта задача 4.2: дефолты согласованы под большие документы — `OLLAMA_NUM_CTX` `8192→32768`, `AGENT_MAX_CONTEXT_CHARS` `8000→90000`, `MAX_DOCUMENT_CHARS` `50000→80000` (документ умещается в контекст без преждевременной суммаризации); обоснование баланса в `agent-loop.md` §4, синхронизированы устаревшие `default 8000` в `architecture.md`/`current-state.md`/`README.md`; тест `test_context_document_defaults_balanced`. Жёсткий cross-validator не добавлен (реальный `.env` читается тестом `test_summarizer_subscriber.py`).
- **2026-06-14** — закрыта задача 4.3: `.env.example` переоформлен (секции «LLM gate», «Journal recovery», все ключи `Settings` представлены — completeness-проверка `MISSING: none`, балансные значения под RTX 5090); локальный `.env` синхронизирован безопасным in-place скриптом (токен не тронут, `.env` не коммитим). Попутно обнаружен и зафиксирован (`current-state.md` §2.3) латентный баг: гонка одного sqlite-соединения `DialogJournal` при `JOURNAL_RECOVERY_CONCURRENCY>1` → флак `test_concurrency_respects_configured_limit` (SQLITE_MISUSE); продакшен-дефолт `concurrency=1` безопасен.
- **2026-06-14** — добавлена и закрыта задача 4.4 (фикс бага из §2.3): доступ к sqlite-соединению `DialogJournal` сериализован `threading.Lock`-ом в `_*_sync`-методах, `JOURNAL_RECOVERY_CONCURRENCY>1` теперь безопасен; ранее флакавший `test_concurrency_respects_configured_limit` зелёный 10/10, добавлен регрессионный `test_concurrent_access_does_not_misuse_sqlite`; доки `current-state.md` §2.3 (→ исправлено) и `memory.md` §4.4. **Этап 4 завершён.**
