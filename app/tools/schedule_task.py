"""Tool `schedule_task` — создание запланированной задачи.

См. `_docs/tools.md` §2–§3, `_docs/scheduler.md`.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.security import sanitize_user_input
from app.services.scheduled_tasks import ScheduledTask, new_task_id
from app.services.scheduler import validate_cron
from app.tools.base import Tool, ToolContext
from app.tools.errors import ToolError


class ScheduleTaskTool(Tool):
    name = "schedule_task"
    description = (
        "Создаёт запланированную задачу, которая будет выполняться автоматически по расписанию. "
        "Параметр 'cron' — 5-польное cron-выражение (минута час день месяц день_недели). "
        "Например: '0 9 * * *' — каждый день в 9:00, '*/30 * * * *' — каждые 30 минут. "
        "Параметр 'prompt' — текст задачи для выполнения. "
        "Параметр 'timezone' — часовой пояс (по умолчанию Europe/Moscow)."
    )
    args_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Текст задачи для выполнения по расписанию",
            },
            "cron": {
                "type": "string",
                "description": "5-польное cron-выражение: минута час день месяц день_недели",
            },
            "timezone": {
                "type": "string",
                "description": "Часовой пояс (например: Europe/Moscow, UTC)",
            },
        },
        "required": ["prompt", "cron"],
    }

    async def run(self, args: Mapping[str, Any], ctx: ToolContext) -> str:
        if ctx.scheduler is None:
            raise ToolError("Планировщик задач недоступен")

        prompt = str(args["prompt"]).strip()
        cron = str(args["cron"]).strip()
        timezone = str(args.get("timezone", "Europe/Moscow")).strip()

        if not prompt:
            raise ToolError("Параметр 'prompt' не может быть пустым")

        if not validate_cron(cron):
            raise ToolError(
                f"Невалидное cron-выражение: '{cron}'. "
                "Используйте 5 полей: минута час день месяц день_недели. "
                "Пример: '0 9 * * *' — каждый день в 9:00."
            )

        max_jobs = ctx.settings.scheduler_max_jobs_per_user
        count = await ctx.scheduler.store.count_by_user(ctx.user_id)
        if count >= max_jobs:
            raise ToolError(
                f"Достигнут лимит запланированных задач ({max_jobs}). "
                "Удалите ненужные задачи перед созданием новых."
            )

        sanitized = sanitize_user_input(prompt, user_id=ctx.user_id, mode="warn")

        task = ScheduledTask(
            id=new_task_id(),
            user_id=ctx.user_id,
            chat_id=ctx.chat_id,
            channel="telegram",
            prompt=sanitized,
            cron=cron,
            timezone=timezone,
        )
        await ctx.scheduler.add_task(task)

        return (
            f"Задача создана. ID: {task.id}\n"
            f"Расписание: {cron} ({timezone})\n"
            f"Prompt: {sanitized[:100]}"
        )
