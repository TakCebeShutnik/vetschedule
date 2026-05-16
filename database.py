from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
from config import config

engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in config.DATABASE_URL else {},
    echo=False,
)
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
    id       = Column(Integer, primary_key=True, index=True)
    hw_id    = Column(Integer, ForeignKey("homework.id"))
    filename = Column(String(255))
    filepath = Column(String(500))
    homework = relationship("Homework", back_populates="files")


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
