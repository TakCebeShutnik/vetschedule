"""
Точка входа для веб-приложения на PythonAnywhere (ASGI).
В панели PA: Web → WSGI configuration file → путь к этому файлу, переменная application.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import app as application  # noqa: E402
