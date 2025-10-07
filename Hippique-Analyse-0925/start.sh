#!/usr/bin/env bash
set -euo pipefail
PORT="${PORT:-8080}"
echo "[start] launching uvicorn on 0.0.0.0:${PORT}..."
exec uvicorn main:app --host 0.0.0.0 --port "${PORT}"
