"""Тесты для scripts/check_sprint_sync.py."""

from __future__ import annotations

from scripts.check_sprint_sync import (
    count_statuses,
    parse_plan_counts,
    parse_sprint_statuses,
)


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
