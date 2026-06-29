"""Проверка синхронизации `Settings` ↔ `.env.example` (спринт 12, задача 3.2).

Автоматизация без ИИ правила из `_docs/instructions.md` §7: любой настраиваемый
параметр `Settings` должен иметь запись в `.env.example` (хотя бы
закомментированную, с описанием), чтобы его можно было менять без правки кода.

Скрипт сравнивает имена полей `Settings` (в верхнем регистре) с переменными,
объявленными в `.env.example` (включая закомментированные `# VAR=...`), и
завершается с ненулевым кодом, если найдено настраиваемое поле без записи.
Секреты (`SECRET_FIELDS`) из требования исключены: их значение в `.env.example`
держат пустым/плейсхолдером, и их отсутствие не должно валить проверку.

Запуск из корня репозитория:

    python -m scripts.check_env_sync
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from app.config import Settings

# Секреты: проверку их наличия в .env.example не форсируем (см. instructions §7).
SECRET_FIELDS: frozenset[str] = frozenset(
    {"telegram_bot_token", "max_bot_token", "sentry_dsn"}
)

_ENV_VAR_RE = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)\s*=")


def settings_env_vars() -> set[str]:
    """Имена настраиваемых полей `Settings` в формате env-переменных."""
    return {name.upper() for name in Settings.model_fields}


def parse_env_example(text: str) -> set[str]:
    """Извлечь имена объявленных переменных из `.env.example`.

    Учитываются и активные (`VAR=...`), и закомментированные (`# VAR=...`)
    объявления — закомментированная запись с описанием считается достаточной.
    """
    found: set[str] = set()
    for line in text.splitlines():
        match = _ENV_VAR_RE.match(line)
        if match:
            found.add(match.group(1))
    return found


def find_missing(env_example_text: str) -> set[str]:
    """Поля `Settings` (кроме секретов), отсутствующие в `.env.example`."""
    declared = parse_env_example(env_example_text)
    required = settings_env_vars() - {f.upper() for f in SECRET_FIELDS}
    return required - declared


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    env_example = repo_root / ".env.example"
    if not env_example.exists():
        print(f"ERROR: не найден {env_example.name}", file=sys.stderr)
        return 1

    missing = find_missing(env_example.read_text(encoding="utf-8"))
    if missing:
        print(
            "ERROR: поля Settings без записи в .env.example:\n  "
            + "\n  ".join(sorted(missing)),
            file=sys.stderr,
        )
        return 1

    print("OK: Settings и .env.example синхронизированы")
    return 0


if __name__ == "__main__":
    sys.exit(main())
