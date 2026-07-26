"""Тесты для scripts/check_sprint_sync.py."""

from __future__ import annotations

from scripts.check_sprint_sync import (
    check_plan_tables,
    count_statuses,
    find_unchecked_dod,
    parse_plan_counts,
    parse_plan_index,
    parse_plan_state,
    parse_sprint_statuses,
)

_PLAN = """## Индекс спринтов

### Активные

| ID | Название | Файл | Ветка | Статус | Открыт | Закрыт |
|:--:|----------|------|-------|:------:|:------:|:------:|
| 16 | Шестнадцатый | [`sprints/16-x.md`](./sprints/16-x.md) | `feature/16-x` | Active | 2026-08-01 | — |

### Закрытые

| ID | Название | Файл | Ветка | Статус | Открыт | Закрыт |
|:--:|----------|------|-------|:------:|:------:|:------:|
| 15 | Пятнадцатый | [`sprints/15-y.md`](./sprints/15-y.md) | `feature/15-y` | Closed | 2026-07-24 | 2026-07-25 |

## Сводная таблица состояния

| Спринт | Статус | Задач (ToDo / Progress / Done) | Файл |
|--------|:------:|:------------------------------:|------|
| 15. Пятнадцатый | Closed | 0 / 0 / 16 | `sprints/15-y.md` |
| 16. Шестнадцатый | Active | 2 / 1 / 3 | `sprints/16-x.md` |
"""


def test_parse_plan_counts():
    text = (
        "| 12. Качество | Active | 4 / 0 / 10 | `sprints/12-qual.md` |\n"
        "| 11. Perf | Closed | 0 / 0 / 20 | `sprints/11-perf.md` |\n"
    )
    result = parse_plan_counts(text)
    assert 12 in result
    assert result[12] == (4, 0, 10)
    # Closed sprints are not matched (no "Active").
    assert 11 not in result


def test_parse_sprint_statuses():
    text = (
        "### Задача 5.1. Per-user скоуп\n\n"
        "- **Статус:** Done\n\n"
        "### Задача 5.2. Заметка\n\n"
        "- **Статус:** Done\n\n"
        "### Задача 6.1. Guard\n\n"
        "- **Статус:** ToDo\n"
    )
    statuses = parse_sprint_statuses(text)
    assert statuses == {"5.1": "Done", "5.2": "Done", "6.1": "ToDo"}


def test_count_statuses():
    statuses = {"1.1": "Done", "2.1": "ToDo", "3.1": "Progress", "4.1": "Done"}
    todo, progress, done = count_statuses(statuses)
    assert todo == 1
    assert progress == 1
    assert done == 2


def test_count_statuses_empty():
    todo, progress, done = count_statuses({})
    assert (todo, progress, done) == (0, 0, 0)


def test_parse_plan_index_reads_sections():
    assert parse_plan_index(_PLAN) == {
        16: ("Активные", "Active"),
        15: ("Закрытые", "Closed"),
    }


def test_parse_plan_index_skips_placeholder_rows():
    plan = (
        "### Активные\n\n"
        "| ID | Название | Файл | Ветка | Статус | Открыт | Закрыт |\n"
        "| —  | (нет активных спринтов) | — | — | — | — | — |\n"
    )
    assert parse_plan_index(plan) == {}


def test_parse_plan_state_reads_summary_table():
    assert parse_plan_state(_PLAN) == {15: "Closed", 16: "Active"}


def test_check_plan_tables_consistent():
    assert check_plan_tables(_PLAN) == []


def test_check_plan_tables_detects_sprint_left_in_active():
    # Спринт закрыт в сводной таблице, но остался в секции «Активные».
    plan = _PLAN.replace(
        "| 16. Шестнадцатый | Active | 2 / 1 / 3 |",
        "| 16. Шестнадцатый | Closed | 2 / 1 / 3 |",
    )
    errors = check_plan_tables(plan)
    assert len(errors) == 1
    assert "Спринт 16" in errors[0]


def test_check_plan_tables_detects_missing_state_row():
    plan = _PLAN.replace(
        "| 15. Пятнадцатый | Closed | 0 / 0 / 16 | `sprints/15-y.md` |\n", ""
    )
    errors = check_plan_tables(plan)
    assert len(errors) == 1
    assert "нет в сводной" in errors[0]


def test_find_unchecked_dod_reports_done_task():
    sprint = (
        "### Задача 1.1. Первая\n\n"
        "- **Статус:** Done\n\n"
        "#### Definition of Done\n\n"
        "- [x] Условие 1.\n"
        "- [ ] Условие 2.\n"
        "- [ ] Условие 3.\n"
    )
    assert find_unchecked_dod(sprint) == {"1.1": 2}


def test_find_unchecked_dod_ignores_open_tasks_and_other_sections():
    sprint = (
        "### Задача 1.1. Открытая\n\n"
        "- **Статус:** ToDo\n\n"
        "#### Definition of Done\n\n"
        "- [ ] Ещё не сделано.\n\n"
        "### Задача 1.2. Закрытая\n\n"
        "- **Статус:** Done\n\n"
        "#### Описание\n\n"
        "- [ ] Пункт из описания, не DoD.\n\n"
        "#### Definition of Done\n\n"
        "- [x] Всё закрыто.\n"
    )
    assert find_unchecked_dod(sprint) == {}
