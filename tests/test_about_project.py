"""Факты об авторе и системе доступны агенту.

Ответ на «кто тебя создал» не должен зависеть от того, догадается ли модель
вызвать `load_skill`: краткие факты лежат в системном промпте, подробности —
в скилле `about-project` (см. `_docs/prompts.md`, `_docs/skills.md`).
"""

from __future__ import annotations

from pathlib import Path

from app.services.skills import SkillRegistry

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PROMPT = _REPO_ROOT / "app" / "prompts" / "agent_system.md"
_SKILLS_DIR = _REPO_ROOT / "app" / "skills"


def test_system_prompt_contains_author_facts() -> None:
    text = _PROMPT.read_text(encoding="utf-8")

    assert "Ilaltdinov" in text
    assert "radif.ru" in text
    assert "github.com/radif-ru/ai-multi-agent-system" in text
    assert "about-project" in text


def test_system_prompt_keeps_placeholders() -> None:
    text = _PROMPT.read_text(encoding="utf-8")

    assert "{{TOOLS_DESCRIPTION}}" in text
    assert "{{SKILLS_DESCRIPTION}}" in text


def test_about_project_skill_is_registered() -> None:
    registry = SkillRegistry(_SKILLS_DIR)
    registry.load()

    names = [d["name"] for d in registry.list_descriptions()]
    assert "about-project" in names

    body = registry.get_body("about-project")
    assert "Ilaltdinov" in body
    assert "ai-multi-agent-system" in body
