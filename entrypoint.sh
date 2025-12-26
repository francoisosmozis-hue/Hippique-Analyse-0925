#!/bin/sh
set -e

# Default to port 8080 if not specified
PORT=${PORT:-8080}

# Start the application using Gunicorn with Uvicorn workers
# This is a more robust setup for production environments.
# Gunicorn manages the worker processes, handling signals and restarts.
# The number of workers is a starting point and can be tuned.
exec gunicorn -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:"$PORT" main_debug:app
