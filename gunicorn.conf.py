# Gunicorn configuration for Cloud Run
import multiprocessing
import os

# Bind
bind = os.getenv("BIND", "0.0.0.0:8080")

# Workers
workers = int(os.getenv("GUNICORN_WORKERS", "2"))
worker_class = "uvicorn.workers.UvicornWorker"

# Timeouts
timeout = int(os.getenv("GUNICORN_TIMEOUT", "300"))
graceful_timeout = 30
keepalive = 5

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "hippique-orchestrator"

# Reload on code changes (dev only)
reload = os.getenv("ENV", "production") == "development"
