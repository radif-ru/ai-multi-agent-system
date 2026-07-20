"""Тесты настраиваемого порога событий Sentry/GlitchTip (`SENTRY_EVENT_LEVEL`).

Проверяем:
- при `SENTRY_EVENT_LEVEL=INFO` логи `INFO+` уезжают как события, `DEBUG` — нет;
- при `SENTRY_EVENT_LEVEL=WARNING` логи `INFO` не создают событий;
- `LoggingIntegration` получает `event_level` из настроек;
- валидатор `Settings` отклоняет невалидные значения.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest
import sentry_sdk
from sentry_sdk.transport import Transport

from app.config import Settings
from app.observability import setup_sentry


class _InMemoryTransport(Transport):
    """Transport, который складывает envelopes в список вместо отправки."""

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        super().__init__(options or {})
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope) -> None:
        for item in envelope.items:
            if item.headers.get("type") == "event":
                self.events.append(item.payload.json)


def _make_settings(
    dsn: str = "https://pub@glitchtip.test/1",
    event_level: str = "INFO",
) -> SimpleNamespace:
    return SimpleNamespace(
        sentry_dsn=dsn,
        sentry_environment="test",
        sentry_traces_sample_rate=0.0,
        sentry_event_level=event_level,
    )


@pytest.fixture
def _transport(monkeypatch: pytest.MonkeyPatch):
    """Подменить sentry_sdk.init, чтобы перехватить transport."""
    transport = _InMemoryTransport()
    original_init = sentry_sdk.init

    def patched_init(*args, **kwargs):
        kwargs["transport"] = transport
        return original_init(*args, **kwargs)

    monkeypatch.setattr(sentry_sdk, "init", patched_init)
    return transport


def _flush_events(transport: _InMemoryTransport) -> list[dict[str, Any]]:
    sentry_sdk.flush(timeout=2.0)
    return transport.events


def test_info_level_creates_event(_transport: _InMemoryTransport) -> None:
    """При `SENTRY_EVENT_LEVEL=INFO` лог `logger.info(...)` создаёт событие."""
    assert setup_sentry(_make_settings(event_level="INFO")) is True
    test_logger = logging.getLogger("test.event_level.info")
    test_logger.setLevel(logging.INFO)
    try:
        test_logger.info("test info message")
        events = _flush_events(_transport)
        assert any(
            e.get("level") == "info" for e in events
        ), f"INFO-событие не найдено: {events}"
    finally:
        sentry_sdk.get_client().close(timeout=2.0)


def test_debug_level_not_sent(_transport: _InMemoryTransport) -> None:
    """При `SENTRY_EVENT_LEVEL=INFO` лог `logger.debug(...)` не создаёт событие."""
    assert setup_sentry(_make_settings(event_level="INFO")) is True
    test_logger = logging.getLogger("test.event_level.debug")
    test_logger.setLevel(logging.DEBUG)
    try:
        test_logger.debug("test debug message")
        events = _flush_events(_transport)
        assert not any(
            "debug" in str(e.get("level", "")) for e in events
        ), f"DEBUG-событие не должно было попасть: {events}"
    finally:
        sentry_sdk.get_client().close(timeout=2.0)


def test_warning_threshold_filters_info(_transport: _InMemoryTransport) -> None:
    """При `SENTRY_EVENT_LEVEL=WARNING` лог `INFO` не создаёт событие."""
    assert setup_sentry(_make_settings(event_level="WARNING")) is True
    test_logger = logging.getLogger("test.event_level.warn")
    test_logger.setLevel(logging.INFO)
    try:
        test_logger.info("should not be event")
        events = _flush_events(_transport)
        assert not any(
            e.get("level") == "info" for e in events
        ), f"INFO не должно быть событием при WARNING-пороге: {events}"
    finally:
        sentry_sdk.get_client().close(timeout=2.0)


def test_logging_integration_event_level_from_settings(
    _transport: _InMemoryTransport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`LoggingIntegration` получает `event_level` из `settings.sentry_event_level`."""
    captured_integrations: list[Any] = []

    original_init = sentry_sdk.init

    def spy_init(*args, **kwargs):
        captured_integrations.extend(kwargs.get("integrations", []))
        return original_init(*args, **kwargs)

    monkeypatch.setattr(sentry_sdk, "init", spy_init)
    assert setup_sentry(_make_settings(event_level="WARNING")) is True
    try:
        from sentry_sdk.integrations.logging import LoggingIntegration

        li = [
            i for i in captured_integrations if isinstance(i, LoggingIntegration)
        ]
        assert li, "LoggingIntegration не передан в sentry_sdk.init"
        assert li[0]._handler.level == logging.WARNING
    finally:
        sentry_sdk.get_client().close(timeout=2.0)


def test_empty_dsn_no_init(_transport: _InMemoryTransport) -> None:
    """При пустом `SENTRY_DSN` `setup_sentry` не инициализирует sentry."""
    assert setup_sentry(_make_settings(dsn="")) is False


def test_settings_validates_event_level() -> None:
    """Валидатор `Settings` принимает корректные значения."""
    import os

    env = {
        "TELEGRAM_BOT_TOKEN": "test",
        "SENTRY_EVENT_LEVEL": "warning",
    }
    old_environ = dict(os.environ)
    os.environ.update(env)
    try:
        s = Settings()
        assert s.sentry_event_level == "WARNING"
    finally:
        os.environ.clear()
        os.environ.update(old_environ)


def test_settings_rejects_invalid_event_level() -> None:
    """Валидатор `Settings` отклоняет невалидные значения."""
    import os

    env = {
        "TELEGRAM_BOT_TOKEN": "test",
        "SENTRY_EVENT_LEVEL": "BOGUS",
    }
    old_environ = dict(os.environ)
    os.environ.update(env)
    try:
        with pytest.raises(Exception):  # noqa: B017
            Settings()
    finally:
        os.environ.clear()
        os.environ.update(old_environ)
