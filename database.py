from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, Text, Boolean, ForeignKey, LargeBinary,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.pool import NullPool
from datetime import datetime
from config import config

_is_sqlite = "sqlite" in config.DATABASE_URL.lower()
_engine_kw: dict = {"echo": False}
if _is_sqlite:
    _engine_kw["connect_args"] = {"check_same_thread": False}
else:
    # Serverless (Vercel): без пула соединений, живые коннекты к Neon/Postgres
    _engine_kw["poolclass"] = NullPool
    _engine_kw["pool_pre_ping"] = True

engine = create_engine(config.DATABASE_URL, **_engine_kw)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ─── Модели ─────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    id          = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, nullable=True, index=True)
    name        = Column(String(120), nullable=False)
    group_name  = Column(String(60), nullable=True)
    is_admin    = Column(Boolean, default=False)
    created_at  = Column(DateTime, default=datetime.utcnow)
    homework    = relationship("Homework", back_populates="creator", foreign_keys="Homework.created_by")


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


class HomeworkFile(Base):
    __tablename__ = "homework_files"
    id           = Column(Integer, primary_key=True, index=True)
    hw_id        = Column(Integer, ForeignKey("homework.id"))
    filename     = Column(String(255))
    filepath     = Column(String(500), nullable=True)
    file_data    = Column(LargeBinary, nullable=True)
    content_type = Column(String(120), nullable=True, default="application/octet-stream")
    homework     = relationship("Homework", back_populates="files")


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

    insp = inspect(engine)
    if not insp.has_table("homework_files"):
        return
    cols = {c["name"] for c in insp.get_columns("homework_files")}
    blob = "BLOB" if _is_sqlite else "BYTEA"
    with engine.begin() as conn:
        if "file_data" not in cols:
            conn.execute(text(f"ALTER TABLE homework_files ADD COLUMN file_data {blob}"))
        if "content_type" not in cols:
            conn.execute(text(
                "ALTER TABLE homework_files ADD COLUMN content_type VARCHAR(120)"
            ))


def init_db():
    Base.metadata.create_all(bind=engine)
    _ensure_hw_file_columns()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
