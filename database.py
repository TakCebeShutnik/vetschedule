from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, Text, Boolean, ForeignKey, LargeBinary,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.pool import NullPool
from datetime import datetime

_engine = None
_SessionLocal = None


def _get_database_url() -> str:
    from config import config
    return config.DATABASE_URL


def _get_engine():
    global _engine, _SessionLocal
    if _engine is not None:
        return _engine
    url = _get_database_url()
    _is_sqlite = "sqlite" in url.lower()
    kw: dict = {"echo": False}
    if _is_sqlite:
        kw["connect_args"] = {"check_same_thread": False}
    else:
        kw["poolclass"] = NullPool
        kw["pool_pre_ping"] = True
    _engine = create_engine(url, **kw)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    return _engine


Base = declarative_base()


# ─── Модели ─────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    id           = Column(Integer, primary_key=True, index=True)
    telegram_id  = Column(Integer, unique=True, nullable=True, index=True)
    name         = Column(String(120), nullable=False)
    group_name   = Column(String(60), nullable=True)
    is_admin     = Column(Boolean, default=False)
    created_at   = Column(DateTime, default=datetime.utcnow)
    notify_hours = Column(Integer, nullable=True)  # личная настройка "за сколько часов напомнить"; NULL = дефолт
    homework     = relationship("Homework", back_populates="creator", foreign_keys="Homework.created_by")


class Homework(Base):
    __tablename__ = "homework"
    id          = Column(Integer, primary_key=True, index=True)
    group_name  = Column(String(60), nullable=False, index=True)
    subject     = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    deadline    = Column(DateTime, nullable=True)
    # pending | in_progress | done
    status      = Column(String(20), nullable=False, default="pending")
    created_by  = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)
    notified    = Column(Boolean, default=False)   # флаг: уведомление отправлено
    creator     = relationship("User", back_populates="homework", foreign_keys=[created_by])
    files       = relationship("HomeworkFile", back_populates="homework", cascade="all, delete-orphan")
    messages    = relationship("HomeworkMessage", back_populates="homework", cascade="all, delete-orphan")
    personal_statuses = relationship("HomeworkStatus", back_populates="homework", cascade="all, delete-orphan")
    reminder_log      = relationship("HomeworkReminderLog", back_populates="homework", cascade="all, delete-orphan")


class HomeworkFile(Base):
    __tablename__ = "homework_files"
    id           = Column(Integer, primary_key=True, index=True)
    hw_id        = Column(Integer, ForeignKey("homework.id"))
    filename     = Column(String(255))
    filepath     = Column(String(500), nullable=True)
    file_data    = Column(LargeBinary, nullable=True)
    content_type = Column(String(120), nullable=True, default="application/octet-stream")
    homework     = relationship("Homework", back_populates="files")


class HomeworkStatus(Base):
    """Личная отметка о выполнении ДЗ. owner_key — 'tg:<telegram_id>' для бота
    или 'web:<client_id>' для анонимного посетителя сайта (id из localStorage
    браузера — аккаунтов на сайте нет). Одна запись = один человек = одно ДЗ."""
    __tablename__ = "homework_status"
    id         = Column(Integer, primary_key=True, index=True)
    hw_id      = Column(Integer, ForeignKey("homework.id"), nullable=False, index=True)
    owner_key  = Column(String(120), nullable=False, index=True)
    status     = Column(String(20), nullable=False, default="pending")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    homework   = relationship("Homework", back_populates="personal_statuses")


class HomeworkReminderLog(Base):
    """Кому уже отправлено напоминание по конкретному ДЗ — чтобы не слать
    повторно каждые 30 минут (cron дёргает /api/cron/reminders часто)."""
    __tablename__ = "homework_reminder_log"
    id        = Column(Integer, primary_key=True, index=True)
    hw_id     = Column(Integer, ForeignKey("homework.id"), nullable=False, index=True)
    owner_key = Column(String(120), nullable=False, index=True)
    sent_at   = Column(DateTime, default=datetime.utcnow)
    homework  = relationship("Homework", back_populates="reminder_log")


class HomeworkMessage(Base):
    """Telegram-сообщение, отправленное конкретному чату при создании ДЗ.
    Хранится, чтобы при редактировании/удалении ДЗ обновить/удалить именно
    это сообщение, а не слать дубликат."""
    __tablename__ = "homework_messages"
    id         = Column(Integer, primary_key=True, index=True)
    hw_id      = Column(Integer, ForeignKey("homework.id"), nullable=False, index=True)
    chat_id    = Column(Integer, nullable=False)
    message_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    homework   = relationship("Homework", back_populates="messages")


class LessonOverride(Base):
    """Отмена пары (PDF не обновили — правка вручную с кодом)."""
    __tablename__ = "lesson_overrides"
    id          = Column(Integer, primary_key=True, index=True)
    group_name  = Column(String(60), nullable=False, index=True)
    day_date    = Column(String(16), nullable=False)   # как в JSON: 10/04
    lesson_time = Column(String(80), nullable=False)
    subject     = Column(String(300), nullable=False)
    lesson_key  = Column(String(500), nullable=False, unique=True, index=True)
    cancelled   = Column(Boolean, nullable=False, default=True)
    note        = Column(Text, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def _ensure_hw_file_columns() -> None:
    """Добавляет file_data / content_type в существующую БД (без потери данных)."""
    from sqlalchemy import inspect, text

    engine = _get_engine()
    insp = inspect(engine)
    if not insp.has_table("homework_files"):
        return
    cols = {c["name"] for c in insp.get_columns("homework_files")}
    blob = "BLOB" if "sqlite" in _get_database_url().lower() else "BYTEA"
    with engine.begin() as conn:
        if "file_data" not in cols:
            conn.execute(text(f"ALTER TABLE homework_files ADD COLUMN file_data {blob}"))
        if "content_type" not in cols:
            conn.execute(text(
                "ALTER TABLE homework_files ADD COLUMN content_type VARCHAR(120)"
            ))


def _ensure_user_columns() -> None:
    """Добавляет notify_hours в существующую таблицу users (без потери данных)."""
    from sqlalchemy import inspect, text

    engine = _get_engine()
    insp = inspect(engine)
    if not insp.has_table("users"):
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    with engine.begin() as conn:
        if "notify_hours" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN notify_hours INTEGER"))


def init_db():
    engine = _get_engine()
    Base.metadata.create_all(bind=engine)
    _ensure_hw_file_columns()
    _ensure_user_columns()


def SessionLocal():
    """Совместимость с bot.py и прочим кодом вне FastAPI Depends."""
    global _SessionLocal
    if _SessionLocal is None:
        _get_engine()
    return _SessionLocal()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
