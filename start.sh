#!/usr/bin/env bash
set -euo pipefail
PORT="${PORT:-8080}"
export BIND="0.0.0.0:${PORT}"
echo "[start] launching gunicorn on ${BIND}..."
exec gunicorn -c gunicorn.conf.py src.service:app
