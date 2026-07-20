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
    event_level: str = "ERROR",
    log_level: str = "INFO",
    enable_logs: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        sentry_dsn=dsn,
        sentry_environment="test",
        sentry_traces_sample_rate=0.0,
        sentry_event_level=event_level,
        sentry_log_level=log_level,
        sentry_enable_logs=enable_logs,
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
    assert setup_sentry(_make_settings(event_level="INFO")) is True  # noqa: S101
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
    assert setup_sentry(_make_settings(event_level="INFO")) is True  # noqa: S101
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
    assert setup_sentry(_make_settings(event_level="WARNING")) is True  # noqa: S101
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
    assert setup_sentry(_make_settings(dsn="")) is False  # noqa: S101


def test_enable_logs_and_auto_session_tracking(
    _transport: _InMemoryTransport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sentry_sdk.init вызывается с enable_logs=True и auto_session_tracking=False."""
    captured_kwargs: dict[str, Any] = {}

    original_init = sentry_sdk.init

    def spy_init(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return original_init(*args, **kwargs)

    monkeypatch.setattr(sentry_sdk, "init", spy_init)
    assert setup_sentry(_make_settings()) is True  # noqa: S101
    try:
        assert captured_kwargs.get("enable_logs") is True
        assert captured_kwargs.get("auto_session_tracking") is False
    finally:
        sentry_sdk.get_client().close(timeout=2.0)


def test_enable_logs_false(
    _transport: _InMemoryTransport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При sentry_enable_logs=False параметр enable_logs=False."""
    captured_kwargs: dict[str, Any] = {}

    original_init = sentry_sdk.init

    def spy_init(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return original_init(*args, **kwargs)

    monkeypatch.setattr(sentry_sdk, "init", spy_init)
    assert setup_sentry(_make_settings(enable_logs=False)) is True  # noqa: S101
    try:
        assert captured_kwargs.get("enable_logs") is False
    finally:
        sentry_sdk.get_client().close(timeout=2.0)


def test_default_event_level_is_error(
    _transport: _InMemoryTransport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Дефолтный event_level=ERROR — INFO-логи не создают Issues."""
    captured_integrations: list[Any] = []

    original_init = sentry_sdk.init

    def spy_init(*args, **kwargs):
        captured_integrations.extend(kwargs.get("integrations", []))
        return original_init(*args, **kwargs)

    monkeypatch.setattr(sentry_sdk, "init", spy_init)
    assert setup_sentry(_make_settings()) is True  # noqa: S101
    try:
        from sentry_sdk.integrations.logging import LoggingIntegration

        li = [
            i for i in captured_integrations if isinstance(i, LoggingIntegration)
        ]
        assert li, "LoggingIntegration не передан в sentry_sdk.init"
        assert li[0]._handler.level == logging.ERROR
    finally:
        sentry_sdk.get_client().close(timeout=2.0)


def test_log_level_debug_changes_breadcrumb_level(
    _transport: _InMemoryTransport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При SENTRY_LOG_LEVEL=DEBUG level в LoggingIntegration меняется на DEBUG."""
    captured_integrations: list[Any] = []

    original_init = sentry_sdk.init

    def spy_init(*args, **kwargs):
        captured_integrations.extend(kwargs.get("integrations", []))
        return original_init(*args, **kwargs)

    monkeypatch.setattr(sentry_sdk, "init", spy_init)
    assert setup_sentry(_make_settings(log_level="DEBUG")) is True  # noqa: S101
    try:
        from sentry_sdk.integrations.logging import LoggingIntegration

        li = [
            i for i in captured_integrations if isinstance(i, LoggingIntegration)
        ]
        assert li, "LoggingIntegration не передан в sentry_sdk.init"
        # _handler — event handler (event_level), _breadcrumb_handler — level
        assert li[0]._breadcrumb_handler.level == logging.DEBUG
    finally:
        sentry_sdk.get_client().close(timeout=2.0)


def test_default_log_level_is_info(
    _transport: _InMemoryTransport,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Дефолтный log_level=INFO — breadcrumbs level=INFO."""
    captured_integrations: list[Any] = []

    original_init = sentry_sdk.init

    def spy_init(*args, **kwargs):
        captured_integrations.extend(kwargs.get("integrations", []))
        return original_init(*args, **kwargs)

    monkeypatch.setattr(sentry_sdk, "init", spy_init)
    assert setup_sentry(_make_settings()) is True  # noqa: S101
    try:
        from sentry_sdk.integrations.logging import LoggingIntegration

        li = [
            i for i in captured_integrations if isinstance(i, LoggingIntegration)
        ]
        assert li, "LoggingIntegration не передан в sentry_sdk.init"
        assert li[0]._breadcrumb_handler.level == logging.INFO
    finally:
        sentry_sdk.get_client().close(timeout=2.0)


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
        with pytest.raises(Exception):  # noqa: B017, S101
            Settings()
    finally:
        os.environ.clear()
        os.environ.update(old_environ)
