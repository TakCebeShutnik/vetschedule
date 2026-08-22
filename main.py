#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI-бэкенд расписания ветеринарной академии.
Запуск: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""
import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from config import config
from database import init_db, get_db, Homework, HomeworkFile, User
from lesson_overrides import apply_to_weeks, apply_to_day, toggle_override
from schedule_utils import load_group, list_groups, get_week, classify_lesson
from file_storage import save_homework_file, file_download_response, delete_homework_file

# ─── Инициализация ───────────────────────────────────────────────────────────

init_db()
app = FastAPI(title="VetSchedule API", version="1.0.0")

_cors_raw = (config.CORS_ORIGINS or "*").strip()
_cors_origins = ["*"] if _cors_raw == "*" else [o.strip() for o in _cors_raw.split(",") if o.strip()]
_cors_credentials = _cors_origins != ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Pydantic-схемы ─────────────────────────────────────────────────────────

class HWCreate(BaseModel):
    group_name: str
    subject: str
    description: Optional[str] = None
    deadline: Optional[str] = None     # ISO datetime string or "YYYY-MM-DD"
    created_by_tg: Optional[int] = None
    editor_code: Optional[str] = None

class HWUpdate(BaseModel):
    subject: Optional[str] = None
    description: Optional[str] = None
    deadline: Optional[str] = None
    status: Optional[str] = None       # pending | in_progress | done
    editor_code: Optional[str] = None

class UserCreate(BaseModel):
    telegram_id: Optional[int] = None
    name: str
    group_name: Optional[str] = None


class LessonOverrideToggle(BaseModel):
    editor_code: str
    group_name: str
    day_date: str
    time: str
    subject: str
    note: Optional[str] = None

# ─── Helpers ─────────────────────────────────────────────────────────────────

