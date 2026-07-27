"""Ритуал перехода статуса задачи спринта: `_board/process.md` §7.3 и §7.9.

Переход задачи в `Progress` / `Done` — механика из шести шагов (статус в
заголовке, чекбоксы DoD, сводная таблица задач, история спринта, счётчики в
`plan.md`, коммит). Делать это руками дорого и легко забыть пункт, поэтому
операция автоматизирована (`AGENTS.md` §5, `_docs/instructions.md` §13).

Запуск из корня репозитория:

    python3 -m scripts.task start 16.1.1
    python3 -m scripts.task done 16.1.1 --note "что сделано"

Перед коммитом скрипт прогоняет `check_sprint_sync` — рассинхрон доски не
попадёт в историю. Коммит можно отключить флагом `--no-commit`.

Выход:
- 0 — переход выполнен.
- 1 — ошибка (задача не найдена, неожиданный текущий статус, рассинхрон).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

from scripts.check_sprint_sync import count_statuses, parse_sprint_statuses
from scripts.check_sprint_sync import main as check_sprint_sync

_TASK_ID_RE = re.compile(r"^(\d{1,2})\.(\d+\.\d+)$")
_HEADING_RE = re.compile(r"^###\s+Задача\s+(\d+\.\d+)\.")
_STATUS_RE = re.compile(r"^(\- \*\*Статус:\*\*\s*)(\w+)\s*$")
_HISTORY_RE = re.compile(r"^##\s+\d+\.\s+История изменений спринта\s*$")
_PLAN_ROW_RE = re.compile(r"^(\d+)\.\s")

_TRANSITIONS = {"start": ("ToDo", "Progress"), "done": ("Progress", "Done")}


class TaskError(Exception):
    """Ожидаемая ошибка ритуала — печатается без stacktrace."""


def parse_task_id(raw: str) -> tuple[int, str]:
    """Разобрать `<NN>.<stage>.<task>` в номер спринта и локальный ID задачи."""
    match = _TASK_ID_RE.match(raw)
    if not match:
        raise TaskError(
            f"неверный ID задачи '{raw}', ожидается формат <NN>.<этап>.<задача>"
        )
    return int(match.group(1)), match.group(2)


def set_task_status(text: str, task_id: str, expected: str, new: str) -> str:
    """Сменить `**Статус:**` в заголовке задачи, проверив текущее значение."""
    lines = text.splitlines(keepends=True)
    current: str | None = None
    for index, line in enumerate(lines):
        heading = _HEADING_RE.match(line)
        if heading:
            current = heading.group(1)
            continue
        if current != task_id:
            continue
        status = _STATUS_RE.match(line.rstrip("\n"))
        if not status:
            continue
        if status.group(2) != expected:
            raise TaskError(
                f"задача {task_id}: статус '{status.group(2)}', "
                f"ожидался '{expected}'"
            )
        lines[index] = f"{status.group(1)}{new}\n"
        return "".join(lines)
    raise TaskError(f"задача {task_id}: не найден заголовок или строка статуса")


def set_summary_row_status(text: str, task_id: str, new: str) -> str:
    """Обновить статус задачи в сводной таблице задач спринта."""
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) != 6 or cells[0] != task_id:
            continue
        cells[4] = new
        lines[index] = "| " + " | ".join(cells) + " |\n"
        return "".join(lines)
    raise TaskError(f"задача {task_id}: строка не найдена в сводной таблице")


def check_task_dod(text: str, task_id: str) -> str:
    """Отметить все чекбоксы Definition of Done задачи как выполненные."""
    lines = text.splitlines(keepends=True)
    current: str | None = None
    in_dod = False
    for index, line in enumerate(lines):
        heading = _HEADING_RE.match(line)
        if heading:
            current = heading.group(1)
            in_dod = False
            continue
        if line.startswith("#"):
            in_dod = line.startswith("#### Definition of Done")
            continue
        if in_dod and current == task_id:
            lines[index] = line.replace("- [ ]", "- [x]", 1)
    return "".join(lines)


def append_history(text: str, entry: str) -> str:
    """Дописать строку в конец раздела «История изменений спринта»."""
    lines = text.splitlines(keepends=True)
    start: int | None = None
    for index, line in enumerate(lines):
        if _HISTORY_RE.match(line.rstrip("\n")):
            start = index
            break
    if start is None:
        raise TaskError("в файле спринта нет раздела «История изменений спринта»")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1

    lines.insert(end, f"{entry}\n")
    return "".join(lines)


def update_plan_counts(
    plan_text: str, sprint_num: int, counts: tuple[int, int, int]
) -> str:
    """Обновить счётчики спринта в «Сводной таблице состояния» `plan.md`."""
    todo, progress, done = counts
    lines = plan_text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) != 4:
            continue
        match = _PLAN_ROW_RE.match(cells[0])
        if not match or int(match.group(1)) != sprint_num:
            continue
        cells[2] = f"{todo} / {progress} / {done}"
        lines[index] = "| " + " | ".join(cells) + " |\n"
        return "".join(lines)
    raise TaskError(
        f"спринт {sprint_num}: строка не найдена в сводной таблице состояния"
    )


def find_sprint_file(repo_root: Path, sprint_num: int) -> Path:
    """Найти файл спринта по номеру."""
    matches = sorted((repo_root / "_board" / "sprints").glob(f"{sprint_num:02d}-*.md"))
    if not matches:
        raise TaskError(f"спринт {sprint_num}: файл не найден в _board/sprints/")
    return matches[0]


def apply_transition(
    sprint_text: str, action: str, task_id: str, note: str
) -> str:
    """Применить переход ко всем местам в файле спринта."""
    expected, new = _TRANSITIONS[action]
    sprint_text = set_task_status(sprint_text, task_id, expected, new)
    sprint_text = set_summary_row_status(sprint_text, task_id, new)
    if action == "done":
        sprint_text = check_task_dod(sprint_text, task_id)
        tail = note if note.endswith((".", "!", "?")) else f"{note}."
        entry = f"- **{date.today().isoformat()}** — задача {task_id} закрыта: {tail}"
        sprint_text = append_history(sprint_text, entry)
    return sprint_text


def commit(repo_root: Path, paths: list[Path], message: str) -> None:
    """Закоммитить изменённые файлы доски."""
    subprocess.run(
        ["git", "add", *[str(p) for p in paths]],
        cwd=repo_root,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo_root,
        check=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m scripts.task",
        description="Перевод задачи спринта в Progress / Done (process.md §7).",
    )
    parser.add_argument("action", choices=sorted(_TRANSITIONS))
    parser.add_argument("task_id", help="ID задачи в формате <NN>.<этап>.<задача>")
    parser.add_argument(
        "--note",
        default="",
        help="краткое описание для истории спринта (обязательно для done)",
    )
    parser.add_argument(
        "--no-commit",
        action="store_true",
        help="только изменить файлы, без коммита",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parent.parent

    try:
        sprint_num, task_id = parse_task_id(args.task_id)
        if args.action == "done" and not args.note.strip():
            raise TaskError("для done нужен --note: строка в историю спринта")

        sprint_path = find_sprint_file(repo_root, sprint_num)
        plan_path = repo_root / "_board" / "plan.md"

        sprint_text = apply_transition(
            sprint_path.read_text(encoding="utf-8"),
            args.action,
            task_id,
            args.note.strip(),
        )
        counts = count_statuses(parse_sprint_statuses(sprint_text))
        plan_text = update_plan_counts(
            plan_path.read_text(encoding="utf-8"), sprint_num, counts
        )
    except TaskError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    sprint_path.write_text(sprint_text, encoding="utf-8")
    plan_path.write_text(plan_text, encoding="utf-8")

    if check_sprint_sync() != 0:
        print("ERROR: доска рассинхронизирована, коммит не сделан", file=sys.stderr)
        return 1

    verb = "начата" if args.action == "start" else "закрыта"
    message = (
        f"chore(plan): {'начать' if args.action == 'start' else 'закрыть'} "
        f"задачу {args.task_id}"
    )
    if args.no_commit:
        print(f"OK: задача {args.task_id} {verb}, коммит пропущен (--no-commit)")
        return 0

    commit(repo_root, [sprint_path, plan_path], message)
    print(f"OK: задача {args.task_id} {verb}, коммит создан")
    return 0


if __name__ == "__main__":
    sys.exit(main())
