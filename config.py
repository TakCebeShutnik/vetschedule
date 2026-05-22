import logging
import os
from pathlib import Path

# Загружаем .env файл до чтения переменных
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=False)
except ImportError:
    pass  # python-dotenv не установлен — читаем из системного окружения

_log = logging.getLogger(__name__)

_EXPLICIT_DB_KEYS = (
    "DATABASE_URL",
    "POSTGRES_URL",
    "POSTGRES_URL_NON_POOLING",
    "POSTGRES_PRISMA_URL",
    "STORAGE_POSTGRES_URL_DATABASE_URL",
    "STORAGE_POSTGRES_URL_POSTGRES_URL",
    "STORAGE_POSTGRES_URL_DATABASE_URL_UNPOOLED",
    "STORAGE_POSTGRES_URL_POSTGRES_URL_NON_POOLING",
    "STORAGE_POSTGRES_URL",
    "STORAGE_DATABASE_URL",
)


def _normalize_db_url(url: str) -> str:
    """postgres:// → postgresql+psycopg2:// для SQLAlchemy."""
    u = url.strip()
    if u.startswith("postgres://"):
        u = "postgresql+psycopg2://" + u[len("postgres://"):]
    elif u.startswith("postgresql://") and "+psycopg2" not in u and "+pg8000" not in u:
        u = "postgresql+psycopg2://" + u[len("postgresql://"):]
    return u


def _looks_like_postgres_url(value: str) -> bool:
    v = (value or "").strip()
    return (
        ("postgresql://" in v or v.startswith("postgres://"))
        and "@" in v
        and len(v) > 20
    )


def _scan_env_postgres() -> list[tuple[str, str]]:
    """Любая переменная Vercel/Neon со строкой подключения Postgres."""
    found: list[tuple[str, str]] = []
    for key, val in os.environ.items():
        if _looks_like_postgres_url(val):
            found.append((key, val.strip()))
    return found


def _pick_best_postgres(candidates: list[tuple[str, str]]) -> str | None:
    if not candidates:
        return None

    def score(name: str) -> int:
        n = name.upper()
        s = 0
        if "DATABASE_URL" in n and "UNPOOLED" not in n and "PRISMA" not in n:
            s += 100
        if n.endswith("_POSTGRES_URL") or n == "POSTGRES_URL":
            s += 80
        if "POSTGRES_URL" in n and "NON_POOLING" not in n:
            s += 60
        if "UNPOOLED" in n or "NON_POOLING" in n:
            s -= 30
        if "PRISMA" in n:
            s -= 20
        return s

    key, val = max(candidates, key=lambda x: score(x[0]))
    _log.info("Postgres URL from env var: %s", key)
    return _normalize_db_url(val)


def _usable_db_url(raw: str) -> bool:
    v = raw.strip()
    if not v:
        return False
    # На Vercel SQLite из .env / старых настроек не должен блокировать Neon
    if v.startswith("sqlite:") and os.getenv("VERCEL") == "1":
        return False
    return True


def resolve_database_url() -> str:
    """Постоянная БД на Vercel: Postgres (Neon). Локально — SQLite."""
    for key in _EXPLICIT_DB_KEYS:
        raw = os.getenv(key, "").strip()
        if _usable_db_url(raw):
            _log.info("Database URL from %s", key)
            return _normalize_db_url(raw)

    picked = _pick_best_postgres(_scan_env_postgres())
    if picked:
        return picked

    if os.getenv("VERCEL") == "1":
        keys = sorted(k for k, v in os.environ.items() if _looks_like_postgres_url(v))
        raise RuntimeError(
            "На Vercel не найдена строка подключения к Postgres. "
            "Подключите Neon к проекту vetschedule и сделайте Redeploy. "
            f"Ожидается STORAGE_POSTGRES_URL_DATABASE_URL. "
            f"Найдено postgres-like keys: {keys[:8]}"
        )
    return "sqlite:///./schedule.db"


class Config:
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
    SCHEDULE_DIR: Path = Path(os.getenv("SCHEDULE_DIR", "schedule_json"))
    UPLOADS_DIR: Path = Path(os.getenv("UPLOADS_DIR", "uploads"))
    IS_VERCEL: bool = os.getenv("VERCEL") == "1"
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

    _db_url: str | None = None

    @property
    def DATABASE_URL(self) -> str:
        if self._db_url is None:
            self._db_url = resolve_database_url()
        return self._db_url

    @property
    def STORE_FILES_IN_DB(self) -> bool:
        return "sqlite" not in self.DATABASE_URL.lower()


config = Config()
config.SCHEDULE_DIR.mkdir(exist_ok=True)
if not config.STORE_FILES_IN_DB:
    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
if config.IS_VERCEL and not config.API_INTERNAL_URL and config.SITE_URL:
    config.API_INTERNAL_URL = config.SITE_URL.rstrip("/") + "/api"
