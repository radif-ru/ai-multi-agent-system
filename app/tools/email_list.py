"""Tool `email_list` — список последних писем (read-only).

Строит `MailReader` из `ctx.settings`; при неподключённой почте или ошибке
провайдера возвращает `ToolError` с человекочитаемой подсказкой (агент
передаёт её пользователю в любом канале). См. `_docs/tools.md`.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from app.services.mail import MailError, MailReader, PROVIDERS
from app.tools.base import Tool, ToolContext, truncate_output
from app.tools.errors import ToolError


class EmailListTool(Tool):
    name = "email_list"
    description = (
        "Список последних писем в почтовом ящике (read-only). Параметры: "
        "provider ('yandex' | 'gmail' | 'all', по умолчанию 'all'), "
        "unread_only (bool), limit (int). Возвращает JSON-массив "
        "[{uid, provider, from, subject, date, unread}, ...]."
    )
    args_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {
            "provider": {"type": "string"},
            "unread_only": {"type": "boolean"},
            "limit": {"type": "integer"},
        },
        "required": [],
    }

    def __init__(self, *, max_output_chars: int = 50000) -> None:
        self._max_output_chars = max_output_chars

    async def run(self, args: Mapping[str, Any], ctx: ToolContext) -> str:
        reader = MailReader(ctx.settings)
        provider = str(args.get("provider") or "all").strip().lower()
        unread_only = bool(args.get("unread_only") or False)
        limit = args.get("limit")
        limit = int(limit) if isinstance(limit, int) else None

        if provider == "all":
            providers = reader.configured_providers()
            if not providers:
                raise ToolError(_no_provider_hint())
        else:
            if provider not in PROVIDERS:
                raise ToolError(
                    f"Неизвестный провайдер '{provider}'. Доступные: "
                    f"{', '.join(PROVIDERS)}, all."
                )
            providers = [provider]

        items: list[dict[str, Any]] = []
        errors: list[str] = []
        for prov in providers:
            try:
                items.extend(
                    await reader.list_messages(
                        prov, unread_only=unread_only, limit=limit
                    )
                )
            except MailError as exc:
                errors.append(str(exc))

        if not items and errors:
            raise ToolError(" ".join(errors))

        payload: dict[str, Any] = {"messages": items}
        if errors:
            payload["warnings"] = errors
        return truncate_output(
            json.dumps(payload, ensure_ascii=False), self._max_output_chars
        )


def _no_provider_hint() -> str:
    parts = []
    for _, label, user_var, pass_var in PROVIDERS.values():
        parts.append(f"{label} ({user_var} + {pass_var})")
    return (
        "Почта не подключена. Заполните креды хотя бы одного провайдера в .env: "
        + "; ".join(parts)
        + " (пароль приложения, см. .env.example)."
    )
