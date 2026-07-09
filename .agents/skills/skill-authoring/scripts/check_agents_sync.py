#!/usr/bin/env python3
"""Проверка синхронности библиотеки материалов ассистента (`.agents/`).

Валидирует:
- формат скиллов `.agents/skills/<name>/SKILL.md`: frontmatter (`name` = имени
  каталога, `description` ≤ 200 символов), обязательные секции тела;
- зеркала скиллов: symlink `.claude/skills/<name>`, упоминание в `AGENTS.md`
  (раздел «Skills») и в таблице скиллов `.agents/README.md`;
- промпты `.agents/prompts/*.prompt.md`: заголовок `# Промпт:`, упоминание
  в таблице промптов `.agents/README.md`.

Запуск из корня репозитория:

    python3 .agents/skills/skill-authoring/scripts/check_agents_sync.py

Выход:
- 0 — всё синхронно.
- 1 — найдены проблемы (список в stdout).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

MAX_DESCRIPTION_LEN = 200
REQUIRED_SECTIONS = ("## Когда использовать", "## Алгоритм", "## Чего избегать")

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_NAME_RE = re.compile(r"^name:\s*(\S+)\s*$", re.MULTILINE)
_DESCRIPTION_RE = re.compile(r'^description:\s*"?(.+?)"?\s*$', re.MULTILINE)


def _repo_root() -> Path:
    """Корень репозитория: три уровня вверх от каталога скрипта."""
    return Path(__file__).resolve().parents[4]


def check_skill(skill_dir: Path, agents_md: str, readme: str, claude_skills: Path) -> list[str]:
    """Проверить один скилл: формат SKILL.md и зеркала."""
    problems: list[str] = []
    name = skill_dir.name
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return [f"{skill_dir}: нет SKILL.md"]

    text = skill_md.read_text(encoding="utf-8")
    fm = _FRONTMATTER_RE.match(text)
    if not fm:
        problems.append(f"{skill_md}: нет YAML frontmatter (--- ... ---)")
    else:
        fm_text = fm.group(1)
        name_match = _NAME_RE.search(fm_text)
        if not name_match:
            problems.append(f"{skill_md}: во frontmatter нет поля name")
        elif name_match.group(1) != name:
            problems.append(
                f"{skill_md}: name={name_match.group(1)!r} не совпадает с каталогом {name!r}"
            )
        desc_match = _DESCRIPTION_RE.search(fm_text)
        if not desc_match:
            problems.append(f"{skill_md}: во frontmatter нет поля description")
        elif len(desc_match.group(1)) > MAX_DESCRIPTION_LEN:
            problems.append(
                f"{skill_md}: description длиннее {MAX_DESCRIPTION_LEN} символов "
                f"({len(desc_match.group(1))})"
            )

    for section in REQUIRED_SECTIONS:
        if section not in text:
            problems.append(f"{skill_md}: нет обязательной секции «{section}»")

    link = claude_skills / name
    if not link.is_symlink():
        problems.append(f".claude/skills/{name}: symlink отсутствует")
    elif link.resolve() != skill_dir.resolve():
        problems.append(f".claude/skills/{name}: symlink указывает не на {skill_dir}")

    if f".agents/skills/{name}/SKILL.md" not in agents_md:
        problems.append(f"AGENTS.md: нет упоминания скилла {name} в разделе «Skills»")
    if f"`{name}`" not in readme:
        problems.append(f".agents/README.md: нет строки про скилл {name} в таблице")

    # Скрипты скилла (если есть) — только .py/.sh, упомянуты в теле SKILL.md.
    scripts_dir = skill_dir / "scripts"
    if scripts_dir.is_dir():
        for script in sorted(scripts_dir.iterdir()):
            if script.suffix not in {".py", ".sh"}:
                problems.append(f"{script}: неподдерживаемый тип скрипта (только .py/.sh)")
            elif script.name not in text:
                problems.append(f"{skill_md}: скрипт {script.name} не описан в теле скилла")

    return problems


def check_prompt(prompt_file: Path, readme: str) -> list[str]:
    """Проверить один промпт: заголовок и упоминание в README."""
    problems: list[str] = []
    text = prompt_file.read_text(encoding="utf-8")
    if not text.startswith("# Промпт:"):
        problems.append(f"{prompt_file}: нет заголовка «# Промпт: ...» в первой строке")
    if f"`{prompt_file.name}`" not in readme:
        problems.append(f".agents/README.md: нет строки про промпт {prompt_file.name} в таблице")
    return problems


def main() -> int:
    root = _repo_root()
    agents_dir = root / ".agents"
    claude_skills = root / ".claude" / "skills"
    agents_md = (root / "AGENTS.md").read_text(encoding="utf-8")
    readme = (agents_dir / "README.md").read_text(encoding="utf-8")

    problems: list[str] = []
    skill_dirs = sorted(p for p in (agents_dir / "skills").iterdir() if p.is_dir())
    for skill_dir in skill_dirs:
        problems += check_skill(skill_dir, agents_md, readme, claude_skills)

    prompt_files = sorted((agents_dir / "prompts").glob("*.prompt.md"))
    for prompt_file in prompt_files:
        problems += check_prompt(prompt_file, readme)

    if problems:
        print("Найдены расхождения в .agents/:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(
        f"OK: .agents/ синхронизирован "
        f"({len(skill_dirs)} скиллов, {len(prompt_files)} промптов)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
