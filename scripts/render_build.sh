#!/usr/bin/env bash
set -euo pipefail
pip install -r requirements.txt
mkdir -p uploads schedule_json
bash scripts/sync_static.sh
