"""Tool `run_skill_script` — sandbox-раннер скриптов скилла.

Исполняет **только** файлы из `app/skills/<skill>/scripts/` (резолв через
`SkillRegistry.resolve_script`, запрет traversal), без shell, с таймаутом и
kill процесса при отмене/таймауте (по образцу `app/tools/weather.py`).

Опасный tool: требует `run_skill_script` в `DANGEROUS_TOOLS_ALLOWLIST`
(secure by default, см. `app/tools/registry.py`).

Конвенция скриптов (см. `_docs/skills.md`): статус — в stderr, машиночитаемый
результат (JSON) — в stdout, ненулевой код возврата = ошибка.
"""

from __future__ import annotations

import asyncio
from typing import Any, Mapping

from app.tools.base import Tool, ToolContext, truncate_output
from app.tools.errors import ToolError

_INTERPRETERS = {".py": "python3", ".sh": "bash"}


class RunSkillScriptTool(Tool):
    name = "run_skill_script"
    description = (
        "Запускает скрипт скилла из его каталога scripts/ (только .py/.sh, "
        "без произвольного кода). Параметры: skill (имя скилла), script (имя "
        "файла в scripts/), args (необязательный массив строк-аргументов)."
    )
    args_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {
            "skill": {"type": "string"},
            "script": {"type": "string"},
            "args": {"type": "array"},
        },
        "required": ["skill", "script"],
    }

    def __init__(self, *, max_output_chars: int = 50000) -> None:
        self._max_output_chars = max_output_chars

    async def run(self, args: Mapping[str, Any], ctx: ToolContext) -> str:
        skill = str(args["skill"]).strip()
        script = str(args["script"]).strip()
        script_args = [str(a) for a in args.get("args") or []]
        if not skill or not script:
            raise ToolError("skill и script обязательны")

        try:
            script_path = ctx.skills.resolve_script(skill, script)
        except KeyError as exc:
            raise ToolError(f"скилл не найден: {skill}") from exc
        except FileNotFoundError as exc:
            raise ToolError(str(exc)) from exc
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

        interpreter = _INTERPRETERS.get(script_path.suffix)
        if interpreter is None:
            raise ToolError(f"неподдерживаемый тип скрипта: {script_path.suffix}")

        cwd = ctx.settings.get_user_tmp_dir(ctx.user_id)
        cwd.mkdir(parents=True, exist_ok=True)

        process = await asyncio.create_subprocess_exec(
            interpreter,
            str(script_path),
            *script_args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=ctx.settings.skill_script_timeout
            )
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise ToolError(
                f"скрипт {script!r} скилла {skill!r} превысил таймаут "
                f"{ctx.settings.skill_script_timeout}с"
            ) from exc
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()

        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="ignore").strip()
            raise ToolError(
                f"скрипт {script!r} скилла {skill!r} завершился с кодом "
                f"{process.returncode}: {error_msg}"
            )

        result = stdout.decode("utf-8", errors="ignore")
        return truncate_output(result, self._max_output_chars)
