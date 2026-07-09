"""Tool `disk_download` — скачать файл с Яндекс.Диска в каталог пользователя.

Возвращает file_id (через `FileIdMapper`), чтобы дальше файл разбирался
существующим tool `read_document`. Файл сохраняется в per-user tmp-каталог
(изоляция по пользователю, см. `_docs/security.md`).
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from app.security import get_global_mapper
from app.services.yandex_disk import DiskError, YandexDiskReader
from app.tools.base import Tool, ToolContext, truncate_output
from app.tools.errors import ToolError


class DiskDownloadTool(Tool):
    name = "disk_download"
    description = (
        "Скачивает файл с Яндекс.Диска в рабочий каталог и возвращает "
        "file_id для последующего чтения через read_document. Параметр: "
        "path (полный путь к файлу на диске)."
    )
    args_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    def __init__(self, *, max_output_chars: int = 50000) -> None:
        self._max_output_chars = max_output_chars

    async def run(self, args: Mapping[str, Any], ctx: ToolContext) -> str:
        path = str(args["path"]).strip()
        if not path:
            raise ToolError("path обязателен (полный путь к файлу на диске).")
        dest_dir = ctx.settings.get_user_tmp_dir(ctx.user_id)
        reader = YandexDiskReader(ctx.settings)
        try:
            local_path = await reader.download(path, dest_dir)
        except DiskError as exc:
            raise ToolError(str(exc)) from exc
        file_id = get_global_mapper().generate_id(local_path)
        payload = {
            "file_id": file_id,
            "name": local_path.name,
            "hint": "Передайте file_id в read_document, чтобы прочитать файл.",
        }
        return truncate_output(
            json.dumps(payload, ensure_ascii=False), self._max_output_chars
        )
