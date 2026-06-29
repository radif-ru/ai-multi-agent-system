"""Тесты `app.tools.read_file.ReadFileTool`."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.security import clear_global_mapper, get_global_mapper
from app.tools.errors import ToolError
from app.tools.read_file import ReadFileTool


@pytest.fixture
def ctx() -> SimpleNamespace:
    return SimpleNamespace()


async def test_reads_text_file(tmp_path, ctx):
    f = tmp_path / "note.txt"
    f.write_text("hello", encoding="utf-8")
    tool = ReadFileTool(allowed_dirs=[tmp_path])
    out = await tool.run({"path": str(f)}, ctx)
    assert out == "hello"


async def test_path_outside_whitelist_rejected(tmp_path, ctx, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    f = other / "x.txt"
    f.write_text("nope", encoding="utf-8")
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    tool = ReadFileTool(allowed_dirs=[allowed])
    with pytest.raises(ToolError):
        await tool.run({"path": str(f)}, ctx)


async def test_dotdot_in_path_rejected(tmp_path, ctx):
    tool = ReadFileTool(allowed_dirs=[tmp_path])
    with pytest.raises(ToolError):
        await tool.run({"path": str(tmp_path / ".." / "etc")}, ctx)


async def test_missing_file(tmp_path, ctx):
    tool = ReadFileTool(allowed_dirs=[tmp_path])
    with pytest.raises(ToolError):
        await tool.run({"path": str(tmp_path / "missing.txt")}, ctx)


async def test_binary_file_rejected(tmp_path, ctx):
    f = tmp_path / "blob.bin"
    f.write_bytes(b"\xff\xfe\x00binary\x00data")
    tool = ReadFileTool(allowed_dirs=[tmp_path])
    with pytest.raises(ToolError):
        await tool.run({"path": str(f)}, ctx)


async def test_too_large(tmp_path, ctx):
    f = tmp_path / "big.txt"
    f.write_text("a" * 100, encoding="utf-8")
    tool = ReadFileTool(allowed_dirs=[tmp_path], max_bytes=10)
    with pytest.raises(ToolError):
        await tool.run({"path": str(f)}, ctx)


async def test_truncation(tmp_path, ctx):
    f = tmp_path / "long.txt"
    f.write_text("a" * 5000, encoding="utf-8")
    tool = ReadFileTool(allowed_dirs=[tmp_path], max_output_chars=100)
    out = await tool.run({"path": str(f)}, ctx)
    assert len(out) == 100
    assert out.endswith("[truncated]")


async def test_file_id_reads_file(tmp_path, ctx):
    """Чтение файла через file_id."""
    clear_global_mapper()
    f = tmp_path / "note.txt"
    f.write_text("hello", encoding="utf-8")
    tool = ReadFileTool(allowed_dirs=[tmp_path])

    mapper = get_global_mapper()
    file_id = mapper.generate_id(f)

    out = await tool.run({"file_id": file_id}, ctx)
    assert out == "hello"
    clear_global_mapper()


async def test_file_id_not_found_error(tmp_path, ctx):
    """Ошибка при неизвестном file_id."""
    clear_global_mapper()
    tool = ReadFileTool(allowed_dirs=[tmp_path])
    with pytest.raises(ToolError, match="file_id .* недоступен"):
        await tool.run({"file_id": "file_unknown"}, ctx)
    clear_global_mapper()


async def test_requires_path_or_file_id(tmp_path, ctx):
    """Ошибка при отсутствии path и file_id."""
    clear_global_mapper()
    tool = ReadFileTool(allowed_dirs=[tmp_path])
    with pytest.raises(ToolError, match="требуется path или file_id"):
        await tool.run({}, ctx)
    clear_global_mapper()


async def test_system_path_rejected(tmp_path, ctx):
    """Запрет на системные пути (/etc, /sys, /proc)."""
    tool = ReadFileTool(allowed_dirs=[tmp_path])
    with pytest.raises(ToolError, match="системный путь не разрешён"):
        await tool.run({"path": "/etc/passwd"}, ctx)
    with pytest.raises(ToolError, match="системный путь не разрешён"):
        await tool.run({"path": "/sys/kernel"}, ctx)
    with pytest.raises(ToolError, match="системный путь не разрешён"):
        await tool.run({"path": "/proc/cpuinfo"}, ctx)


# --- Per-user область видимости (спринт 12, задача 5.1) ---


def _user_ctx(tmp_base: Path, user_id: int) -> SimpleNamespace:
    """Контекст с settings, разводящим каталоги по user_id (как Settings)."""
    settings = SimpleNamespace(
        get_user_tmp_dir=lambda uid: tmp_base / str(uid)
    )
    return SimpleNamespace(user_id=user_id, settings=settings)


async def test_user_scoped_reads_own_file(tmp_path):
    """В per-user режиме файл в каталоге пользователя читается."""
    user_dir = tmp_path / "42"
    user_dir.mkdir()
    f = user_dir / "note.txt"
    f.write_text("mine", encoding="utf-8")
    tool = ReadFileTool(user_scoped=True)
    out = await tool.run({"path": str(f)}, _user_ctx(tmp_path, 42))
    assert out == "mine"


async def test_user_scoped_rejects_other_user_dir(tmp_path):
    """Чужой каталог пользователя в per-user режиме → ToolError."""
    other_dir = tmp_path / "99"
    other_dir.mkdir()
    f = other_dir / "secret.txt"
    f.write_text("nope", encoding="utf-8")
    tool = ReadFileTool(user_scoped=True)
    with pytest.raises(ToolError, match="path not allowed"):
        await tool.run({"path": str(f)}, _user_ctx(tmp_path, 42))


async def test_user_scoped_rejects_base_dir_root(tmp_path):
    """Файл в корне data/tmp (вне каталога пользователя) → ToolError."""
    f = tmp_path / "shared.txt"
    f.write_text("nope", encoding="utf-8")
    tool = ReadFileTool(user_scoped=True)
    with pytest.raises(ToolError, match="path not allowed"):
        await tool.run({"path": str(f)}, _user_ctx(tmp_path, 42))


async def test_user_scoped_requires_context(tmp_path, ctx):
    """Без user_id/settings per-user режим отказывает."""
    tool = ReadFileTool(user_scoped=True)
    with pytest.raises(ToolError, match="per-user scope"):
        await tool.run({"path": str(tmp_path / "x.txt")}, ctx)
