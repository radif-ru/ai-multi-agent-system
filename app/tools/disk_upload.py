"""Tool `disk_upload` — загрузка файла на Яндекс.Диск.

Принимает `file_id` (локальный файл из `data/tmp/` через `FileIdMapper`) и
`path` (путь на Яндекс.Диске). Загружает файл через REST API.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from app.security import get_global_mapper
from app.services.yandex_disk import DiskError, YandexDiskReader
from app.tools.base import Tool, ToolContext, truncate_output
from app.tools.errors import ToolError


class DiskUploadTool(Tool):
    name = "disk_upload"
    description = (
        "Загружает локальный файл (по file_id из data/tmp/) на Яндекс.Диск. "
        "Параметры: file_id (идентификатор файла), path (путь на диске, "
        "например /uploads/report.pdf)."
    )
    args_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {
            "file_id": {"type": "string"},
            "path": {"type": "string"},
        },
        "required": ["file_id", "path"],
    }

    def __init__(self, *, max_output_chars: int = 50000) -> None:
        self._max_output_chars = max_output_chars

    async def run(self, args: Mapping[str, Any], ctx: ToolContext) -> str:
        file_id = str(args["file_id"]).strip()
        disk_path = str(args["path"]).strip()
        if not file_id:
            raise ToolError("file_id обязателен.")
        if not disk_path:
            raise ToolError("path обязателен (путь на Яндекс.Диске).")
        local_path = get_global_mapper().get_path(file_id)
        if local_path is None or not local_path.is_file():
            raise ToolError(f"Файл не найден по file_id: {file_id}")
        reader = YandexDiskReader(ctx.settings)
        try:
            uploaded_path = await reader.upload(Path(local_path), disk_path)
        except DiskError as exc:
            raise ToolError(str(exc)) from exc
        payload = {
            "path": uploaded_path,
            "status": "ok",
            "hint": f"Файл загружен на Яндекс.Диск: {uploaded_path}",
        }
        return truncate_output(
            json.dumps(payload, ensure_ascii=False), self._max_output_chars
        )
