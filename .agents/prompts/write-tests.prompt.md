# Промпт: написать unit-тесты

Действуй как инженер, пишущий тесты для этого проекта. Я указываю модуль/функцию, которую нужно покрыть. Напиши `pytest`-тесты по правилам `_docs/testing.md`.

Требования:

- **Раннер и режим.** `pytest` + `pytest-asyncio` (`asyncio_mode = "auto"`), фикстура `mocker` из `pytest-mock`. `async def test_...` для асинхронного кода.
- **Никаких сетевых вызовов.** Реальные Telegram / Ollama / интернет — запрещены. Мокаем:
  - `aiogram.Bot` / `Message` → `MagicMock` / `AsyncMock`;
  - `OllamaClient.chat` / `OllamaClient.embed` → через `mocker.patch.object`;
  - `ddgs.DDGS.text` → `mocker.patch`;
  - `httpx` → `MockTransport` / `respx`;
  - `app/skills/`, `app/prompts/` → путь подменяется на `tmp_path`.
- **Исключение:** `SemanticMemory` тестируется с **реальным** `sqlite-vec` на `tmp_path`; если extension не грузится — `pytest.skip`.
- **Расположение.** Файл теста зеркалит `app/`: `tests/<пакет>/test_<name>.py`.

Покрой минимум:

1. **Happy path** — валидный вход → ожидаемый результат.
2. **Ошибки домена** — `ToolError` / `LLMTimeout` / `LLMUnavailable` / `LLMBadResponse` / `ArgsValidationError` там, где они уместны.
3. **Граничные случаи** — пустой результат, усечение длинного output до лимита, превышение лимитов цикла.
4. **Логирование** — при необходимости проверяй через `caplog` ключевые строки (`step=`, `tool=<name>`, `status=`).

Тесты должны быть детерминированными и проходить одной командой `pytest -q`. Цель покрытия: пакет `app/` ≥ 70%, `services/`/`agents/`/`tools/` ≥ 85%, `app/agents/protocol.py` — 100%.
