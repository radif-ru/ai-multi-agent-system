"""Tool `list_scheduled_tasks` — список запланированных задач пользователя.

См. `_docs/tools.md` §2–§3, `_docs/scheduler.md`.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.tools.base import Tool, ToolContext
from app.tools.errors import ToolError


class ListScheduledTasksTool(Tool):
    name = "list_scheduled_tasks"
    description = (
        "Возвращает список запланированных задач текущего пользователя: "
        "id, prompt, cron, timezone, enabled, last_run_at, last_status."
    )
    args_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {},
    }

    async def run(self, args: Mapping[str, Any], ctx: ToolContext) -> str:
        if ctx.scheduler is None:
            raise ToolError("Планировщик задач недоступен")

        tasks = await ctx.scheduler.store.list_by_user(ctx.user_id)
        if not tasks:
            return "У вас нет запланированных задач."

        lines = []
        for t in tasks:
            status = "включена" if t.enabled else "выключена"
            last_run = t.last_run_at or "—"
            last_status = t.last_status or "—"
            prompt_short = t.prompt[:60]
            if len(t.prompt) > 60:
                prompt_short += "…"
            lines.append(
                f"ID: {t.id}\n"
                f"  Prompt: {prompt_short}\n"
                f"  Cron: {t.cron} ({t.timezone})\n"
                f"  Статус: {status}, последний запуск: {last_run} ({last_status})"
            )
        return "\n".join(lines)
