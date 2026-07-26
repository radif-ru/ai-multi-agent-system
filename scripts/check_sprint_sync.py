"""Проверка синхронизации доски: файлы спринтов ↔ `_board/plan.md`.

Скрипт проверяет три вещи:

1. Счётчики ToDo / Progress / Done в `plan.md` совпадают со статусами задач
   в файле активного спринта.
2. Статус спринта в индексе (`Активные` / `Закрытые`) совпадает со статусом
   в «Сводной таблице состояния» — ритуал закрытия спринта (`process.md` §9
   п.4) выполнен полностью.
3. У задач активного спринта со статусом `Done` не осталось незакрытых
   чекбоксов Definition of Done (`process.md` §7.9).

Закрытые спринты — архив (`process.md` §2 п.5), их DoD не проверяется.

Запуск из корня репозитория:

    python -m scripts.check_sprint_sync

Выход:
- 0 — расхождений нет.
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

# Статус, ожидаемый в сводной таблице для спринта из секции индекса.
_SECTION_STATUSES = {
    "Активные": {"Active"},
    "Закрытые": {"Closed", "Cancelled"},
}

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


def _row_cells(line: str) -> list[str]:
    """Ячейки markdown-строки таблицы или `[]`, если строка не табличная."""
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def parse_plan_index(plan_text: str) -> dict[int, tuple[str, str]]:
    """Статусы спринтов из индекса: `{sprint: (секция, статус)}`.

    Секция — заголовок `### Активные` / `### Закрытые`; строки-заглушки
    (`| — | (нет ...) |`) пропускаются.
    """
    result: dict[int, tuple[str, str]] = {}
    section = ""
    for line in plan_text.splitlines():
        heading = re.match(r"^###\s+(.+?)\s*$", line)
        if heading:
            section = heading.group(1)
            continue
        if section not in _SECTION_STATUSES:
            continue
        cells = _row_cells(line)
        if len(cells) != 7 or not cells[0].isdigit():
            continue
        result[int(cells[0])] = (section, cells[4])
    return result


def parse_plan_state(plan_text: str) -> dict[int, str]:
    """Статусы спринтов из «Сводной таблицы состояния»: `{sprint: статус}`."""
    result: dict[int, str] = {}
    for line in plan_text.splitlines():
        cells = _row_cells(line)
        if len(cells) != 4:
            continue
        match = re.match(r"^(\d+)\.\s", cells[0])
        if not match:
            continue
        result[int(match.group(1))] = cells[1]
    return result


def check_plan_tables(plan_text: str) -> list[str]:
    """Расхождения между индексом спринтов и сводной таблицей состояния."""
    index = parse_plan_index(plan_text)
    state = parse_plan_state(plan_text)
    errors: list[str] = []
    for sprint_num, (section, index_status) in sorted(index.items()):
        expected = _SECTION_STATUSES[section]
        if index_status not in expected:
            errors.append(
                f"Спринт {sprint_num}: в секции «{section}» статус "
                f"'{index_status}', ожидался один из {sorted(expected)}"
            )
        state_status = state.get(sprint_num)
        if state_status is None:
            errors.append(
                f"Спринт {sprint_num}: есть в индексе, но нет в сводной "
                "таблице состояния"
            )
        elif state_status != index_status:
            errors.append(
                f"Спринт {sprint_num}: статус в индексе '{index_status}' "
                f"≠ статусу в сводной таблице '{state_status}'"
            )
    return errors


def find_unchecked_dod(sprint_text: str) -> dict[str, int]:
    """Задачи `Done` с незакрытыми чекбоксами DoD: `{task_id: количество}`."""
    unchecked: dict[str, int] = {}
    current_task: str | None = None
    current_status: str | None = None
    in_dod = False
    for line in sprint_text.splitlines():
        task_match = re.match(r"^###\s+Задача\s+(\d+\.\d+)\.", line)
        if task_match:
            current_task = task_match.group(1)
            current_status = None
            in_dod = False
            continue
        status_match = re.match(r"^\- \*\*Статус:\*\*\s*(\w+)", line)
        if status_match:
            current_status = status_match.group(1)
            continue
        if line.startswith("#"):
            in_dod = line.startswith("#### Definition of Done")
            continue
        if in_dod and current_task and current_status == "Done":
            if line.lstrip().startswith("- [ ]"):
                unchecked[current_task] = unchecked.get(current_task, 0) + 1
    return unchecked


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    plan_path = repo_root / "_board" / "plan.md"
    sprints_dir = repo_root / "_board" / "sprints"

    if not plan_path.exists():
        print(f"ERROR: не найден {plan_path}", file=sys.stderr)
        return 1

    plan_text = plan_path.read_text(encoding="utf-8")
    plan_counts = parse_plan_counts(plan_text)
    errors: list[str] = check_plan_tables(plan_text)

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

        for task_id, count in sorted(find_unchecked_dod(sprint_text).items()):
            errors.append(
                f"Спринт {sprint_num}, задача {task_id}: статус Done, но "
                f"{count} чекбокс(ов) DoD не отмечены (process.md §7.9)"
            )

    if errors:
        print("ERROR: рассинхронизация доски:\n", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("OK: plan.md и файлы спринтов синхронизированы")
    return 0


if __name__ == "__main__":
    sys.exit(main())
