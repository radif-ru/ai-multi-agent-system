# `.agents/` — библиотека промптов и скиллов для AI-ассистента

Каталог содержит **переиспользуемые промпты и скиллы для AI-ассистента разработки**, который работает над этим проектом. Это не runtime-сущности бота — те живут в `app/prompts/` и `app/skills/`. Здесь — готовые инструкции для типовых задач разработки (ревью, тесты, отладка, добавление tool/skill, ведение спринта).

Все материалы — на русском; технические идентификаторы — латиницей (`_docs/instructions.md` §1). Ссылки на проект — относительные. Поведенческая база ассистента — `AGENTS.md` в корне; правила разработки — `_docs/instructions.md`; процесс задач — `_board/process.md`.

## Структура

```
.agents/
├── README.md                 # этот файл
├── prompts/                  # переиспользуемые промпты (*.prompt.md)
└── skills/                   # скиллы-инструкции (<name>/SKILL.md)
```

## Промпты (`prompts/`)

Каждый файл `*.prompt.md` — самодостаточный промпт: копируешь содержимое, добавляешь свой контекст (diff, модуль, описание бага) и отдаёшь ассистенту.

### Базовые

| Файл | Назначение |
|------|------------|
| `describe-architecture.prompt.md` | Построить подробное описание архитектуры проекта по его файлам. |
| `code-review.prompt.md` | Ревью diff по чек-листу проекта (хирургичность, тесты, async, безопасность). |
| `write-tests.prompt.md` | Написать `pytest`-тесты с моками внешних систем, без сети. |
| `debug-issue.prompt.md` | Диагностика бага через корневую причину + воспроизводящий тест. |
| `refactor.prompt.md` | Хирургический рефакторинг без изменения поведения. |
| `explain-code.prompt.md` | Структурно объяснить модуль/функцию и его место в системе. |
| `commit-message.prompt.md` | Сообщение коммита по Conventional Commits на русском. |

### Проектные

| Файл | Назначение |
|------|------------|
| `add-tool.prompt.md` | Добавить новый tool по контракту `_docs/tools.md`. |
| `add-skill.prompt.md` | Добавить новый skill по формату `_docs/skills.md`. |
| `run-sprint-task.prompt.md` | Выполнить задачу спринта по процессу `_board/process.md` §7. |
| `update-docs.prompt.md` | Обновить документацию `_docs/`/`_board/` с синхронизацией ссылок. |

## Скиллы (`skills/`)

Скилл — это устойчивая **дисциплина/правило**, которое полезно держать перед глазами в нескольких задачах. Формат повторяет проектный (`_docs/skills.md` §3): каталог `<name>/SKILL.md` с YAML frontmatter (`name`, `description`) и телом «Когда использовать → Алгоритм → Чего избегать».

| Скилл | Назначение |
|-------|------------|
| `architecture-discipline` | Границы слоёв, JSON-цикл, local-first, `sqlite-vec`; загружай первым для широкой задачи. |
| `async-discipline` | Async-дисциплина: весь I/O через `await`, синхронные либы через `asyncio.to_thread`. |
| `testing-discipline` | Дисциплина тестов: pytest + asyncio, моки, без сети, покрытие. |
| `error-handling-discipline` | Иерархии исключений, нет необработанных, человеческие сообщения, stacktrace только в лог. |
| `prompt-injection-defense` | Защита: InputSanitizer / ResponseSanitizer / FileIdMapper / allowlist. |
| `documentation-discipline` | Только относительные пути, синхронизация ссылок, doc-before-code. |
| `git-discipline` | Conventional Commits, ритуал задачи, зелёные `pytest`+`flake8` до коммита. |

## Как пользоваться

- **Промпт.** Открой нужный `*.prompt.md`, скопируй содержимое, добавь свой контекст и отправь ассистенту.
- **Скилл.** Прочитай `SKILL.md` перед задачей соответствующего класса (или дай ассистенту как справку) — он задаёт правила, по которым проверяется результат.

## Как добавить новый материал

- **Промпт:** создать `prompts/<name>.prompt.md`. Имя — kebab-case. Внутри — заголовок `# Промпт: ...` и сам текст промпта. Добавить строку в таблицу выше.
- **Скилл:** создать `skills/<name>/SKILL.md` по формату `_docs/skills.md` §3 (frontmatter `name` + `description` ≤ 200 символов, тело с разделами «Когда использовать», «Алгоритм», «Чего избегать»). Добавить строку в таблицу выше, строку в `AGENTS.md` (раздел «Skills») и symlink `.claude/skills/<name> → ../../.agents/skills/<name>` (см. ниже).

## Зеркалирование для других агентов

Чтобы одни и те же правила и скиллы видели все используемые AI-инструменты, держим **единственный источник истины** и зеркалим его относительными symlink'ами.

- **Источник истины правил** — `AGENTS.md` в корне (читается OpenAI Codex, Cursor, Windsurf и др.). Зеркала-symlink'и на него:
  - `CLAUDE.md → AGENTS.md` (Claude Code, Kimi через Claude-совместимые CLI).
  - `GEMINI.md → AGENTS.md` (Gemini CLI; `GEMINI.md` — его дефолтный контекст-файл).
  - `QWEN.md → AGENTS.md` (Qwen Code; `QWEN.md` — его дефолтный контекст-файл, настройка `contextFileName` пока не работает — [qwen-code#727](https://github.com/QwenLM/qwen-code/issues/727)).
  - `.github/copilot-instructions.md → ../AGENTS.md` (GitHub Copilot).
- **Источник истины скиллов** — `.agents/skills/<name>/SKILL.md`. Зеркало: `.claude/skills/<name> → ../../.agents/skills/<name>` (Claude Agent Skills; frontmatter `name` + `description` совместим). Windsurf (Cascade) и так читает `.agents/skills/` нативно.
- **Cursor и Devin/Windsurf** используют собственный формат правил — у них не symlink, а тонкий файл-указатель на `AGENTS.md`: `.cursor/rules/agents.mdc` (`alwaysApply: true`) и `.devin/rules/agents.md` (`trigger: always_on`).
- **DeepSeek / Kimi и прочие** собственного файла-конвенции не имеют — работают через перечисленные инструменты, поэтому отдельной настройки не требуют.

**Правило:** правим только источники (`AGENTS.md`, `.agents/skills/`); зеркала-symlink'и подхватывают изменения сами. Новый агент добавляется одним symlink'ом его дефолтного контекст-файла на `AGENTS.md` (или указателем, если у него свой формат правил).

