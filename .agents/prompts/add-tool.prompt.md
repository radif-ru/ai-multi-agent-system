# Промпт: добавить новый tool

Действуй как инженер этого проекта. Я описываю возможность, которую нужно реализовать как **tool** (детерминированное действие, вызываемое агентом в шаге `action`). Реализуй её строго по контракту из `_docs/tools.md`.

Сначала проверь: это точно tool, а не skill? Tool — это **код** (вычисление, HTTP, поиск, чтение файла). Если задача — «как решать класс задач» (последовательность шагов, формат ответа), это skill (`_docs/skills.md` §1).

Контракт (`_docs/tools.md` §2):

- Один tool — один файл `app/tools/<name>.py`.
- Атрибуты: `name` (snake_case, уникальное), `description` (одна короткая строка на русском, попадёт в системный промпт), `args_schema` (JSON Schema: `object` с `properties` и `required`).
- Метод `async def run(self, args, ctx: ToolContext) -> str` — возвращает **строку** (станет `observation`). Ошибки домена — `raise ToolError(message)` из `app/tools/errors.py`.
- Никаких сетевых вызовов в `__init__`. Любой I/O — через `await`; синхронные библиотеки — через `asyncio.to_thread`.
- Tool сам **не пишет** свои логи — это делает реестр.

Шаги (`_docs/tools.md` §5):

1. Создать `app/tools/<name>.py` по контракту.
2. Зарегистрировать инстанс в `app/tools/registry.py` (`_DEFAULT_TOOLS`).
3. Покрыть unit-тестом `tests/tools/test_<name>.py`: валидный вызов; невалидные `args` → `ArgsValidationError`; типичная ошибка домена → `ToolError`; усечение длинного output до `MAX_TOOL_OUTPUT_CHARS`.
4. Если нужны новые env-переменные — обновить `.env.example`, `Settings`, `_docs/stack.md`.
5. Если нужна новая зависимость — обновить `requirements.txt` и `_docs/links.md`.

Если tool потенциально опасен (произвольная ФС, shell, запись) — это **не** локальный tool: согласуй с пользователем отдельный контракт и режим allowlist (`_docs/security.md` §4, `_docs/tools.md` §7). Не расширяй scope без согласования (`_docs/instructions.md` §11).
