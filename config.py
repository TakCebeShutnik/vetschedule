import os
from pathlib import Path

# Загружаем .env файл до чтения переменных
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=False)
except ImportError:
    pass  # python-dotenv не установлен — читаем из системного окружения


def _normalize_db_url(url: str) -> str:
    """postgres:// → postgresql+psycopg2:// для SQLAlchemy."""
    u = url.strip()
    if u.startswith("postgres://"):
        u = "postgresql+psycopg2://" + u[len("postgres://"):]
    elif u.startswith("postgresql://") and "+psycopg2" not in u and "+pg8000" not in u:
        u = "postgresql+psycopg2://" + u[len("postgresql://"):]
    return u


def _resolve_database_url() -> str:
    """Постоянная БД: Postgres (Neon / Vercel Postgres). На Vercel SQLite в /tmp не используем."""
    for key in (
        "DATABASE_URL",
        "POSTGRES_URL",
        "POSTGRES_URL_NON_POOLING",
        "POSTGRES_PRISMA_URL",
        # Vercel Storage → Neon с префиксом (например STORAGE_POSTGRES_URL)
        "STORAGE_POSTGRES_URL",
        "STORAGE_DATABASE_URL",
    ):
        raw = os.getenv(key, "").strip()
        if raw:
            return _normalize_db_url(raw)
    if os.getenv("VERCEL") == "1":
        raise RuntimeError(
            "На Vercel нужна постоянная БД: подключите Neon или Vercel Postgres "
            "и задайте DATABASE_URL (или POSTGRES_URL) в Environment Variables."
        )
    return "sqlite:///./schedule.db"


_DB_URL = _resolve_database_url()


class Config:
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
    SCHEDULE_DIR: Path = Path(os.getenv("SCHEDULE_DIR", "schedule_json"))
    UPLOADS_DIR: Path = Path(os.getenv("UPLOADS_DIR", "uploads"))
    DATABASE_URL: str = _DB_URL
    IS_VERCEL: bool = os.getenv("VERCEL") == "1"
    # Вложения ДЗ в Postgres (на Vercel диск /tmp не сохраняется)
    STORE_FILES_IN_DB: bool = "sqlite" not in _DB_URL.lower()
    TELEGRAM_MODE: str = os.getenv(
        "TELEGRAM_MODE",
        "webhook" if os.getenv("VERCEL") == "1" else "polling",
    ).strip().lower()
    CRON_SECRET: str = os.getenv("CRON_SECRET", "").strip()
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", 8000))
    SITE_URL: str = os.getenv("SITE_URL", "http://localhost:8000")
    SCHEDULE_PDF_URL: str = os.getenv("SCHEDULE_PDF_URL", "").strip()
    API_INTERNAL_URL: str = os.getenv("API_INTERNAL_URL", "").strip().rstrip("/")
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "*").strip()
    NOTIFY_BEFORE_HOURS: int = int(os.getenv("NOTIFY_BEFORE_HOURS", 24))
    EDITOR_CODE: str = os.getenv("EDITOR_CODE", os.getenv("HW_EDITOR_CODE", "0801"))


config = Config()
config.SCHEDULE_DIR.mkdir(exist_ok=True)
if not config.STORE_FILES_IN_DB:
    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
if config.IS_VERCEL and not config.API_INTERNAL_URL and config.SITE_URL:
    config.API_INTERNAL_URL = config.SITE_URL.rstrip("/") + "/api"
