"""Скачивание вложений MAX с изоляцией по пользователю.

По образцу `app/adapters/telegram/files.py`: проверка размера и сохранение
во временный подкаталог пользователя (`Settings.tmp_base_dir/{user_id}/`).
Вложения MAX содержат прямую ссылку (`payload.url`) на CDN; скачивание идёт
потоково через `MaxClient.stream`, лимит проверяется до и во время загрузки.

См. спринт 09, задача 4.1; `dev.max.ru/docs-api` (объекты вложений).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from urllib.parse import urlparse

from app.adapters.max.client import MaxClient

logger = logging.getLogger(__name__)


class FileTooLargeError(Exception):
    """Вложение превышает допустимый размер."""

    def __init__(self, file_size_mb: int, max_size_mb: int) -> None:
        super().__init__(
            f"Размер файла {file_size_mb} МБ превышает лимит {max_size_mb} МБ"
        )
        self.file_size_mb = file_size_mb
        self.max_size_mb = max_size_mb


def _extension(filename: str | None, url: str) -> str:
    """Определить расширение по имени файла, иначе по пути URL."""
    if filename:
        suffix = Path(filename).suffix
        if suffix:
            return suffix
    suffix = Path(urlparse(url).path).suffix
    return suffix


async def download_max_file(
    client: MaxClient,
    url: str,
    *,
    max_size_mb: int,
    tmp_dir: Path,
    user_id: int,
    filename: str | None = None,
) -> Path:
    """Скачать вложение MAX по `url` с проверкой размера и изоляцией.

    Args:
        client: `MaxClient` (используется его потоковый `stream`).
        url: Прямая ссылка на файл из `attachment.payload.url`.
        max_size_mb: Максимальный размер файла в мегабайтах.
        tmp_dir: Базовая директория временных файлов (`Settings.tmp_base_dir`).
        user_id: ID пользователя — подкаталог для изоляции.
        filename: Исходное имя файла (для расширения), если есть.

    Returns:
        Путь к скачанному файлу внутри `tmp_dir/{user_id}/`.

    Raises:
        FileTooLargeError: Если размер превышает лимит (по заголовку или факту).
    """
    max_bytes = max_size_mb * 1024 * 1024

    # Изоляция по пользователю: файл всегда внутри подкаталога user_id.
    user_dir = (tmp_dir / str(user_id)).resolve()
    base_dir = tmp_dir.resolve()
    if base_dir != user_dir and base_dir not in user_dir.parents:
        raise ValueError("user_dir вне tmp_base_dir")
    user_dir.mkdir(parents=True, exist_ok=True)

    file_name = f"{uuid.uuid4().hex}{_extension(filename, url)}"
    tmp_path = user_dir / file_name

    buffer = bytearray()
    async with client.stream(url) as response:
        if response.status_code >= 400:
            raise OSError(
                f"MAX вернул {response.status_code} при скачивании вложения"
            )
        declared = response.headers.get("content-length")
        if declared is not None and int(declared) > max_bytes:
            raise FileTooLargeError(int(declared) // (1024 * 1024), max_size_mb)
        async for chunk in response.aiter_bytes():
            buffer += chunk
            if len(buffer) > max_bytes:
                raise FileTooLargeError(len(buffer) // (1024 * 1024), max_size_mb)

    await asyncio.to_thread(tmp_path.write_bytes, bytes(buffer))
    logger.info(
        "max: вложение (%d байт) скачано в %s", len(buffer), tmp_path
    )
    return tmp_path
