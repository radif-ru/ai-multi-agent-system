#!/usr/bin/env python3
"""Сводка по письмам из JSON-вывода email_list.

Читает JSON из stdin или файла (--input <path>), считает:
- всего / непрочитанных
- топ отправителей (по убыванию, до 10)
- распределение по датам (YYYY-MM-DD)

Вывод: JSON-объект на stdout.
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime


def compute_stats(messages: list[dict]) -> dict:
    total = len(messages)
    unread = sum(1 for m in messages if m.get("unread"))
    senders = Counter(m.get("from", "?") for m in messages)
    dates = Counter()
    for m in messages:
        raw = m.get("date", "")
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            dates[dt.strftime("%Y-%m-%d")] += 1
        except (ValueError, TypeError):
            dates["unknown"] += 1
    return {
        "total": total,
        "unread": unread,
        "read": total - unread,
        "top_senders": senders.most_common(10),
        "by_date": dict(sorted(dates.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Mail digest stats")
    parser.add_argument(
        "--input", help="Path to JSON file (default: stdin)"
    )
    args = parser.parse_args()

    if args.input:
        with open(args.input, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    messages = data.get("messages", []) if isinstance(data, dict) else data
    result = compute_stats(messages)
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
