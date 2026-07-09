"""Tool `disk_list` — список файлов и папок на Яндекс.Диске (read-only)."""

from __future__ import annotations

import json
from typing import Any, Mapping

from app.services.yandex_disk import DiskError, YandexDiskReader
from app.tools.base import Tool, ToolContext, truncate_output
from app.tools.errors import ToolError


class DiskListTool(Tool):
    name = "disk_list"
    description = (
        "Список файлов и папок на Яндекс.Диске (read-only). Параметр: "
        "path (папка, по умолчанию '/'). Возвращает JSON-массив "
        "[{name, path, type, size, modified}, ...]."
    )
    args_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": [],
    }

    def __init__(self, *, max_output_chars: int = 50000) -> None:
        self._max_output_chars = max_output_chars

    async def run(self, args: Mapping[str, Any], ctx: ToolContext) -> str:
        path = str(args.get("path") or "/").strip() or "/"
        reader = YandexDiskReader(ctx.settings)
        try:
            items = await reader.list_path(path)
        except DiskError as exc:
            raise ToolError(str(exc)) from exc
        return truncate_output(
            json.dumps({"items": items}, ensure_ascii=False),
            self._max_output_chars,
        )
