#!/usr/bin/env bash
# Один контейнер Render: сайт + API + бот. Общая БД, бот → http://127.0.0.1:$PORT/api
set -euo pipefail

PORT="${PORT:-8000}"

uvicorn main:app --host 0.0.0.0 --port "$PORT" &
WEB_PID=$!

for _ in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${PORT}/api/groups" >/dev/null; then
    break
  fi
  sleep 1
done

if [ -n "${TELEGRAM_TOKEN:-}" ]; then
  echo "Starting Telegram bot (same instance as web)…"
  python bot.py &
else
  echo "TELEGRAM_TOKEN not set — bot skipped"
fi

wait "$WEB_PID"
