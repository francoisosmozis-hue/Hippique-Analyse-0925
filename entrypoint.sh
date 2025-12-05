#!/bin/sh
set -e

# Default to port 8080 if not specified
PORT=${PORT:-8080}

# Start the application using the exec form
# This ensures that the uvicorn process becomes PID 1 and receives signals correctly
exec uvicorn hippique_orchestrator.service:app --host 0.0.0.0 --port "$PORT" --log-level info
