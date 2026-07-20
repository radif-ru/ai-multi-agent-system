"""Tool `cancel_scheduled_task` — отмена запланированной задачи.

См. `_docs/tools.md` §2–§3, `_docs/scheduler.md`.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.tools.base import Tool, ToolContext
from app.tools.errors import ToolError


class CancelScheduledTaskTool(Tool):
    name = "cancel_scheduled_task"
    description = (
        "Отменяет запланированную задачу по её ID. "
        "Можно отменить только свою задачу."
    )
    args_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "ID задачи для отмены",
            },
        },
        "required": ["task_id"],
    }

    async def run(self, args: Mapping[str, Any], ctx: ToolContext) -> str:
        if ctx.scheduler is None:
            raise ToolError("Планировщик задач недоступен")

        task_id = str(args["task_id"]).strip()
        if not task_id:
            raise ToolError("Параметр 'task_id' не может быть пустым")

        removed = await ctx.scheduler.remove_task(task_id, user_id=ctx.user_id)
        if not removed:
            return (
                f"Задача с ID '{task_id}' не найдена или принадлежит другому пользователю."
            )

        return f"Задача '{task_id}' отменена."
