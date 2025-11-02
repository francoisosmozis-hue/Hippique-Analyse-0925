"""
gunicorn.conf.py - Gunicorn Configuration for Cloud Run
"""

import multiprocessing
import os

# Server socket
bind = f"0.0.0.0:{os.getenv('PORT', '8080')}"
backlog = 2048

# Worker processes
workers = int(os.getenv("GUNICORN_WORKERS", "2"))
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50

# Timeouts
timeout = int(os.getenv("GUNICORN_TIMEOUT", "600"))
graceful_timeout = 30
keepalive = 5

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "hippique-orchestrator"

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# SSL (not used in Cloud Run)
keyfile = None
certfile = None

# Logging hooks
def on_starting(server):
    """Called just before the master process is initialized."""
    server.log.info("Starting Hippique Orchestrator")

def on_reload(server):
    """Called to recycle workers during a reload via SIGHUP."""
    server.log.info("Reloading workers")

def when_ready(server):
    """Called just after the server is started."""
    server.log.info(f"Server ready. Listening on {bind}")

def on_exit(server):
    """Called just before exiting Gunicorn."""
    server.log.info("Shutting down Hippique Orchestrator")

def worker_int(worker):
    """Called when a worker receives the SIGINT or SIGQUIT signal."""
    worker.log.info(f"Worker {worker.pid} interrupted")

def worker_abort(worker):
    """Called when a worker receives the SIGABRT signal."""
    worker.log.warning(f"Worker {worker.pid} aborted")