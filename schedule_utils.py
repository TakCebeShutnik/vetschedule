"""Утилиты для работы с расписанием (используются и в API, и в боте)."""
import json
import re
from datetime import date, datetime
from html import escape as html_escape
from pathlib import Path
from typing import Optional
from config import config


def load_group(group_name: str) -> Optional[dict]:
    """Загружает JSON расписания для группы. Возвращает None если не найден."""
    safe = re.sub(r"[^A-Za-zА-Яа-яЁё0-9]", "_", group_name)
    path = config.SCHEDULE_DIR / f"{safe}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_groups() -> list[str]:
    """Список имён групп из папки schedule_json."""
    groups = []
    for p in sorted(config.SCHEDULE_DIR.glob("*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            groups.append(data.get("group", p.stem))
        except Exception:
            pass
    return groups


def get_week(group_data: dict, week_num: int) -> Optional[dict]:
    for w in group_data.get("weeks", []):
        if w["week"] == week_num:
            return w
    return None


def get_day(group_data: dict, day_date: str) -> Optional[dict]:
    """Ищет день по ключу '7/04'."""
    for w in group_data.get("weeks", []):
        for d in w.get("days", []):
            if d["date"] == day_date:
                return d, w
    return None, None


def today_key() -> str:
    t = date.today()
    return f"{t.day}/{t.month:02d}"


def tomorrow_key() -> str:
    from datetime import timedelta
    t = date.today() + timedelta(days=1)
    return f"{t.day}/{t.month:02d}"


def current_iso_week() -> int:
    return date.today().isocalendar()[1]


def classify_lesson(subject: str) -> str:
    """Определяет тип занятия по префиксу."""
    s = subject.lower().strip()
    if s.startswith("л.") or s.startswith("л "):
        return "lecture"
    if s.startswith("лаб.") or s.startswith("лаб "):
        return "lab"
    if s.startswith("пр.") or s.startswith("пр "):
        return "practical"
    return "other"


def weekday_abbr_ru(full_name: str) -> str:
    """Сокращения: Пн., Вт., Ср., Чт., Пт., Сб., Вс."""
    if not full_name:
        return ""
    m = {
        "понедельник": "Пн.",
        "вторник": "Вт.",
        "среда": "Ср.",
        "четверг": "Чт.",
        "пятница": "Пт.",
        "суббота": "Сб.",
        "воскресенье": "Вс.",
    }
    return m.get(full_name.strip().lower(), full_name.strip())


def clean_subject(s: str) -> str:
    """Убирает префикс типа занятия из названия (как в выводе недели в боте)."""
    return re.sub(r"^(л\.|лаб\.|пр\.)\s*", "", s or "", flags=re.IGNORECASE).strip()


def format_week_day_lines(day: dict) -> list[str]:
    """Строки HTML для одного дня — тот же стиль, что у /week в боте."""
    lines = [
        f"<b>📅 {html_escape(day.get('day_name') or '')}, "
        f"{html_escape(day.get('date') or '')}</b>",
    ]
    for ls in day.get("lessons", []):
        subj = clean_subject(ls.get("subject") or "")
        time_s = html_escape(ls.get("time") or "")
        subj_s = html_escape(subj[:45])
        if ls.get("cancelled"):
            lines.append(f"  • <s>{time_s} — {subj_s}</s> ❌ <i>ОТМЕНЕНО</i>")
        else:
            lines.append(f"  • {time_s} — {subj_s}")
        if ls.get("teacher"):
            lines.append(
                f"    👤 {html_escape(ls['teacher'])}  "
                f"🏛 {html_escape(str(ls.get('room') or ''))}"
            )
    return lines


def format_day_text(day: dict) -> str:
    """Один день в том же виде, что блок дня в недельном расписании бота."""
    return "\n".join(format_week_day_lines(day))