def parse_deadline(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def require_editor_code(code: Optional[str]) -> None:
    if not code or code.strip() != config.EDITOR_CODE:
        raise HTTPException(403, "Неверный код доступа")


def _enrich_weeks(group: str, weeks: list, db: Session) -> None:
    for week in weeks:
        for day in week.get("days", []):
            for ls in day.get("lessons", []):
                ls["type"] = classify_lesson(ls["subject"])
    apply_to_weeks(group, weeks, db)


def _enrich_day(group: str, day: dict, db: Session) -> None:
    for ls in day.get("lessons", []):
        ls["type"] = classify_lesson(ls["subject"])
    apply_to_day(group, day, db)


def hw_to_dict(hw: Homework) -> dict:
    return {
        "id":          hw.id,
        "group_name":  hw.group_name,
        "subject":     hw.subject,
        "description": hw.description,
        "deadline":    hw.deadline.isoformat() if hw.deadline else None,
        "status":      hw.status,
        "created_at":  hw.created_at.isoformat(),
        "files": [
            {"id": f.id, "filename": f.filename, "url": f"/api/files/{f.id}"}
            for f in hw.files
        ],
    }


# ─── Schedule endpoints ──────────────────────────────────────────────────────

@app.get("/api/health")
def api_health(db: Session = Depends(get_db)):
    """Для аптайм-мониторинга (UptimeRobot и т.п.): проверяет БД и наличие расписаний."""
    checks = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
    groups = list_groups()
    checks["schedule_groups"] = len(groups)
    healthy = checks["database"] == "ok" and checks["schedule_groups"] > 0
    return {"status": "ok" if healthy else "degraded", **checks}


@app.get("/api/groups")
def api_groups():
    """Список всех доступных групп."""
    return {"groups": list_groups()}


@app.get("/api/schedule/{group}")
def api_schedule(group: str, db: Session = Depends(get_db)):
    """Полное расписание группы."""
    data = load_group(group)
    if data is None:
        raise HTTPException(404, f"Расписание группы '{group}' не найдено")
    _enrich_weeks(group, data.get("weeks", []), db)
    return data


@app.get("/api/schedule/{group}/week/{week_num}")
def api_schedule_week(group: str, week_num: int, db: Session = Depends(get_db)):
    """Расписание конкретной недели (ISO номер)."""
    data = load_group(group)
    if data is None:
        raise HTTPException(404, "Группа не найдена")
    week = get_week(data, week_num)
    if week is None:
        raise HTTPException(404, f"Неделя {week_num} не найдена в расписании")
    _enrich_weeks(group, [week], db)
    return week


@app.get("/api/schedule/{group}/today")
def api_today(group: str, db: Session = Depends(get_db)):
    from schedule_utils import today_key, get_day
    data = load_group(group)
    if data is None:
        raise HTTPException(404, "Группа не найдена")
    day, week = get_day(data, today_key())
    if day is None:
        return {"message": "Сегодня занятий нет", "day": None}
    _enrich_day(group, day, db)
    return {"day": day, "week": week}


@app.get("/api/schedule/{group}/tomorrow")
def api_tomorrow(group: str, db: Session = Depends(get_db)):
    from schedule_utils import tomorrow_key, get_day
    data = load_group(group)
    if data is None:
        raise HTTPException(404, "Группа не найдена")
    day, week = get_day(data, tomorrow_key())
    if day is None:
        return {"message": "Завтра занятий нет", "day": None}
    _enrich_day(group, day, db)
    return {"day": day, "week": week}


@app.post("/api/lesson-overrides/toggle")
async def api_lesson_override_toggle(
    body: LessonOverrideToggle,
    db: Session = Depends(get_db),
):
    """Отметить пару отменённой или вернуть (нужен код редактора)."""
    require_editor_code(body.editor_code)
    if not load_group(body.group_name):
        raise HTTPException(404, "Группа не найдена")
    result = toggle_override(
        db,
        body.group_name,
        body.day_date,
        body.time,
        body.subject,
        body.note,
    )
    # Ждём отправку синхронно (не через BackgroundTasks) — см. пояснение
    # в api_hw_create: на Vercel фоновая задача может не успеть выполниться.
    try:
        from bot import notify_lesson_override
        await notify_lesson_override(
            body.group_name, body.day_date, body.time, body.subject,
            result["cancelled"], body.note,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("notify_lesson_override failed: %s", e)
    return result


# ─── Homework endpoints ──────────────────────────────────────────────────────

@app.get("/api/homework")
def api_hw_list(
    group: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    q = db.query(Homework)
    if group:
        q = q.filter(Homework.group_name == group)
    if status:
        q = q.filter(Homework.status == status)
    if from_date:
        dt = parse_deadline(from_date)
        if dt:
            q = q.filter(Homework.deadline >= dt)
    if to_date:
        dt = parse_deadline(to_date)
        if dt:
            q = q.filter(Homework.deadline <= dt)
    items = q.order_by(Homework.deadline.asc().nullslast()).all()
    return {"homework": [hw_to_dict(h) for h in items]}


@app.get("/api/homework/{hw_id}")
def api_hw_get(hw_id: int, db: Session = Depends(get_db)):
    hw = db.get(Homework, hw_id)
    if not hw:
        raise HTTPException(404, "ДЗ не найдено")
    return hw_to_dict(hw)


@app.post("/api/homework", status_code=201)
async def api_hw_create(body: HWCreate, db: Session = Depends(get_db)):
    require_editor_code(body.editor_code)
    user_id = None
    if body.created_by_tg:
        user = db.query(User).filter(User.telegram_id == body.created_by_tg).first()
        if user:
            user_id = user.id

    hw = Homework(
        group_name  = body.group_name,
        subject     = body.subject,
        description = body.description,
        deadline    = parse_deadline(body.deadline),
        status      = "pending",
        created_by  = user_id,
    )
    db.add(hw)
    db.commit()
    db.refresh(hw)
    # Ждём отправку синхронно (не через BackgroundTasks): на serverless
    # (Vercel) функция может "заморозиться" сразу после ответа, и фоновая
    # задача не успевает доработать — сообщение в Telegram просто не уйдёт.
    try:
        from bot import notify_new_homework
        await notify_new_homework(hw.id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("notify_new_homework failed: %s", e)
    return hw_to_dict(hw)


@app.put("/api/homework/{hw_id}")
def api_hw_update(hw_id: int, body: HWUpdate, db: Session = Depends(get_db)):
    hw = db.get(Homework, hw_id)
    if not hw:
        raise HTTPException(404, "ДЗ не найдено")
    # Менять статус (pending/in_progress/done) может любой студент без кода.
    # Редактирование содержимого задания (тема/описание/срок) требует кода редактора.
    if body.subject is not None or body.description is not None or body.deadline is not None:
        require_editor_code(body.editor_code)
    if body.subject is not None:
        hw.subject = body.subject
    if body.description is not None:
        hw.description = body.description
    if body.deadline is not None:
        hw.deadline = parse_deadline(body.deadline)
    if body.status is not None:
        if body.status not in ("pending", "in_progress", "done"):
            raise HTTPException(400, "Неверный статус")
        hw.status = body.status
    db.commit()
    db.refresh(hw)
    return hw_to_dict(hw)


@app.delete("/api/homework/{hw_id}", status_code=204)
def api_hw_delete(hw_id: int, editor_code: Optional[str] = Query(None), db: Session = Depends(get_db)):
    require_editor_code(editor_code)
    hw = db.get(Homework, hw_id)
    if not hw:
        raise HTTPException(404, "ДЗ не найдено")
    db.delete(hw)
    db.commit()


MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 МБ
ALLOWED_UPLOAD_EXT = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".rtf", ".odt", ".ods", ".odp",
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".zip", ".rar",
}


@app.post("/api/homework/{hw_id}/files")
async def api_hw_upload(
    hw_id: int,
    file: UploadFile = File(...),
    editor_code: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    require_editor_code(editor_code)
    hw = db.get(Homework, hw_id)
    if not hw:
        raise HTTPException(404, "ДЗ не найдено")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXT:
        raise HTTPException(415, f"Тип файла не поддерживается ({ext or 'без расширения'})")
    hf = await save_homework_file(db, hw_id, file, max_bytes=MAX_UPLOAD_BYTES)
    return {"id": hf.id, "filename": hf.filename, "url": f"/api/files/{hf.id}"}


@app.get("/api/files/{file_id}")
def api_file_download(file_id: int, db: Session = Depends(get_db)):
    hf = db.get(HomeworkFile, file_id)
    if not hf:
        raise HTTPException(404, "Файл не найден")
    try:
        return file_download_response(hf)
    except FileNotFoundError:
        raise HTTPException(404, "Файл не найден")


@app.delete("/api/homework/{hw_id}/files/{file_id}", status_code=204)
def api_hw_file_delete(
    hw_id: int,
    file_id: int,
    editor_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    require_editor_code(editor_code)
    hf = db.get(HomeworkFile, file_id)
    if not hf or hf.hw_id != hw_id:
        raise HTTPException(404, "Файл не найден")
    delete_homework_file(hf)
    db.delete(hf)
    db.commit()


# ─── User endpoints ──────────────────────────────────────────────────────────

@app.post("/api/users", status_code=201)
def api_user_create(body: UserCreate, db: Session = Depends(get_db)):
    if body.telegram_id:
        existing = db.query(User).filter(User.telegram_id == body.telegram_id).first()
        if existing:
            existing.name       = body.name
            existing.group_name = body.group_name
            db.commit()
            db.refresh(existing)
            return {"id": existing.id, "created": False}
    user = User(telegram_id=body.telegram_id, name=body.name, group_name=body.group_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "created": True}


@app.get("/api/users/{telegram_id}")
def api_user_get(telegram_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    return {"id": user.id, "name": user.name, "group_name": user.group_name}


# ─── Telegram webhook (Vercel / без long-polling) ────────────────────────────

def _check_cron_secret(secret: Optional[str]) -> None:
    if not config.CRON_SECRET or secret != config.CRON_SECRET:
        raise HTTPException(403, "Forbidden")


@app.post("/api/telegram/webhook")
async def api_telegram_webhook(request: Request):
    """Точка входа для Telegram при TELEGRAM_MODE=webhook."""
    if not config.TELEGRAM_TOKEN:
        raise HTTPException(503, "TELEGRAM_TOKEN не задан")
    from bot import process_webhook_update

    await process_webhook_update(await request.json())
    return {"ok": True}


@app.post("/api/cron/cleanup")
@app.get("/api/cron/cleanup")
def api_cron_cleanup(secret: str = Query(...), days: int = Query(180), db: Session = Depends(get_db)):
    """Удаляет вложения (не сами задания) у ДЗ с дедлайном старше N дней —
    файлы хранятся как BYTEA в Postgres, на бесплатном Neon это не бесконечно.
    Вызывается внешним планировщиком (см. .github/workflows/send-reminders.yml)."""
    _check_cron_secret(secret)
    cutoff = datetime.utcnow() - timedelta(days=days)
    old_hw_ids = [
        hw.id for hw in
        db.query(Homework).filter(Homework.deadline.isnot(None), Homework.deadline < cutoff).all()
    ]
    if not old_hw_ids:
        return {"ok": True, "deleted_files": 0}
    files = db.query(HomeworkFile).filter(HomeworkFile.hw_id.in_(old_hw_ids)).all()
    deleted = len(files)
    for f in files:
        db.delete(f)
    db.commit()
    return {"ok": True, "deleted_files": deleted, "checked_homework": len(old_hw_ids)}


@app.post("/api/cron/reminders")
@app.get("/api/cron/reminders")
async def api_cron_reminders(secret: str = Query(...)):
    """Дёргается внешним планировщиком (GitHub Actions/cron-job.org) раз в N минут,
    т.к. на serverless (Vercel, webhook-режим) job_queue бота не запускается —
    см. bot.build_application(). Требует CRON_SECRET."""
    _check_cron_secret(secret)
    if not config.TELEGRAM_TOKEN:
        raise HTTPException(503, "TELEGRAM_TOKEN не задан")
    from bot import run_reminders_once

    await run_reminders_once()
    return {"ok": True}


@app.get("/api/telegram/setup-webhook")
async def api_telegram_setup_webhook(secret: str = Query(...)):
    """Один раз после деплоя: ?secret=CRON_SECRET — привязать webhook к SITE_URL."""
    _check_cron_secret(secret)
    if not config.TELEGRAM_TOKEN:
        raise HTTPException(503, "TELEGRAM_TOKEN не задан")
    from bot import register_webhook

    url = await register_webhook()
    return {"ok": True, "webhook_url": url}


# ─── Static / SPA ────────────────────────────────────────────────────────────

static_dir = Path("static")


@app.get("/favicon.ico", include_in_schema=False)
def favicon_ico():
    svg = static_dir / "favicon.svg"
    if svg.is_file():
        return FileResponse(svg, media_type="image/svg+xml")
    raise HTTPException(404)


if static_dir.exists():
    app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
