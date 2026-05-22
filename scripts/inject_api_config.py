#!/usr/bin/env python3
"""Пишет static/config.js из переменной API_PUBLIC_URL (сборка Vercel и т.п.)."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "config.js"
url = (os.environ.get("API_PUBLIC_URL") or os.environ.get("VET_API_PUBLIC_URL") or "").strip().rstrip("/")

if url:
    body = f"window.__VET_API_BASE__={json.dumps(url)};\n"
else:
    body = (
        "// API на том же домене (Vercel или локально: python run.py)\n"
        "window.__VET_API_BASE__=\"\";\n"
    )

OUT.write_text(body, encoding="utf-8")
print(f"Wrote {OUT} -> {url or '(same origin)'}")
