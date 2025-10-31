#!/bin/bash
export PORT=8080
export PROJECT_ID=analyse-hippique
export REGION=europe-west1
export SERVICE_NAME=hippique-orchestrator
export QUEUE_ID=hippique-tasks
export TZ=Europe/Paris
export PYTHONPATH=/home/francoisosmozis/hippique-orchestrator

# Lancer gunicorn localement
gunicorn --bind 0.0.0.0:8080 --worker-class uvicorn.workers.UvicornWorker --workers 1 src.service:app
