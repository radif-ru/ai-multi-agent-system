"""Тесты скрипта `scripts/check_env_sync.py` (спринт 12, задача 3.2)."""

from __future__ import annotations

from app.config import Settings
from scripts.check_env_sync import (
    SECRET_FIELDS,
    find_missing,
    parse_env_example,
    settings_env_vars,
)


def test_parse_env_example_active_and_commented() -> None:
    text = (
        "# комментарий\n"
        "OLLAMA_BASE_URL=http://localhost:11434\n"
        "# MAX_BOT_TOKEN=\n"
        "   # DANGEROUS_TOOLS_ALLOWLIST=read_file\n"
        "не_переменная\n"
    )
    assert parse_env_example(text) == {
        "OLLAMA_BASE_URL",
        "MAX_BOT_TOKEN",
        "DANGEROUS_TOOLS_ALLOWLIST",
    }


def test_settings_env_vars_uppercase() -> None:
    names = settings_env_vars()
    assert "OLLAMA_BASE_URL" in names
    assert all(name == name.upper() for name in names)


def test_find_missing_detects_absent_non_secret_field() -> None:
    # Полный .env.example, но без READ_FILE_MAX_BYTES → поле должно «потеряться».
    sample = "".join(
        f"{name}=x\n"
        for name in settings_env_vars()
        if name != "READ_FILE_MAX_BYTES"
    )
    assert find_missing(sample) == {"READ_FILE_MAX_BYTES"}


def test_find_missing_ignores_secrets() -> None:
    # .env.example без единой секретной переменной — проверка не падает.
    secret_vars = {f.upper() for f in SECRET_FIELDS}
    sample = "".join(
        f"{name}=x\n"
        for name in settings_env_vars()
        if name not in secret_vars
    )
    assert find_missing(sample) == set()


def test_secret_fields_are_real_settings_fields() -> None:
    assert SECRET_FIELDS <= set(Settings.model_fields)
