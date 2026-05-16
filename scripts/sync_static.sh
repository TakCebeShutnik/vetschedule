#!/usr/bin/env bash
# Копирует index.html → static/ (FastAPI отдаёт сайт из static/)
set -euo pipefail
mkdir -p static
cp -f index.html static/index.html
