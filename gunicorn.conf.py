"""
gunicorn.conf.py - Configuration Gunicorn pour Cloud Run
"""

import multiprocessing
import os

# Bind
bind = f"0.0.0.0:{os.getenv('PORT', '8080')}"

# Workers
# Pour Cloud Run : 1-2 workers suffisent (CPU limité)
workers = int(os.getenv("GUNICORN_WORKERS", "2"))
worker_class = "uvicorn.workers.UvicornWorker"
threads = int(os.getenv("GUNICORN_THREADS", "1"))

# Timeouts
timeout = int(os.getenv("GUNICORN_TIMEOUT", "600"))  # 10 minutes pour analyses longues
keepalive = 5
graceful_timeout = 30

# Logging
accesslog = "-"  # stdout
errorlog = "-"   # stderr
loglevel = os.getenv("LOG_LEVEL", "info").lower()
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "hippique-orchestrator"

# Server mechanics
daemon = False
pidfile = None
worker_tmp_dir = "/dev/shm"  # Utiliser RAM pour améliorer perfs

# Preload app pour économiser mémoire
preload_app = False  # False car on veut des workers indépendants pour analyses lourdes

# Reload
reload = os.getenv("GUNICORN_RELOAD", "false").lower() == "true"