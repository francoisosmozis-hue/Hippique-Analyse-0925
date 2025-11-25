#!/bin/bash
cd "$(dirname "$0")" || exit 1
export PYTHONPATH="$PWD:$PYTHONPATH"
export TZ=Europe/Paris
pkill -f "uvicorn" || true
uvicorn service:app --app-dir ./src --host 0.0.0.0 --port 8080
