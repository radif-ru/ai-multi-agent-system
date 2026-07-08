"""Тесты сервиса `MailReader` (IMAP, read-only).

Все вызовы IMAP замоканы через фабрику `imap_factory` — реальной сети нет
(см. `_docs/testing.md` § «Моки внешних систем»).
"""

from __future__ import annotations

import imaplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytest

from app.services.mail import (
    MailAuthError,
    MailError,
    MailNotConfigured,
    MailReader,
    MailUnavailable,
    _extract_body,
)


class _Settings:
    def __init__(self, **overrides):
        self.yandex_mail_user = "user@yandex.ru"
        self.yandex_mail_app_password = "app-secret"
        self.gmail_user = None
        self.gmail_app_password = None
        self.mail_imap_timeout = 5.0
        self.mail_max_messages = 10
        self.mail_body_max_chars = 200
        for key, value in overrides.items():
            setattr(self, key, value)


def _plain_message(subject: str = "Привет", body: str = "Тело письма") -> bytes:
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = "Отправитель <sender@example.com>"
    msg["To"] = "user@yandex.ru"
    msg["Subject"] = subject
    msg["Date"] = "Tue, 07 Jul 2026 10:00:00 +0300"
    return msg.as_bytes()


class _FakeImap:
    """Мок imaplib-соединения: search/fetch по заранее заданным письмам."""

    def __init__(self, messages: dict[bytes, dict]) -> None:
        # messages: uid -> {"raw": bytes, "seen": bool, "unread": bool}
        self._messages = messages
        self.selected: str | None = None
        self.search_criteria: str | None = None
        self.logged_out = False

    def login(self, user: str, password: str):
        return "OK", [b"Logged in"]

    def select(self, folder: str, readonly: bool = False):
        self.selected = folder
        return "OK", [b"1"]

    def uid(self, command: str, *args):
        if command == "search":
            self.search_criteria = args[1]
            uids = [
                uid for uid, m in self._messages.items()
                if args[1] == "ALL" or not m.get("seen", False)
            ]
            return "OK", [b" ".join(uids)]
        if command == "fetch":
            uid = args[0]
            spec = args[1]
            m = self._messages.get(uid)
            if m is None:
                return "OK", [None]
            flags = b"\\Seen" if m.get("seen", False) else b""
            raw = m["raw"]
            if "HEADER" in spec:
                raw = raw.split(b"\n\n")[0] + b"\n\n"
            meta = b"1 (UID " + uid + b" FLAGS (" + flags + b") BODY[] {%d}" % len(raw)
            return "OK", [(meta, raw), b")"]
        raise AssertionError(f"unexpected uid command: {command}")

    def logout(self):
        self.logged_out = True
        return "BYE", [b""]


def _reader(messages=None, settings=None, factory=None):
    settings = settings or _Settings()
    connections: list[_FakeImap] = []
    if factory is None:
        def factory(host, port, timeout=None):  # noqa: ARG001
            conn = _FakeImap(messages or {})
            connections.append(conn)
            return conn
    return MailReader(settings, imap_factory=factory), connections


# --- list_messages ---------------------------------------------------------


async def test_list_messages_returns_decoded_headers():
    messages = {
        b"1": {"raw": _plain_message(subject="Отчёт за июнь"), "seen": True},
        b"2": {"raw": _plain_message(subject="Новое письмо"), "seen": False},
    }
    reader, connections = _reader(messages)
    items = await reader.list_messages("yandex")
    assert [i["uid"] for i in items] == ["2", "1"]  # новые первыми
    assert items[0]["subject"] == "Новое письмо"
    assert items[0]["unread"] is True
    assert items[1]["subject"] == "Отчёт за июнь"
    assert items[1]["unread"] is False
    assert all(i["provider"] == "yandex" for i in items)
    assert connections[0].logged_out is True


async def test_list_messages_unread_only_uses_unseen():
    messages = {
        b"1": {"raw": _plain_message(), "seen": True},
        b"2": {"raw": _plain_message(), "seen": False},
    }
    reader, connections = _reader(messages)
    items = await reader.list_messages("yandex", unread_only=True)
    assert connections[0].search_criteria == "UNSEEN"
    assert [i["uid"] for i in items] == ["2"]


async def test_list_messages_respects_limit_cap():
    messages = {
        str(i).encode(): {"raw": _plain_message(subject=f"m{i}"), "seen": True}
        for i in range(1, 8)
    }
    reader, _ = _reader(messages, settings=_Settings(mail_max_messages=3))
    items = await reader.list_messages("yandex", limit=100)
    assert len(items) == 3
    assert [i["uid"] for i in items] == ["7", "6", "5"]


# --- read_message ----------------------------------------------------------


async def test_read_message_plain_body():
    messages = {b"5": {"raw": _plain_message(body="Строка один\nСтрока два"), "seen": True}}
    reader, _ = _reader(messages)
    msg = await reader.read_message("yandex", "5")
    assert msg["subject"] == "Привет"
    assert "Строка один" in msg["body"]
    assert msg["truncated"] is False


async def test_read_message_truncates_long_body():
    messages = {b"5": {"raw": _plain_message(body="x" * 500), "seen": True}}
    reader, _ = _reader(messages, settings=_Settings(mail_body_max_chars=100))
    msg = await reader.read_message("yandex", "5")
    assert msg["truncated"] is True
    assert msg["body"].endswith("... [truncated]")


async def test_read_message_missing_uid_raises():
    reader, _ = _reader({})
    with pytest.raises(MailError, match="не найдено"):
        await reader.read_message("yandex", "404")


def test_extract_body_html_fallback():
    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText("<p>Привет, <b>мир</b>!</p><style>a{}</style>", "html", "utf-8"))
    assert _extract_body(msg) == "Привет, мир !"


# --- Ошибки конфигурации / авторизации / сети ------------------------------


async def test_not_configured_message_mentions_env_vars():
    settings = _Settings(gmail_user=None, gmail_app_password=None)
    reader, _ = _reader({}, settings=settings)
    with pytest.raises(MailNotConfigured, match="GMAIL_USER"):
        await reader.list_messages("gmail")


async def test_auth_error_maps_to_mail_auth_error():
    class _BadLogin(_FakeImap):
        def login(self, user, password):
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")

    def factory(host, port, timeout=None):  # noqa: ARG001
        return _BadLogin({})

    reader, _ = _reader(factory=factory)
    with pytest.raises(MailAuthError, match="YANDEX_MAIL_APP_PASSWORD"):
        await reader.list_messages("yandex")


async def test_network_error_maps_to_unavailable():
    def factory(host, port, timeout=None):  # noqa: ARG001
        raise TimeoutError("timed out")

    reader, _ = _reader(factory=factory)
    with pytest.raises(MailUnavailable, match="недоступна"):
        await reader.list_messages("yandex")


async def test_unknown_provider_raises():
    reader, _ = _reader({})
    with pytest.raises(MailError, match="Неизвестный"):
        await reader.list_messages("mailru")


def test_configured_providers_lists_only_filled():
    settings = _Settings(gmail_user="u@gmail.com", gmail_app_password="p")
    reader, _ = _reader({}, settings=settings)
    assert reader.configured_providers() == ["yandex", "gmail"]

    settings = _Settings(yandex_mail_user=None)
    reader, _ = _reader({}, settings=settings)
    assert reader.configured_providers() == []
