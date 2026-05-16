"""Отмены пар поверх JSON-расписания (не правим файл расписания)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from database import LessonOverride


def lesson_key(group_name: str, day_date: str, lesson: dict) -> str:
    time = (lesson.get("time") or "").strip()
    subj = (lesson.get("subject") or "").strip()
    return f"{group_name}|{day_date}|{time}|{subj}"


def _parse_key(key: str) -> tuple[str, str, str, str]:
    parts = key.split("|", 3)
    if len(parts) != 4:
        raise ValueError("invalid lesson key")
    return parts[0], parts[1], parts[2], parts[3]


def overrides_map(db: Session, group_name: str) -> dict[str, LessonOverride]:
    rows = (
        db.query(LessonOverride)
        .filter(
            LessonOverride.group_name == group_name,
            LessonOverride.cancelled.is_(True),
        )
        .all()
    )
    return {r.lesson_key: r for r in rows}


def apply_to_lessons(
    group_name: str,
    day_date: str,
    lessons: list,
    by_key: dict[str, LessonOverride],
) -> None:
    for ls in lessons:
        key = lesson_key(group_name, day_date, ls)
        row = by_key.get(key)
        ls["lesson_key"] = key
        ls["cancelled"] = bool(row)
        ls["cancel_note"] = (row.note or "").strip() if row else None
        ls["override_id"] = row.id if row else None


def apply_to_weeks(group_name: str, weeks: list, db: Session) -> None:
    by_key = overrides_map(db, group_name)
    for week in weeks:
        for day in week.get("days", []):
            apply_to_lessons(group_name, day.get("date") or "", day.get("lessons") or [], by_key)


def apply_to_day(group_name: str, day: Optional[dict], db: Session) -> None:
    if not day:
        return
    by_key = overrides_map(db, group_name)
    apply_to_lessons(group_name, day.get("date") or "", day.get("lessons") or [], by_key)


def toggle_override(
    db: Session,
    group_name: str,
    day_date: str,
    time: str,
    subject: str,
    note: Optional[str] = None,
) -> dict:
    """Переключить отмену. Возвращает {cancelled, lesson_key, override_id}."""
    key = lesson_key(group_name, day_date, {"time": time, "subject": subject})
    row = db.query(LessonOverride).filter(LessonOverride.lesson_key == key).first()
    if row and row.cancelled:
        db.delete(row)
        db.commit()
        return {"cancelled": False, "lesson_key": key, "override_id": None}
    if row:
        row.cancelled = True
        row.note = note
        db.commit()
        db.refresh(row)
        return {"cancelled": True, "lesson_key": key, "override_id": row.id}
    row = LessonOverride(
        group_name=group_name,
        day_date=day_date.strip(),
        lesson_time=time.strip(),
        subject=subject.strip(),
        lesson_key=key,
        cancelled=True,
        note=(note or "").strip() or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"cancelled": True, "lesson_key": key, "override_id": row.id}
