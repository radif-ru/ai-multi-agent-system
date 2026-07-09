"""Тесты tool `run_skill_script` (sandbox-раннер скриптов скилла)."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.skills import SkillRegistry
from app.tools.errors import ToolError
from app.tools.registry import _DANGEROUS_TOOLS
from app.tools.run_skill_script import RunSkillScriptTool


def _write_skill(root: Path, name: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("Description: ok\n\nТело.\n", encoding="utf-8")
    return skill_dir


def _write_script(skill_dir: Path, script: str, body: str) -> Path:
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    path = scripts_dir / script
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def _ctx(tmp_path: Path, skills: SkillRegistry, *, timeout: float = 5.0):
    settings = SimpleNamespace(
        skill_script_timeout=timeout,
        get_user_tmp_dir=lambda uid: tmp_path / "user" / str(uid),
    )
    return SimpleNamespace(settings=settings, user_id=1, skills=skills)


async def test_run_skill_script_returns_stdout(tmp_path: Path) -> None:
    skill_dir = _write_skill(tmp_path, "demo")
    _write_script(
        skill_dir, "stats.py",
        "import json\nprint(json.dumps({'ok': True}))\n",
    )
    reg = SkillRegistry(tmp_path)
    reg.load()

    out = await RunSkillScriptTool().run(
        {"skill": "demo", "script": "stats.py"}, _ctx(tmp_path, reg)
    )
    assert json.loads(out) == {"ok": True}


async def test_run_skill_script_passes_args(tmp_path: Path) -> None:
    skill_dir = _write_skill(tmp_path, "demo")
    _write_script(
        skill_dir, "echo.py",
        "import sys\nprint(sys.argv[1])\n",
    )
    reg = SkillRegistry(tmp_path)
    reg.load()

    out = await RunSkillScriptTool().run(
        {"skill": "demo", "script": "echo.py", "args": ["hello"]},
        _ctx(tmp_path, reg),
    )
    assert out.strip() == "hello"


async def test_run_skill_script_nonzero_exit_raises(tmp_path: Path) -> None:
    skill_dir = _write_skill(tmp_path, "demo")
    _write_script(
        skill_dir, "fail.py",
        "import sys\nsys.stderr.write('boom')\nsys.exit(1)\n",
    )
    reg = SkillRegistry(tmp_path)
    reg.load()

    with pytest.raises(ToolError, match="boom"):
        await RunSkillScriptTool().run(
            {"skill": "demo", "script": "fail.py"}, _ctx(tmp_path, reg)
        )


async def test_run_skill_script_unknown_skill_raises(tmp_path: Path) -> None:
    reg = SkillRegistry(tmp_path)
    reg.load()
    with pytest.raises(ToolError, match="скилл не найден"):
        await RunSkillScriptTool().run(
            {"skill": "missing", "script": "x.py"}, _ctx(tmp_path, reg)
        )


async def test_run_skill_script_unknown_script_raises(tmp_path: Path) -> None:
    _write_skill(tmp_path, "demo")
    reg = SkillRegistry(tmp_path)
    reg.load()
    with pytest.raises(ToolError, match="не найден"):
        await RunSkillScriptTool().run(
            {"skill": "demo", "script": "nope.py"}, _ctx(tmp_path, reg)
        )


async def test_run_skill_script_rejects_traversal(tmp_path: Path) -> None:
    skill_dir = _write_skill(tmp_path, "demo")
    _write_script(skill_dir, "stats.py", "print('x')\n")
    (skill_dir / "SECRET.md").write_text("secret", encoding="utf-8")
    reg = SkillRegistry(tmp_path)
    reg.load()

    with pytest.raises(ToolError, match="scripts/"):
        await RunSkillScriptTool().run(
            {"skill": "demo", "script": "../SECRET.md"}, _ctx(tmp_path, reg)
        )


async def test_run_skill_script_timeout_kills_process(tmp_path: Path) -> None:
    skill_dir = _write_skill(tmp_path, "demo")
    _write_script(
        skill_dir, "sleep.py",
        "import time\ntime.sleep(5)\n",
    )
    reg = SkillRegistry(tmp_path)
    reg.load()

    with pytest.raises(ToolError, match="таймаут"):
        await RunSkillScriptTool().run(
            {"skill": "demo", "script": "sleep.py"},
            _ctx(tmp_path, reg, timeout=0.2),
        )


async def test_run_skill_script_requires_skill_and_script(tmp_path: Path) -> None:
    reg = SkillRegistry(tmp_path)
    reg.load()
    with pytest.raises(ToolError, match="обязательны"):
        await RunSkillScriptTool().run({"skill": " ", "script": ""}, _ctx(tmp_path, reg))


def test_run_skill_script_is_dangerous_tool() -> None:
    """Без run_skill_script в allowlist tool блокируется реестром (secure by default)."""
    assert RunSkillScriptTool.name in _DANGEROUS_TOOLS
