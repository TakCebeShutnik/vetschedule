#!/usr/bin/env python3
"""
Запускает парсер расписания (опционально), затем FastAPI и Telegram-бота.
Порядок: JSON из PDF → сервер → бот.
"""

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

# Рабочая директория — каталог проекта (относительные пути schedule.pdf / schedule_json)
ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)


def run_schedule_parser() -> None:
    """
    Скачивание PDF, конвертация, парсинг → JSON в SCHEDULE_DIR.
    Выполняется до старта API. Если SCHEDULE_PDF_URL не задан — пропуск (остаются старые файлы).
    """
    from config import config

    url = (config.SCHEDULE_PDF_URL or "").strip()
    if not url:
        logger.info(
            "Парсер пропущен: не задан SCHEDULE_PDF_URL в .env — используются текущие JSON в %s",
            config.SCHEDULE_DIR,
        )
        return

    logger.info("📥 Парсер расписания: загрузка PDF и обновление JSON …")
    try:
        from schedule_parser import DOCX_FILENAME, PDF_FILENAME, run_once

        ok = run_once(url, PDF_FILENAME, DOCX_FILENAME, str(config.SCHEDULE_DIR))
        if ok:
            logger.info("✅ Парсер расписания успешно обновил данные.")
        else:
            logger.warning(
                "⚠️ Парсер завершился с ошибкой (см. логи schedule_parser выше). "
                "Сервер стартует с уже имеющимися JSON, если они есть."
            )
    except Exception:
        logger.exception(
            "❌ Ошибка при запуске парсера; сервер всё равно будет запущен со старыми данными."
        )


def run_bot():
    """Запуск Telegram-бота"""
    logger.info("⏳ Ожидаем запуска сервера перед стартом бота...")
    time.sleep(4)  # Даём uvicorn полностью подняться (особенно с --reload)

    logger.info("🚀 Запуск Telegram-бота...")
    try:
        subprocess.run(
            [sys.executable, str(ROOT / "bot.py")],
            check=True,
            capture_output=False,
        )
    except subprocess.CalledProcessError as e:
        logger.error("❌ Бот завершился с ошибкой (код %s)", e.returncode)
    except FileNotFoundError:
        logger.error("❌ Файл bot.py не найден!")
    except Exception as e:
        logger.error("❌ Неожиданная ошибка при запуске бота: %s", e)


def main():
    """Главная функция"""
    logger.info("=== Запуск vetschedule ===")

    run_schedule_parser()

    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    logger.info("🌐 Запуск FastAPI сервера...")

    try:
        import uvicorn
        from config import config

        reload = os.getenv("RELOAD", "1").strip().lower() in ("1", "true", "yes")
        uvicorn.run(
            "main:app",
            host=config.HOST,
            port=config.PORT,
            reload=reload,
            log_level="info",
        )
    except ImportError:
        logger.error("❌ Uvicorn не установлен. Установите: pip install uvicorn")
    except KeyboardInterrupt:
        logger.info("⏹️ Сервер остановлен пользователем")
    except Exception as e:
        logger.error("❌ Ошибка запуска сервера: %s", e)


if __name__ == "__main__":
    main()
