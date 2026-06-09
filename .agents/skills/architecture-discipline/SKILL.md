---
name: architecture-discipline
description: "Загружай первым: границы слоёв (адаптер→core→executor→tools/services), JSON-only цикл, local-first, sqlite-vec, без новой архитектуры без согласования; указатель на остальные скиллы."
---

# Skill: architecture-discipline

Базовые архитектурные правила репозитория. Загружай **первым** для широкой/неочевидной задачи, затем — профильный скилл. Источник истины — `_docs/architecture.md` и `_docs/instructions.md` §11.

## Когда использовать

- Задача широкая или неочевидная — начни отсюда, чтобы выбрать следующий скилл.
- Добавляешь компонент или поток, трогаешь границы слоёв, реестр tools, память или агентный цикл.
- Сомневаешься, не выходит ли решение за рамки уже принятой архитектуры.

## Алгоритм

1. **Слоистая изоляция.** Поток: адаптер (`app/adapters/`) → core (`app/core/orchestrator.py`) → executor (`app/agents/`) → tools / LLM / memory (`app/tools/`, `app/services/`). Слой ниже не знает про слой выше: tool не знает про aiogram, memory — про executor, executor — про Telegram.
2. **Единая точка входа.** Любой адаптер вызывает только `core.handle_user_task(...)`. Адаптер не дёргает `Executor` / `Planner` / `Critic` напрямую.
3. **JSON-only цикл.** Ответ LLM в агентном цикле — строго JSON одной из форм `_docs/agent-loop.md`. Prose-ответ в цикле считается ошибкой.
4. **Tools as a registry.** Новый tool — отдельный модуль с контрактом `name` / `description` / `args_schema` / `async run(args, ctx)`, регистрация в `app/tools/registry.py` (`_docs/tools.md`).
5. **Memory split.** Краткосрочная — in-memory `ConversationStore`; долгосрочная — `sqlite-vec` (`SemanticMemory`), пополняется только саммари при `/new`, не сырыми сообщениями (`_docs/memory.md`).
6. **Local-first, без облака.** Только локальная Ollama; единственная БД — `sqlite-vec`; polling, не webhook (`_docs/instructions.md` §11).
7. **Async-first.** Любой I/O — через `await`; общие клиенты создаются один раз на приложение → скилл `async-discipline`.
8. **Без новой архитектуры без согласования.** Новый слой/сервис/абстракция/паттерн/зависимость или смена структуры каталогов — сначала проговорить с пользователем (`_docs/instructions.md` §11). В рамках задачи — только локальные технические решения.

## Куда дальше

- Async и I/O → `async-discipline`. Тесты → `testing-discipline`. Ошибки и исключения → `error-handling-discipline`.
- Безопасность входов и опасных tools → `prompt-injection-defense`. Документация → `documentation-discipline`. Git и коммиты → `git-discipline`.

## Чего избегать

- Обращения адаптера к `Executor` в обход `core`; обращения tool/memory к верхним слоям.
- Prose-ответов LLM в цикле вместо JSON.
- Новых зависимостей / слоёв / паттернов без согласования с пользователем.
- Облачных LLM, второй БД кроме `sqlite-vec`, webhook в MVP.
