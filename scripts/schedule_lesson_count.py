#!/usr/bin/env python3
"""Считает суммарное число пар во всех schedule_json/*.json.

Используется в .github/workflows/update-schedule.yml как sanity-check:
если после парсинга число пар резко упало (сайт колледжа сменил вёрстку PDF,
парсер тихо всё потерял) — коммит не делаем и шлём алерт вместо того, чтобы
молча закоммитить пустое/битое расписание.
"""
import glob
import json
import sys


def count_lessons(directory: str) -> int:
    total = 0
    for path in glob.glob(f"{directory}/*.json"):
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        for week in data.get("weeks", []):
            for day in week.get("days", []):
                total += len(day.get("lessons", []))
    return total


if __name__ == "__main__":
    directory = sys.argv[1] if len(sys.argv) > 1 else "schedule_json"
    print(count_lessons(directory))
