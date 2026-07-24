"""Тесты парсера естественного языка → cron.

См. спринт 15, задача 4.2.
"""

from __future__ import annotations

from app.services.cron_parser import parse_cron


# --- каждый день ---


def test_every_day_at_9():
    assert parse_cron("каждый день в 9") == "0 9 * * *"


def test_every_day_at_18_30():
    assert parse_cron("каждый день в 18:30") == "30 18 * * *"


def test_every_day_no_time():
    assert parse_cron("каждый день") is None


# --- по будням ---


def test_weekdays_at_9():
    assert parse_cron("по будням в 9") == "0 9 * * 1-5"


def test_weekdays_at_18_30():
    assert parse_cron("по будням в 18:30") == "30 18 * * 1-5"


# --- каждый час ---


def test_every_hour():
    assert parse_cron("каждый час") == "0 * * * *"


# --- каждые N часов ---


def test_every_2_hours():
    assert parse_cron("каждые 2 часа") == "0 */2 * * *"


def test_every_6_hours():
    assert parse_cron("каждые 6 часов") == "0 */6 * * *"


# --- каждые N минут ---


def test_every_30_minutes():
    assert parse_cron("каждые 30 минут") == "*/30 * * * *"


def test_every_15_minutes():
    assert parse_cron("каждые 15 минут") == "*/15 * * * *"


# --- каждую неделю ---


def test_every_week():
    assert parse_cron("каждую неделю") == "0 0 * * 0"


# --- день недели ---


def test_every_monday_at_10():
    assert parse_cron("каждый понедельник в 10") == "0 10 * * 1"


def test_every_friday_at_18_30():
    assert parse_cron("каждую пятницу в 18:30") == "30 18 * * 5"


def test_by_tuesdays_at_12():
    assert parse_cron("по вторникам в 12") == "0 12 * * 2"


# --- число месяца ---


def test_every_1st_of_month():
    assert parse_cron("1-го числа каждого месяца в 10:00") == "0 10 1 * *"


def test_every_15th_of_month_no_time():
    assert parse_cron("каждое 15 число месяца") == "0 0 15 * *"


# --- unsupported ---


def test_unsupported_pattern():
    assert parse_cron("напомни через 10 минут") is None


def test_garbage():
    assert parse_cron("случайный текст") is None


def test_empty():
    assert parse_cron("") is None
