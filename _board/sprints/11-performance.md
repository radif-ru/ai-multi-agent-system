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

- **Статус:** ToDo
- **Приоритет:** high
- **Объём:** S
- **Зависит от:** Задача 1.1
- **Связанные документы:** `_docs/agent-loop.md`; `_docs/multi-agent.md`.
- **Затрагиваемые файлы:** `app/agents/executor.py`, `app/services/summarizer.py`, `app/agents/planner.py`, `app/agents/critic.py` (проверка, что используют общий клиент), `_docs/current-state.md`.

#### Описание

Все роли вызывают общий `OllamaClient`, поэтому think наследуется автоматически — задача: убедиться в этом тестом, зафиксировать замер до/после в `_docs/current-state.md` §6 (история) или §3.

#### Definition of Done

- [ ] Тест подтверждает, что executor/summarizer/planner/critic идут через общий клиент с актуальным think.
- [ ] Замер «5 шагов think on vs off» задокументирован.
- [ ] **Документация обновлена**: `_docs/current-state.md`.
- [ ] **Тесты**: `pytest tests/agents -q` зелёный.
- [ ] `git status` чист.

## 5. Этап 2. Сериализация и приоритет доступа к LLM

Устранить пайл-апы (live + recovery), вызывавшие зависания до ~200с.

### Задача 2.1. Общий gate на LLM-вызовы + `queue_wait_ms`

- **Статус:** ToDo
- **Приоритет:** high
- **Объём:** M
- **Зависит от:** —
- **Связанные документы:** `_docs/architecture.md` §3.4; `_docs/observability.md`.
- **Затрагиваемые файлы:** `app/services/llm.py`, `app/config.py`.

#### Описание

1. `Settings.llm_max_concurrency: int = 2` (env `LLM_MAX_CONCURRENCY`; на 5090 две параллельные сессии к 4b с `num_ctx=32768` (~14 ГБ KV) умещаются в 24 ГБ).
2. В `OllamaClient` — внутренний `asyncio.Semaphore(llm_max_concurrency)`, оборачивающий `chat`/`embed`; замерять время ожидания в очереди и логировать `queue_wait_ms`.

#### Definition of Done

- [ ] Конкурентные вызовы ограничены семафором; `queue_wait_ms` в `external.ok/fail`.
- [ ] **Документация обновлена**: `_docs/architecture.md` §3.4, `_docs/observability.md`.
- [ ] **Тесты**: семафор сериализует вызовы (мок); `pytest -q` зелёный.
- [ ] `git status` чист.

### Задача 2.2. Приоритет live над фоновым recovery

- **Статус:** ToDo
- **Приоритет:** high
- **Объём:** M
- **Зависит от:** Задача 2.1
- **Связанные документы:** `_docs/memory.md` §4.
- **Затрагиваемые файлы:** `app/services/journal_recovery.py`, `app/config.py`.

#### Описание

Recovery не должен занимать все слоты LLM. Ограничить его собственным лимитом (`JOURNAL_RECOVERY_CONCURRENCY=1`) и обрабатывать сессии последовательно с короткой паузой, оставляя слот для live-запросов.

#### Definition of Done

- [ ] Recovery использует не более 1 слота; live-запрос не ждёт весь backlog.
- [ ] **Документация обновлена**: `_docs/memory.md` §4.
- [ ] **Тесты**: `pytest -q` зелёный (мок LLM/journal).
- [ ] `git status` чист.

## 6. Этап 3. Починка `journal_recovery`

11+ висящих сессий (часть мусорные: 1 строка, 6–24 символа) гоняются через LLM на каждом старте и не закрываются. Чиним.

### Задача 3.1. Пропуск мусорных сессий (`JOURNAL_RECOVERY_MIN_CHARS`)

- **Статус:** ToDo
- **Приоритет:** high
- **Объём:** S
- **Зависит от:** —
- **Связанные документы:** `_docs/memory.md` §4.
- **Затрагиваемые файлы:** `app/services/journal_recovery.py`, `app/config.py`.

#### Описание

`Settings.journal_recovery_min_chars: int = 50`. Сессии с суммарным `content` меньше порога — `mark_archived` без LLM-суммаризации (нечего архивировать), чтобы они не повторялись.

#### Definition of Done

- [ ] Мусорные сессии помечаются archived без LLM-вызова.
- [ ] **Документация обновлена**: `_docs/memory.md` §4.
- [ ] **Тесты**: сессия < порога не вызывает summarizer; `pytest -q` зелёный.
- [ ] `git status` чист.

### Задача 3.2. Отложенный старт recovery

- **Статус:** ToDo
- **Приоритет:** medium
- **Объём:** S
- **Зависит от:** Задача 3.1
- **Связанные документы:** `_docs/memory.md` §4.
- **Затрагиваемые файлы:** `app/services/journal_recovery.py`, `app/config.py`.

#### Описание

`Settings.journal_recovery_start_delay: float = 20.0` — пауза перед запуском recovery, чтобы не штормить Ollama сразу после старта (когда пользователь активен).

#### Definition of Done

- [ ] Recovery стартует после задержки; значение настраивается.
- [ ] **Документация обновлена**: `_docs/memory.md` §4.
- [ ] **Тесты**: `pytest -q` зелёный.
- [ ] `git status` чист.

### Задача 3.3. Одноразовая зачистка текущего backlog

