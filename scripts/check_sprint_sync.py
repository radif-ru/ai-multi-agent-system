"""Проверка синхронизации статусов задач в файле спринта ↔ счётчиков в plan.md.

Скрипт парсит «Сводную таблицу задач спринта» из каждого активного файла спринта
и сравнивает количество ToDo / Progress / Done с записью в `_board/plan.md`.

Запуск из корня репозитория:

    python -m scripts.check_sprint_sync

Выход:
- 0 — все счётчики совпадают.
- 1 — найдено расхождение (выводит детали).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_PLAN_RE = re.compile(
    r"\|\s*(\d+)\.\s*(.+?)\s*\|\s*Active\s*\|\s*"
    r"(\d+)\s*/\s*(\d+)\s*/\s*(\d+)\s*\|"
)

_SUMMARY_ROW_RE = re.compile(
    r"^\|\s*([\d.]+)\s*\|.*?\|\s*(\w+)\s*\|\s*(\w+)\s*\|$",
    re.MULTILINE,
)

_TASK_STATUS_RE = re.compile(r"^\- \*\*Статус:\*\*\s*(\w+)", re.MULTILINE)


def parse_plan_counts(plan_text: str) -> dict[int, tuple[int, int, int]]:
    """Извлечь счётчики (todo, progress, done) для активных спринтов из plan.md."""
    result: dict[int, tuple[int, int, int]] = {}
    for match in _PLAN_RE.finditer(plan_text):
        sprint_num = int(match.group(1))
        todo = int(match.group(3))
        progress = int(match.group(4))
        done = int(match.group(5))
        result[sprint_num] = (todo, progress, done)
    return result


def parse_sprint_statuses(sprint_text: str) -> dict[str, str]:
    """Извлечь статусы задач из файла спринта по `**Статус:**` строкам."""
    statuses: dict[str, str] = {}
    lines = sprint_text.splitlines()
    current_task: str | None = None
    for line in lines:
        task_match = re.match(r"^###\s+Задача\s+(\d+\.\d+)\.", line)
        if task_match:
            current_task = task_match.group(1)
            continue
        status_match = re.match(r"^\- \*\*Статус:\*\*\s*(\w+)", line)
        if status_match and current_task:
            statuses[current_task] = status_match.group(1)
    return statuses


def count_statuses(statuses: dict[str, str]) -> tuple[int, int, int]:
    """Подсчитать ToDo / Progress / Done по словарю статусов."""
    todo = sum(1 for s in statuses.values() if s == "ToDo")
    progress = sum(1 for s in statuses.values() if s == "Progress")
    done = sum(1 for s in statuses.values() if s == "Done")
    return todo, progress, done


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    plan_path = repo_root / "_board" / "plan.md"
    sprints_dir = repo_root / "_board" / "sprints"

    if not plan_path.exists():
        print(f"ERROR: не найден {plan_path}", file=sys.stderr)
        return 1

    plan_counts = parse_plan_counts(plan_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    for sprint_num, (plan_todo, plan_progress, plan_done) in sorted(
        plan_counts.items()
    ):
        sprint_files = list(sprints_dir.glob(f"{sprint_num:02d}-*.md"))
        if not sprint_files:
            errors.append(
                f"Спринт {sprint_num}: файл не найден в {sprints_dir}"
            )
            continue

        sprint_text = sprint_files[0].read_text(encoding="utf-8")
        statuses = parse_sprint_statuses(sprint_text)
        actual_todo, actual_progress, actual_done = count_statuses(statuses)

        plan_total = plan_todo + plan_progress + plan_done
        actual_total = actual_todo + actual_progress + actual_done

        if (plan_todo, plan_progress, plan_done) != (
            actual_todo,
            actual_progress,
            actual_done,
        ):
            errors.append(
                f"Спринт {sprint_num}: расхождение. "
                f"plan.md={plan_todo}/{plan_progress}/{plan_done} "
                f"(всего {plan_total}), "
                f"файл спринта={actual_todo}/{actual_progress}/{actual_done} "
                f"(всего {actual_total})"
            )

    if errors:
        print("ERROR: рассинхронизация plan.md ↔ файл спринта:\n", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("OK: plan.md и файлы спринтов синхронизированы")
    return 0


if __name__ == "__main__":
    sys.exit(main())
