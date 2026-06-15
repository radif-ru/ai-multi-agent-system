"""Тесты для WeatherTool."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest
from app.tools.weather import WeatherTool
from app.tools.errors import ToolError


@pytest.mark.asyncio
async def test_weather_tool_success() -> None:
    """Успешное получение погоды (curl/wttr.in замокан, без сети)."""
    tool = WeatherTool()

    fake_proc = AsyncMock()
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(
        return_value=(
            "Weather for Moscow: ☀ Sunny, +10°C\n".encode("utf-8"),
            b"",
        )
    )

    with patch.object(
        asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=fake_proc),
    ):
        result = await tool.run({"location": "Moscow"}, ctx=None)

    assert result
    assert "Moscow" in result


@pytest.mark.asyncio
async def test_weather_tool_empty_location() -> None:
    """Пустая локация."""
    tool = WeatherTool()

    with pytest.raises(ToolError, match="location is required"):
        await tool.run({"location": ""}, ctx=None)


@pytest.mark.asyncio
async def test_weather_tool_no_location() -> None:
    """Нет параметра location."""
    tool = WeatherTool()

    with pytest.raises(KeyError):
        await tool.run({}, ctx=None)


@pytest.mark.asyncio
async def test_weather_tool_fallback_method_exists() -> None:
    """Проверка существования метода fallback."""
    tool = WeatherTool()
    # Проверяем, что метод fallback существует
    assert hasattr(tool, "_fallback_to_web_search")


@pytest.mark.asyncio
async def test_weather_tool_kills_subprocess_on_cancel() -> None:
    """Подпроцесс curl убивается при отмене задачи."""
    tool = WeatherTool()

    fake_proc = AsyncMock()
    fake_proc.returncode = None  # процесс ещё не завершился
    fake_kill = Mock()
    fake_proc.kill = fake_kill
    fake_proc.wait = AsyncMock()
    # communicate выбрасывает CancelledError для симуляции отмены
    fake_proc.communicate = AsyncMock(side_effect=asyncio.CancelledError())

    with patch.object(
        asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=fake_proc),
    ):
        with pytest.raises(asyncio.CancelledError):
            await tool.run({"location": "Moscow"}, ctx=None)

    # Проверяем, что kill() был вызван
    fake_kill.assert_called_once()
    fake_proc.wait.assert_called_once()
