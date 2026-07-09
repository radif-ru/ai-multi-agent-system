#!/usr/bin/env bash
# Весь ритуал проверок перед коммитом одной командой (git-discipline, шаг 4).
# Запуск из любого места репозитория: bash .agents/skills/git-discipline/scripts/preflight.sh
# Выход: 0 — все проверки зелёные; 1 — первая красная проверка (fail fast).

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

PY=.venv/bin/python
if [ ! -x "$PY" ]; then
    echo "ОШИБКА: нет .venv/bin/python — создай окружение (см. README.md)" >&2
    exit 1
fi

echo "[1/6] flake8..." >&2
"$PY" -m flake8 app tests

echo "[2/6] pytest -q..." >&2
"$PY" -m pytest -q

echo "[3/6] check_env_sync..." >&2
PYTHONPATH=. "$PY" scripts/check_env_sync.py

echo "[4/6] check_sprint_sync..." >&2
python3 scripts/check_sprint_sync.py

echo "[5/6] check_doc_links..." >&2
python3 scripts/check_doc_links.py

echo "[6/6] check_agents_sync..." >&2
python3 .agents/skills/skill-authoring/scripts/check_agents_sync.py

echo "OK: preflight пройден — можно коммитить" >&2
