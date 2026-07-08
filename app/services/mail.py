"""Сервис чтения почты по IMAP (Яндекс, Gmail). Read-only.

Обёртка над stdlib `imaplib`/`email`: синхронные вызовы уводятся в
`asyncio.to_thread`. Каждая операция — отдельное соединение (stateless).
Ошибки конфигурации/авторизации/сети — собственная иерархия `MailError`
с человекочитаемыми сообщениями для пользователя. См. `_docs/tools.md`.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import imaplib
import logging
import re
import time
from email import message_from_bytes
from email.header import decode_header
from email.message import Message
from typing import Any, Callable

from app.config import Settings

logger = logging.getLogger(__name__)

IMAP_PORT = 993

# Провайдер → (IMAP-хост, человекочитаемое имя, env-переменные кредов).
PROVIDERS: dict[str, tuple[str, str, str, str]] = {
    "yandex": (
        "imap.yandex.ru",
        "Яндекс Почта",
        "YANDEX_MAIL_USER",
        "YANDEX_MAIL_APP_PASSWORD",
    ),
    "gmail": (
        "imap.gmail.com",
        "Gmail",
        "GMAIL_USER",
        "GMAIL_APP_PASSWORD",
    ),
}


class MailError(Exception):
    """Базовая ошибка почтового сервиса (сообщение — для пользователя)."""


class MailNotConfigured(MailError):
    """Креды провайдера не заполнены в `.env`."""


class MailAuthError(MailError):
    """Провайдер отверг логин/пароль приложения."""


class MailUnavailable(MailError):
    """Сервер недоступен или превышен таймаут."""


class MailReader:
    """Read-only доступ к почте по IMAP (список, чтение писем)."""

    def __init__(
        self,
        settings: Settings,
        *,
        imap_factory: Callable[..., Any] = imaplib.IMAP4_SSL,
    ) -> None:
        self._settings = settings
        self._imap_factory = imap_factory

    # --- Публичный API -------------------------------------------------

    def configured_providers(self) -> list[str]:
        """Провайдеры, у которых заполнены креды."""
        return [p for p in PROVIDERS if self._credentials(p) is not None]

    async def list_messages(
        self,
        provider: str,
        *,
        folder: str = "INBOX",
        unread_only: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Последние письма папки: `{uid, provider, from, subject, date, unread}`."""
        user, password = self._require_credentials(provider)
        if limit is None or limit <= 0:
            limit = self._settings.mail_max_messages
        limit = min(limit, self._settings.mail_max_messages)
        return await self._call(
            provider,
            "list",
            lambda: self._list_sync(provider, user, password, folder, unread_only, limit),
        )

    async def read_message(self, provider: str, uid: str) -> dict[str, Any]:
        """Письмо целиком: заголовки + текстовое тело (усечённое)."""
        user, password = self._require_credentials(provider)
        return await self._call(
            provider,
            "read",
            lambda: self._read_sync(provider, user, password, uid),
        )

    # --- Внутреннее ------------------------------------------------------

    def _credentials(self, provider: str) -> tuple[str, str] | None:
        if provider == "yandex":
            user = self._settings.yandex_mail_user
            password = self._settings.yandex_mail_app_password
        elif provider == "gmail":
            user = self._settings.gmail_user
            password = self._settings.gmail_app_password
        else:
            raise MailError(
                f"Неизвестный почтовый провайдер '{provider}'. "
                f"Доступные: {', '.join(PROVIDERS)}."
            )
        if user and password:
            return user, password
        return None

    def _require_credentials(self, provider: str) -> tuple[str, str]:
        creds = self._credentials(provider)
        if creds is None:
            _, label, user_var, pass_var = PROVIDERS[provider]
            raise MailNotConfigured(
                f"{label} не подключена: заполните {user_var} и {pass_var} в .env "
                f"(пароль приложения, см. .env.example)."
            )
        return creds

    async def _call(self, provider: str, op: str, fn: Callable[[], Any]) -> Any:
        host, label, _, _ = PROVIDERS[provider]
        started = time.monotonic()
        logger.info(
            "external.call service=mail provider=%s op=%s",
            provider, op,
            extra={"service": "mail", "provider": provider, "op": op},
        )
        try:
            result = await asyncio.to_thread(fn)
        except imaplib.IMAP4.error as exc:
            self._log_fail(provider, op, started, exc)
            text = str(exc).lower()
            if "auth" in text or "login" in text or "credentials" in text:
                _, _, user_var, pass_var = PROVIDERS[provider]
                raise MailAuthError(
                    f"Не удалось войти в {label}: проверьте {user_var} и "
                    f"{pass_var} в .env (нужен пароль приложения, не основной)."
                ) from exc
            raise MailUnavailable(f"{label}: ошибка IMAP — {exc}") from exc
        except MailError:
            raise
        except OSError as exc:
            self._log_fail(provider, op, started, exc)
            raise MailUnavailable(
                f"{label} ({host}) недоступна: {exc}. Попробуйте позже."
            ) from exc
        dur_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "external.ok service=mail provider=%s op=%s dur_ms=%d",
            provider, op, dur_ms,
            extra={"service": "mail", "provider": provider, "op": op,
                   "duration_ms": dur_ms, "status": "ok"},
        )
        return result

    @staticmethod
    def _log_fail(provider: str, op: str, started: float, exc: Exception) -> None:
        dur_ms = int((time.monotonic() - started) * 1000)
        logger.error(
            "external.fail service=mail provider=%s op=%s dur_ms=%d error=%s",
            provider, op, dur_ms, exc,
            extra={"service": "mail", "provider": provider, "op": op,
                   "duration_ms": dur_ms, "status": "fail", "error": str(exc)},
        )

    def _connect(self, provider: str, user: str, password: str) -> Any:
        host, _, _, _ = PROVIDERS[provider]
        conn = self._imap_factory(
            host, IMAP_PORT, timeout=self._settings.mail_imap_timeout
        )
        conn.login(user, password)
        return conn

    def _list_sync(
        self,
        provider: str,
        user: str,
        password: str,
        folder: str,
        unread_only: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        conn = self._connect(provider, user, password)
        try:
            conn.select(folder, readonly=True)
            criteria = "UNSEEN" if unread_only else "ALL"
            _, data = conn.uid("search", None, criteria)
            uids = (data[0] or b"").split()
            items: list[dict[str, Any]] = []
            for uid in reversed(uids[-limit:]):
                _, fetched = conn.uid(
                    "fetch", uid, "(BODY.PEEK[HEADER] FLAGS)"
                )
                part = next((p for p in fetched or [] if isinstance(p, tuple)), None)
                if part is None:
                    continue
                meta, raw_header = part
                msg = message_from_bytes(raw_header)
                items.append({
                    "uid": uid.decode(),
                    "provider": provider,
                    "from": _decode(msg.get("From")),
                    "subject": _decode(msg.get("Subject")),
                    "date": _decode(msg.get("Date")),
                    "unread": b"\\Seen" not in (meta or b""),
                })
            return items
        finally:
            _close_quietly(conn)

    def _read_sync(
        self, provider: str, user: str, password: str, uid: str
    ) -> dict[str, Any]:
        conn = self._connect(provider, user, password)
        try:
            conn.select("INBOX", readonly=True)
            _, fetched = conn.uid("fetch", uid.encode(), "(BODY.PEEK[])")
            part = next((p for p in fetched or [] if isinstance(p, tuple)), None)
            if part is None:
                raise MailError(f"Письмо с uid={uid} не найдено.")
            msg = message_from_bytes(part[1])
            body = _extract_body(msg)
            max_chars = self._settings.mail_body_max_chars
            truncated = len(body) > max_chars
            if truncated:
                body = body[:max_chars] + "... [truncated]"
            return {
                "uid": uid,
                "provider": provider,
                "from": _decode(msg.get("From")),
                "to": _decode(msg.get("To")),
                "subject": _decode(msg.get("Subject")),
                "date": _decode(msg.get("Date")),
                "body": body,
                "truncated": truncated,
            }
        finally:
            _close_quietly(conn)


def _close_quietly(conn: Any) -> None:
    try:
        conn.logout()
    except Exception:  # noqa: BLE001 — соединение закрывается best-effort
        pass


def _decode(value: str | None) -> str:
    """Декодировать MIME-заголовок (RFC 2047) в обычную строку."""
    if not value:
        return ""
    parts: list[str] = []
    for chunk, charset in decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return "".join(parts).strip()


def _extract_body(msg: Message) -> str:
    """Текстовое тело письма: text/plain, fallback — text/html без тегов."""
    plain: str | None = None
    html: str | None = None
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_content_disposition() == "attachment":
            continue
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="replace")
        if ctype == "text/plain" and plain is None:
            plain = text
        elif ctype == "text/html" and html is None:
            html = text
    if plain is not None:
        return plain.strip()
    if html is not None:
        stripped = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html,
                          flags=re.DOTALL | re.IGNORECASE)
        stripped = re.sub(r"<[^>]+>", " ", stripped)
        return re.sub(r"\s+", " ", html_lib.unescape(stripped)).strip()
    return ""
