#!/usr/bin/env python3
"""
Локальный запуск: опционально парсер → API + сайт + бот в одном процессе.
На Render используйте scripts/render_start.sh (парсер — только GitHub Actions).
"""

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


def sync_static() -> None:
    src, dst = ROOT / "index.html", ROOT / "static" / "index.html"
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def run_schedule_parser() -> None:
    from config import config

    url = (config.SCHEDULE_PDF_URL or "").strip()
    if not url:
        logger.info(
            "Парсер пропущен (нет SCHEDULE_PDF_URL). JSON: %s",
            config.SCHEDULE_DIR,
        )
        return

    logger.info("📥 Парсер: загрузка PDF …")
    try:
        from schedule_parser import DOCX_FILENAME, PDF_FILENAME, run_once

        if run_once(url, PDF_FILENAME, DOCX_FILENAME, str(config.SCHEDULE_DIR)):
            logger.info("✅ JSON расписания обновлены.")
        else:
            logger.warning("⚠️ Парсер завершился с ошибкой.")
    except Exception:
        logger.exception("❌ Ошибка парсера.")


def run_bot():
    from config import config

    time.sleep(3)
    logger.info("🚀 Telegram-бот…")
    try:
        subprocess.run([sys.executable, str(ROOT / "bot.py")], check=True)
    except subprocess.CalledProcessError as e:
        logger.error("❌ Бот завершился (код %s)", e.returncode)


def main():
    from config import config

    logger.info("=== VetSchedule (локально) ===")
    sync_static()
    run_schedule_parser()

    threading.Thread(target=run_bot, daemon=True).start()

    reload = os.getenv("UVICORN_RELOAD", "1").lower() in ("1", "true", "yes")
    logger.info("🌐 API + сайт на порту %s (reload=%s)", config.PORT, reload)

    import uvicorn

    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
