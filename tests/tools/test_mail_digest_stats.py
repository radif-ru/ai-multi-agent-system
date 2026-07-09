"""Тест скрипта mail-digest/stats.py — детерминированный подсчёт сводки."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "app" / "skills" / "mail-digest" / "scripts" / "stats.py"

SAMPLE = {
    "messages": [
        {"uid": "1", "provider": "yandex", "from": "alice@example.com",
         "subject": "Re: hello", "date": "2026-07-08T10:00:00Z", "unread": True},
        {"uid": "2", "provider": "yandex", "from": "bob@example.com",
         "subject": "News", "date": "2026-07-08T12:00:00Z", "unread": False},
        {"uid": "3", "provider": "gmail", "from": "alice@example.com",
         "subject": "FYI", "date": "2026-07-07T09:00:00Z", "unread": True},
        {"uid": "4", "provider": "gmail", "from": "carol@example.com",
         "subject": "Test", "date": "invalid", "unread": False},
    ],
    "warnings": [],
}


def _run_with_file(data: dict, tmp_path: Path) -> dict:
    infile = tmp_path / "mail.json"
    infile.write_text(json.dumps(data), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(infile)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    return json.loads(proc.stdout)


def test_stats_basic(tmp_path: Path) -> None:
    result = _run_with_file(SAMPLE, tmp_path)
    assert result["total"] == 4
    assert result["unread"] == 2
    assert result["read"] == 2


def test_stats_top_senders(tmp_path: Path) -> None:
    result = _run_with_file(SAMPLE, tmp_path)
    senders = dict(result["top_senders"])
    assert senders["alice@example.com"] == 2
    assert senders["bob@example.com"] == 1


def test_stats_by_date(tmp_path: Path) -> None:
    result = _run_with_file(SAMPLE, tmp_path)
    assert result["by_date"]["2026-07-08"] == 2
    assert result["by_date"]["2026-07-07"] == 1
    assert result["by_date"]["unknown"] == 1


def test_stats_empty(tmp_path: Path) -> None:
    result = _run_with_file({"messages": []}, tmp_path)
    assert result["total"] == 0
    assert result["unread"] == 0


def test_stats_stdin() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(SAMPLE),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    result = json.loads(proc.stdout)
    assert result["total"] == 4
