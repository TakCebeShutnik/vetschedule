import os
from pathlib import Path

# Загружаем .env файл до чтения переменных
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=False)
except ImportError:
    pass  # python-dotenv не установлен — читаем из системного окружения

def _default_database_url() -> str:
    if os.getenv("VERCEL") == "1":
        return "sqlite:////tmp/schedule.db"
    return "sqlite:///./schedule.db"


def _default_uploads_dir() -> Path:
    if os.getenv("VERCEL") == "1":
        return Path(os.getenv("UPLOADS_DIR", "/tmp/uploads"))
    return Path(os.getenv("UPLOADS_DIR", "uploads"))


class Config:
    TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
    SCHEDULE_DIR: Path = Path(os.getenv("SCHEDULE_DIR", "schedule_json"))
    UPLOADS_DIR: Path = _default_uploads_dir()
    DATABASE_URL: str = os.getenv("DATABASE_URL", _default_database_url())
    IS_VERCEL: bool = os.getenv("VERCEL") == "1"
    # polling — локально; webhook — Vercel / продакшен
    TELEGRAM_MODE: str = os.getenv(
        "TELEGRAM_MODE",
        "webhook" if os.getenv("VERCEL") == "1" else "polling",
    ).strip().lower()
    CRON_SECRET: str = os.getenv("CRON_SECRET", "").strip()
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", 8000))
    # URL веб-сайта (нужен боту для генерации ссылок на файлы ДЗ)
    SITE_URL: str = os.getenv("SITE_URL", "http://localhost:8000")
    # Прямая ссылка на PDF расписания для автозапуска парсера из run.py (пусто = не качать)
    SCHEDULE_PDF_URL: str = os.getenv("SCHEDULE_PDF_URL", "").strip()
    # База API для бота (если пусто — http://127.0.0.1:PORT/api локально; на Vercel — SITE_URL/api)
    API_INTERNAL_URL: str = os.getenv("API_INTERNAL_URL", "").strip().rstrip("/")
    # CORS для фронта на другом домене (Vercel): через запятую, например https://app.vercel.app
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "*").strip()
    # Сколько минут до дедлайна отправлять напоминание
    NOTIFY_BEFORE_HOURS: int = int(os.getenv("NOTIFY_BEFORE_HOURS", 24))
    # Код для правки ДЗ и отмены пар (сайт + бот + API)
    EDITOR_CODE: str = os.getenv("EDITOR_CODE", os.getenv("HW_EDITOR_CODE", "0801"))

    def __post_init__(self):
        self.SCHEDULE_DIR.mkdir(exist_ok=True)
        self.UPLOADS_DIR.mkdir(exist_ok=True)

config = Config()
config.SCHEDULE_DIR.mkdir(exist_ok=True)
config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
if config.IS_VERCEL and not config.API_INTERNAL_URL and config.SITE_URL:
    config.API_INTERNAL_URL = config.SITE_URL.rstrip("/") + "/api"
