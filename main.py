#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI-бэкенд расписания ветеринарной академии.
Запуск: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""
import os
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import config
from database import init_db, get_db, Homework, HomeworkFile, User
from schedule_utils import load_group, list_groups, get_week, classify_lesson

# ─── Инициализация ───────────────────────────────────────────────────────────

init_db()
app = FastAPI(title="VetSchedule API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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

class HWUpdate(BaseModel):
    subject: Optional[str] = None
    description: Optional[str] = None
    deadline: Optional[str] = None
    status: Optional[str] = None       # pending | in_progress | done

class UserCreate(BaseModel):
    telegram_id: Optional[int] = None
    name: str
    group_name: Optional[str] = None

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

@app.get("/api/groups")
def api_groups():
    """Список всех доступных групп."""
    return {"groups": list_groups()}


@app.get("/api/schedule/{group}")
def api_schedule(group: str):
    """Полное расписание группы."""
    data = load_group(group)
    if data is None:
        raise HTTPException(404, f"Расписание группы '{group}' не найдено")
    # Обогащаем каждое занятие типом
    for week in data.get("weeks", []):
        for day in week.get("days", []):
            for ls in day.get("lessons", []):
                ls["type"] = classify_lesson(ls["subject"])
    return data


@app.get("/api/schedule/{group}/week/{week_num}")
def api_schedule_week(group: str, week_num: int):
    """Расписание конкретной недели (ISO номер)."""
    data = load_group(group)
    if data is None:
        raise HTTPException(404, "Группа не найдена")
    week = get_week(data, week_num)
    if week is None:
        raise HTTPException(404, f"Неделя {week_num} не найдена в расписании")
    for day in week.get("days", []):
        for ls in day.get("lessons", []):
            ls["type"] = classify_lesson(ls["subject"])
    return week


@app.get("/api/schedule/{group}/today")
def api_today(group: str):
    from schedule_utils import today_key, get_day
    data = load_group(group)
    if data is None:
        raise HTTPException(404, "Группа не найдена")
    day, week = get_day(data, today_key())
    if day is None:
        return {"message": "Сегодня занятий нет", "day": None}
    for ls in day.get("lessons", []):
        ls["type"] = classify_lesson(ls["subject"])
    return {"day": day, "week": week}


@app.get("/api/schedule/{group}/tomorrow")
def api_tomorrow(group: str):
    from schedule_utils import tomorrow_key, get_day
    data = load_group(group)
    if data is None:
        raise HTTPException(404, "Группа не найдена")
    day, week = get_day(data, tomorrow_key())
    if day is None:
        return {"message": "Завтра занятий нет", "day": None}
    for ls in day.get("lessons", []):
        ls["type"] = classify_lesson(ls["subject"])
    return {"day": day, "week": week}


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
def api_hw_create(body: HWCreate, db: Session = Depends(get_db)):
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
    return hw_to_dict(hw)


@app.put("/api/homework/{hw_id}")
def api_hw_update(hw_id: int, body: HWUpdate, db: Session = Depends(get_db)):
    hw = db.get(Homework, hw_id)
    if not hw:
        raise HTTPException(404, "ДЗ не найдено")
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
def api_hw_delete(hw_id: int, db: Session = Depends(get_db)):
    hw = db.get(Homework, hw_id)
    if not hw:
        raise HTTPException(404, "ДЗ не найдено")
    db.delete(hw)
    db.commit()


@app.post("/api/homework/{hw_id}/files")
async def api_hw_upload(hw_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    hw = db.get(Homework, hw_id)
    if not hw:
        raise HTTPException(404, "ДЗ не найдено")
    ext = Path(file.filename).suffix
    fname = f"{uuid.uuid4()}{ext}"
    dest = config.UPLOADS_DIR / fname
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    hf = HomeworkFile(hw_id=hw_id, filename=file.filename, filepath=str(dest))
    db.add(hf)
    db.commit()
    db.refresh(hf)
    return {"id": hf.id, "filename": hf.filename, "url": f"/api/files/{hf.id}"}


@app.get("/api/files/{file_id}")
def api_file_download(file_id: int, db: Session = Depends(get_db)):
    hf = db.get(HomeworkFile, file_id)
    if not hf or not Path(hf.filepath).exists():
        raise HTTPException(404, "Файл не найден")
    return FileResponse(hf.filepath, filename=hf.filename)


@app.delete("/api/homework/{hw_id}/files/{file_id}", status_code=204)
def api_hw_file_delete(hw_id: int, file_id: int, db: Session = Depends(get_db)):
    hf = db.get(HomeworkFile, file_id)
    if not hf or hf.hw_id != hw_id:
        raise HTTPException(404, "Файл не найден")
    p = Path(hf.filepath)
    if p.is_file():
        try:
            p.unlink()
        except OSError:
            pass
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


# ─── Static / SPA ────────────────────────────────────────────────────────────

static_dir = Path("static")


@app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
def chrome_devtools_stub():
    """Пустой ответ для Chrome DevTools — убирает лишний 404 в логах."""
    return {}


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
