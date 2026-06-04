---
name: testing-discipline
description: "Дисциплина тестов проекта: pytest + asyncio, моки внешних систем, без сети, тест на новое поведение, целевое покрытие."
---

# Skill: testing-discipline

Правила тестирования этого проекта. Источник истины — `_docs/testing.md` и `_docs/instructions.md` §8.

## Когда использовать

- Пишешь или меняешь код в `app/` — нужен unit-тест на новое поведение.
- Готовишь задачу к коммиту — нужен зелёный `pytest -q`.
- Чинишь баг — нужен падающий тест, воспроизводящий дефект.

**Не использовать** для чисто-документационных задач (правят только `_docs/`, `_board/`, `README.md`, `.env.example`, `app/skills/`, `app/prompts/`) — они освобождены от теста, в DoD ставится `n/a`.

## Алгоритм

1. Размести тест зеркально коду: `tests/<пакет>/test_<name>.py`.
2. Используй `pytest` + `pytest-asyncio` (`asyncio_mode = "auto"`), фикстуру `mocker`.
3. Замокай все внешние системы (никакой реальной сети):
   - Telegram: `Message`/`Bot` → `MagicMock`/`AsyncMock`;
   - Ollama: `mocker.patch.object(client, "chat"/"embed", ...)`;
   - `ddgs`: `mocker.patch("ddgs.DDGS.text", ...)`;
   - `httpx`: `MockTransport`/`respx`;
   - `app/skills/`, `app/prompts/`: путь → `tmp_path`.
4. Исключение: `SemanticMemory` тестируй с **реальным** `sqlite-vec` на `tmp_path`; если extension не грузится — `pytest.skip`.
5. Покрой happy path, ошибки домена (`ToolError`, `LLMTimeout`, `LLMUnavailable`, `LLMBadResponse`, `ArgsValidationError`), границы (пустой результат, усечение до лимита, превышение лимитов цикла).
6. При необходимости проверь логи через `caplog` (`step=`, `tool=<name>`, `status=`).
7. Прогон: `pytest -q` — зелёный. Цель покрытия: `app/` ≥ 70%, `services/`/`agents/`/`tools/` ≥ 85%, `app/agents/protocol.py` — 100%.

## Чего избегать

- Реальных вызовов Telegram / Ollama / интернета.
- Маскировки падений через `pytest -k`/`skip` вместо починки.
- Ослабления или удаления существующих тестов без явного указания.
- Недетерминизма (зависимость от времени, порядка, внешних данных).
