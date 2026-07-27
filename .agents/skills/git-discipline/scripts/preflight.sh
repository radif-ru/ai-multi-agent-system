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

echo "[1/7] артефакты в индексе..." >&2
# Файл, попадающий под .gitignore (.env, data/, *.db, logs/, graphify-out/, кэши),
# не должен быть отслеживаемым или застейдженным — чаще всего это `git add -f`
# или `git add .` до появления паттерна в .gitignore.
tracked_ignored=$(git ls-files --cached --ignored --exclude-standard)
if [ -n "$tracked_ignored" ]; then
    echo "ОШИБКА: игнорируемые файлы попали в git (убери через git rm --cached):" >&2
    echo "$tracked_ignored" | sed 's/^/  - /' >&2
    exit 1
fi

echo "[2/7] flake8..." >&2
"$PY" -m flake8 app tests

echo "[3/7] pytest -q..." >&2
"$PY" -m pytest -q

echo "[4/7] check_env_sync..." >&2
PYTHONPATH=. "$PY" scripts/check_env_sync.py

echo "[5/7] check_sprint_sync..." >&2
python3 scripts/check_sprint_sync.py

echo "[6/7] check_doc_links..." >&2
python3 scripts/check_doc_links.py

echo "[7/7] check_agents_sync..." >&2
python3 .agents/skills/skill-authoring/scripts/check_agents_sync.py

echo "OK: preflight пройден — можно коммитить" >&2