- **Статус:** ToDo
- **Приоритет:** medium
- **Объём:** S
- **Зависит от:** Задача 3.1
- **Связанные документы:** `_docs/memory.md` §4.
- **Затрагиваемые файлы:** `scripts/` (новый maintenance-скрипт) или одноразовая проверка.

#### Описание

Прогнать починенный recovery на текущей `data/memory.db`, убедиться, что backlog схлопнулся (мусор закрыт, реальные сессии заархивированы), и не растёт между рестартами.

#### Definition of Done

- [ ] `pending` сессий не растёт между двумя рестартами (ручная проверка по sqlite).
- [ ] **Документация**: `n/a` (maintenance) либо короткая заметка в `_docs/memory.md`.
- [ ] **Тесты**: `n/a` (одноразовая операция; поведение покрыто 3.1/3.2).
- [ ] `git status` чист (БД не коммитим).

## 7. Этап 4. Тюнинг Ollama и редизайн `.env`

Баланс под RTX 5090 (24 ГБ) и большие многостраничные документы.

### Задача 4.1. `OLLAMA_KEEP_ALIVE` и `OLLAMA_TEMPERATURE`

- **Статус:** ToDo
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

- [ ] `keep_alive`/`temperature` управляются из `.env`; `ollama ps` показывает резидентную модель между запросами.
- [ ] **Документация обновлена**: `_docs/architecture.md` §3.4, `_docs/stack.md` §9.
- [ ] **Тесты**: значения прокидываются (мок); `pytest -q` зелёный.
- [ ] `git status` чист.

### Задача 4.2. Согласовать `num_ctx` и порог суммаризации под документы

- **Статус:** ToDo
- **Приоритет:** medium
- **Объём:** S
- **Зависит от:** —
- **Связанные документы:** `_docs/memory.md` §3.3; `_docs/agent-loop.md` §4.
- **Затрагиваемые файлы:** `app/config.py` (дефолты), `.env`, `.env.example`.

#### Описание

Сейчас `OLLAMA_NUM_CTX=32768`, но `AGENT_MAX_CONTEXT_CHARS=50000` (~12.5k токенов) суммаризирует документ **раньше**, чем используется контекст. Для больших документов это теряет факты. Поднять `AGENT_MAX_CONTEXT_CHARS` (предложение `~90000`, ниже ёмкости 32k ctx с запасом на system+ответ) и согласовать `MAX_DOCUMENT_CHARS` (предложение `~80000`). `num_ctx=32768` оставить (умещается в VRAM, prefill быстрый). Значения тюнингуемые, зафиксировать обоснование.

#### Definition of Done

- [ ] Большой документ попадает в контекст без преждевременной суммаризации (smoke на тестовом PDF/TXT).
- [ ] **Документация обновлена**: `_docs/memory.md` §3.3 / `_docs/agent-loop.md` §4.
- [ ] **Тесты**: валидатор согласованности (если добавлен) / `pytest -q` зелёный.
- [ ] `git status` чист.

### Задача 4.3. Редизайн `.env.example` + синхронизация локального `.env`

- **Статус:** ToDo
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

- [ ] `.env.example` переоформлен, все ключи `Settings` представлены, описания актуальны.
- [ ] Локальный `.env` обновлён (проверка: `python -c "from app.config import Settings; Settings()"` без ошибок).
- [ ] **Документация обновлена**: `_docs/stack.md` §9.
- [ ] **Тесты**: `n/a` (конфиг-файлы) — но `Settings()` грузится без ошибок.
- [ ] `git status` чист (`.env` не коммитится).

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
| 1.2 | Все роли учитывают think + замер | high | S | ToDo | 1.1 |
| 2.1 | Общий gate на LLM + `queue_wait_ms` | high | M | ToDo | — |
| 2.2 | Приоритет live над recovery | high | M | ToDo | 2.1 |
| 3.1 | Пропуск мусорных сессий recovery | high | S | ToDo | — |
| 3.2 | Отложенный старт recovery | medium | S | ToDo | 3.1 |
| 3.3 | Зачистка текущего backlog | medium | S | ToDo | 3.1 |
| 4.1 | `OLLAMA_KEEP_ALIVE` / `OLLAMA_TEMPERATURE` | high | S | ToDo | — |
| 4.2 | Согласовать `num_ctx` и порог суммаризации | medium | S | ToDo | — |
| 4.3 | Редизайн `.env.example` + синх `.env` | high | M | ToDo | 1.1, 2.1, 4.1 |
| 5.1 | VRAM-гард в `/model` / `/models` | low | M | ToDo | — |
| 6.1 | `scripts/run.sh` с trap | medium | S | ToDo | — |
| 6.2 | Bounded shutdown + добивание `curl` | medium | M | ToDo | — |
| 7.1 | Метрики генерации в логах LLM | medium | S | ToDo | 1.1 |

> Обновляется при каждом переходе статуса и при добавлении/удалении задач.

## 13. История изменений спринта

- **2026-06-10** — спринт открыт, ветка `feature/11-performance` создана от `main`.
- **2026-06-10** — закрыта задача 1.1: флаг `think` в `OllamaClient.chat` (+ per-call override) и настройка `OLLAMA_THINK` (default `false`), проброс в `app/main.py`, нижняя граница `ollama>=0.5`; документация (`architecture.md` §3.4, `stack.md` §9) и тесты обновлены.
