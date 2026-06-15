"""Тесты VRAM-гарда и размеров моделей в /models и /model.

Логика — в `app/commands/registry.py` (общий `CommandRegistry`); `llm`
прокидывается через `CommandContext.llm`. См. `_docs/commands.md` § /models, /model.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.commands import CommandRegistry
from app.commands.context import CommandContext


class _FakeUserSettings:
    def __init__(self, model: str = "qwen3.5:4b") -> None:
        self._model = model

    def get_model(self, user_id: int) -> str:
        return self._model

    def set_model(self, user_id: int, name: str) -> None:
        self._model = name


def _ctx(*, llm=None, budget: float = 24.0, active: str = "qwen3.5:4b") -> CommandContext:
    settings = SimpleNamespace(
        ollama_available_models=["qwen3.5:4b", "qwen3.6:35b"],
        ollama_vram_budget_gb=budget,
    )
    return CommandContext(
        user_id=1,
        chat_id=1,
        settings=settings,
        user_settings=_FakeUserSettings(active),
        prompts=SimpleNamespace(),
        tools=SimpleNamespace(),
        skills=SimpleNamespace(),
        conversations=SimpleNamespace(),
        archiver=SimpleNamespace(),
        llm=llm,
    )


def _llm_with_sizes(sizes: dict[str, int]):
    return SimpleNamespace(list_models=AsyncMock(return_value=sizes))


_GIB = 1024 ** 3
_LIGHT_BYTES = int(2.6 * _GIB)   # → "2.6 ГБ", влезает в бюджет 24 ГБ
_HEAVY_BYTES = 23 * _GIB         # → "23.0 ГБ", >= 90% от 24 ГБ → предупреждение


async def test_models_shows_sizes() -> None:
    llm = _llm_with_sizes({"qwen3.5:4b": _LIGHT_BYTES, "qwen3.6:35b": _HEAVY_BYTES})
    res = await CommandRegistry().execute("models", _ctx(llm=llm))
    assert "qwen3.5:4b (2.6 ГБ)" in res.text
    assert "qwen3.6:35b (23.0 ГБ)" in res.text


async def test_models_without_llm_has_no_sizes() -> None:
    res = await CommandRegistry().execute("models", _ctx(llm=None))
    assert "qwen3.5:4b" in res.text
    assert "ГБ" not in res.text


async def test_model_switch_warns_for_heavy_model() -> None:
    llm = _llm_with_sizes({"qwen3.6:35b": _HEAVY_BYTES})
    res = await CommandRegistry().execute("model", _ctx(llm=llm), args="qwen3.6:35b")
    assert "переключена на qwen3.6:35b" in res.text
    assert "⚠️" in res.text


async def test_model_switch_no_warning_for_light_model() -> None:
    llm = _llm_with_sizes({"qwen3.5:4b": _LIGHT_BYTES})
    res = await CommandRegistry().execute("model", _ctx(llm=llm), args="qwen3.5:4b")
    assert "переключена на qwen3.5:4b" in res.text
    assert "⚠️" not in res.text


async def test_model_switch_no_warning_when_budget_disabled() -> None:
    llm = _llm_with_sizes({"qwen3.6:35b": _HEAVY_BYTES})
    res = await CommandRegistry().execute(
        "model", _ctx(llm=llm, budget=0.0), args="qwen3.6:35b"
    )
    assert "⚠️" not in res.text


async def test_model_switch_no_warning_when_size_unknown() -> None:
    # ollama недоступен / тег не найден локально → размеров нет, без предупреждения.
    llm = _llm_with_sizes({})
    res = await CommandRegistry().execute("model", _ctx(llm=llm), args="qwen3.6:35b")
    assert "⚠️" not in res.text
