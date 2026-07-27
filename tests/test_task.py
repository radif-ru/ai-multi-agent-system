"""Тесты для scripts/task.py."""

from __future__ import annotations

import pytest

from scripts.task import (
    TaskError,
    append_history,
    apply_transition,
    check_task_dod,
    parse_task_id,
    set_summary_row_status,
    set_task_status,
    update_plan_counts,
)

_SPRINT = """# Спринт 16

## 4. Этап 1. Первый

### Задача 1.1. Первая задача

- **Статус:** ToDo
- **Приоритет:** high

#### Definition of Done

- [ ] Код написан.
- [ ] Тесты зелёные.

### Задача 1.2. Вторая задача

- **Статус:** ToDo
- **Приоритет:** low

#### Definition of Done

- [ ] Документация обновлена.

## 11. Сводная таблица задач спринта

| #   | Задача | Приоритет | Объём | Статус | Зависит от |
|-----|--------|:---------:|:-----:|:------:|:----------:|
| 1.1 | Первая задача | high | M | ToDo | — |
| 1.2 | Вторая задача | low | S | ToDo | — |

## 12. История изменений спринта

- **2026-08-01** — спринт открыт.
"""

_PLAN = """## Сводная таблица состояния

| Спринт | Статус | Задач (ToDo / Progress / Done) | Файл |
|--------|:------:|:------------------------------:|------|
| 15. Пятнадцатый | Closed | 0 / 0 / 16 | `sprints/15-x.md` |
| 16. Шестнадцатый | Active | 2 / 0 / 0 | `sprints/16-y.md` |
"""


def test_parse_task_id_splits_sprint_and_task():
    assert parse_task_id("16.1.1") == (16, "1.1")
    assert parse_task_id("3.12.4") == (3, "12.4")


@pytest.mark.parametrize("raw", ["16.1", "1.1.1.1", "abc", "16..1"])
def test_parse_task_id_rejects_bad_format(raw):
    with pytest.raises(TaskError):
        parse_task_id(raw)


def test_set_task_status_changes_only_target_task():
    result = set_task_status(_SPRINT, "1.1", "ToDo", "Progress")

    assert "### Задача 1.1. Первая задача\n\n- **Статус:** Progress" in result
    assert "### Задача 1.2. Вторая задача\n\n- **Статус:** ToDo" in result


def test_set_task_status_rejects_unexpected_current_status():
    with pytest.raises(TaskError, match="ожидался 'Progress'"):
        set_task_status(_SPRINT, "1.1", "Progress", "Done")


def test_set_task_status_rejects_unknown_task():
    with pytest.raises(TaskError, match="не найден заголовок"):
        set_task_status(_SPRINT, "9.9", "ToDo", "Progress")


def test_set_summary_row_status_updates_matching_row():
    result = set_summary_row_status(_SPRINT, "1.2", "Done")

    assert "| 1.2 | Вторая задача | low | S | Done | — |" in result
    assert "| 1.1 | Первая задача | high | M | ToDo | — |" in result


def test_set_summary_row_status_rejects_missing_row():
    with pytest.raises(TaskError, match="сводной таблице"):
        set_summary_row_status(_SPRINT, "9.9", "Done")


def test_check_task_dod_marks_only_target_task():
    result = check_task_dod(_SPRINT, "1.1")

    assert "- [x] Код написан." in result
    assert "- [x] Тесты зелёные." in result
    assert "- [ ] Документация обновлена." in result


def test_append_history_adds_line_at_section_end():
    result = append_history(_SPRINT, "- **2026-08-02** — задача 1.1 закрыта: сделано.")

    lines = [line for line in result.splitlines() if line.strip()]
    assert lines[-1] == "- **2026-08-02** — задача 1.1 закрыта: сделано."
    assert lines[-2] == "- **2026-08-01** — спринт открыт."


def test_append_history_requires_section():
    with pytest.raises(TaskError, match="История изменений"):
        append_history("# Спринт без истории\n", "- запись")


def test_update_plan_counts_touches_only_target_sprint():
    result = update_plan_counts(_PLAN, 16, (1, 0, 1))

    assert "| 16. Шестнадцатый | Active | 1 / 0 / 1 | `sprints/16-y.md` |" in result
    assert "| 15. Пятнадцатый | Closed | 0 / 0 / 16 | `sprints/15-x.md` |" in result


def test_update_plan_counts_rejects_unknown_sprint():
    with pytest.raises(TaskError, match="спринт 99"):
        update_plan_counts(_PLAN, 99, (0, 0, 0))


def test_apply_transition_start_does_not_touch_dod_or_history():
    result = apply_transition(_SPRINT, "start", "1.1", "")

    assert "- **Статус:** Progress" in result
    assert "| 1.1 | Первая задача | high | M | Progress | — |" in result
    assert "- [ ] Код написан." in result
    assert "задача 1.1 закрыта" not in result


def test_apply_transition_done_closes_all_ritual_points():
    started = apply_transition(_SPRINT, "start", "1.1", "")
    result = apply_transition(started, "done", "1.1", "реализовано и покрыто")

    assert "### Задача 1.1. Первая задача\n\n- **Статус:** Done" in result
    assert "| 1.1 | Первая задача | high | M | Done | — |" in result
    assert "- [x] Код написан." in result
    assert "задача 1.1 закрыта: реализовано и покрыто." in result


def test_apply_transition_done_keeps_existing_final_punctuation():
    started = apply_transition(_SPRINT, "start", "1.1", "")
    result = apply_transition(started, "done", "1.1", "готово.")

    assert "задача 1.1 закрыта: готово." in result
    assert "готово.." not in result
