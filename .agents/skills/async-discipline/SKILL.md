---
name: async-discipline
description: "Async-дисциплина проекта: весь I/O через await, никаких requests/time.sleep, синхронные либы через asyncio.to_thread, общие клиенты."
---

# Skill: async-discipline

Правила работы с асинхронностью. Источник истины — `_docs/instructions.md` §4.

## Когда использовать

- Пишешь handler, tool, сервис или агентный цикл, где есть I/O (HTTP, файлы, Telegram API, `sqlite-vec`, Ollama).
- Интегрируешь синхронную библиотеку (`sqlite3`, `ddgs`).
- Создаёшь клиент внешнего сервиса.

## Алгоритм

1. Любой I/O — только через `await`. В hot path не должно быть блокирующих вызовов.
2. Не используй `requests`, `time.sleep`, блокирующие SDK. Разрешено: `httpx.AsyncClient`, `ollama.AsyncClient`, `aiofiles` (если нужно).
3. Синхронную библиотеку оборачивай в `asyncio.to_thread(...)` (например, `sqlite3`, `ddgs`).
4. Не создавай новый event loop внутри handlers/tools — всё работает в loop'е, запущенном aiogram.
5. Общие клиенты (HTTP, Ollama, SQLite-соединение) создавай **один раз на приложение** и закрывай при shutdown. В `__init__` tool'а — никаких сетевых вызовов, только сохранение зависимостей.
6. Метод `run` у tool — всегда `async`, даже если работа синхронная (единый контракт).

## Пример

Синхронный поиск через `ddgs` внутри async-tool:

```python
results = await asyncio.to_thread(lambda: DDGS().text(query, max_results=top_k))
```

## Чего избегать

- `requests.get(...)`, `time.sleep(...)`, `open(...).read()` в hot path event loop'а.
- `asyncio.run(...)` / `new_event_loop()` внутри handlers и tools.
- Создания нового HTTP/Ollama-клиента на каждый запрос вместо переиспользования общего.
