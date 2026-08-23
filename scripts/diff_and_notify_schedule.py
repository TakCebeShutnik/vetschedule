#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сравнивает schedule_json/*.json ДО и ПОСЛЕ прогона парсера и, если что-то
реально изменилось (не просто пересчитался diff из-за иного форматирования),
шлёт уведомление студентам группы через /api/cron/schedule-changed.

Запускается в .github/workflows/update-schedule.yml ПОСЛЕ парсинга, но ДО
git commit — старая версия файла ещё лежит в HEAD (git show), а новая уже
на диске (перезаписана парсером).

Не требует новых зависимостей — использует git (уже есть в раннере) и
requests (уже в requirements.txt).
"""
import glob
import json
import os
import subprocess
import sys

import requests

SCHEDULE_DIR = "schedule_json"
MAX_DATES_IN_MESSAGE = 6


def _old_file_content(path: str) -> str | None:
    """Содержимое файла в последнем коммите (до парсинга). None, если файла
    не было (новая группа) — тогда сравнивать не с чем, просто пропускаем."""
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD:{path}"],
            capture_output=True, text=True, check=True,
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return None


def _lesson_key(day: dict) -> dict:
    """{'1/09': [(time, subject, teacher, room), ...], ...} — отсортировано,
    чтобы порядок пар в JSON не считался изменением, только их содержимое."""
    out = {}
    for day_entry in day:
        date = day_entry.get("date")
        lessons = sorted(
            (l.get("time", ""), l.get("subject", ""), l.get("teacher", ""), l.get("room", ""))
            for l in day_entry.get("lessons", [])
        )
        out[date] = lessons
    return out


def diff_group(old_json: dict, new_json: dict) -> list[str]:
    """Возвращает список дат, у которых пары реально отличаются."""
    old_by_week = {w["week"]: _lesson_key(w["days"]) for w in old_json.get("weeks", [])}
    new_by_week = {w["week"]: _lesson_key(w["days"]) for w in new_json.get("weeks", [])}

    changed_dates = []
    all_weeks = set(old_by_week) | set(new_by_week)
    for week in sorted(all_weeks):
        old_days = old_by_week.get(week, {})
        new_days = new_by_week.get(week, {})
        for date in sorted(set(old_days) | set(new_days)):
            if old_days.get(date, []) != new_days.get(date, []):
                changed_dates.append(date)
    return changed_dates


def main():
    site_url = os.environ.get("SITE_URL", "").rstrip("/")
    secret = os.environ.get("CRON_SECRET", "")
    if not site_url or not secret:
        print("SITE_URL / CRON_SECRET не заданы — уведомления об изменениях пропущены")
        return 0

    notified = 0
    for path in sorted(glob.glob(f"{SCHEDULE_DIR}/*.json")):
        old_text = _old_file_content(path)
        if old_text is None:
            continue  # новый файл — не с чем сравнивать
        try:
            old_json = json.loads(old_text)
            new_json = json.loads(open(path, encoding="utf-8").read())
        except json.JSONDecodeError:
            continue

        changed_dates = diff_group(old_json, new_json)
        if not changed_dates:
            continue

        group = new_json.get("group") or old_json.get("group") or "?"
        shown = changed_dates[:MAX_DATES_IN_MESSAGE]
        dates_str = ", ".join(shown)
        if len(changed_dates) > MAX_DATES_IN_MESSAGE:
            dates_str += f" и ещё {len(changed_dates) - MAX_DATES_IN_MESSAGE}"
        message = (
            "📋 <b>Расписание обновилось</b>\n"
            f"Изменения на: {dates_str}\n\n"
            "Открой /schedule или /week, чтобы посмотреть подробности."
        )
        try:
            r = requests.post(
                f"{site_url}/api/cron/schedule-changed",
                params={"secret": secret},
                json={"group": group, "message": message},
                timeout=15,
            )
            r.raise_for_status()
            notified += 1
            print(f"Уведомили группу {group}: {len(changed_dates)} дат изменилось")
        except requests.RequestException as e:
            print(f"Не удалось уведомить {group}: {e}", file=sys.stderr)

    print(f"Готово, уведомлено групп: {notified}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
