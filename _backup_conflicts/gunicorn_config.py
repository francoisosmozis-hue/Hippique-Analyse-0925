"""
Configuration Gunicorn pour Cloud Run
"""
import os

# Bind sur le port fourni par Cloud Run (défaut 8080)
port = os.getenv("PORT", "8080")
bind = f"0.0.0.0:{port}"

# Workers : 2 par défaut (ajuster selon ressources Cloud Run)
# Formule recommandée: (2 x CPU) + 1
workers = int(os.getenv("WORKERS", "2"))

# Worker class : uvicorn pour FastAPI
worker_class = "uvicorn.workers.UvicornWorker"

# Timeouts (300s pour analyses longues)
timeout = 300
graceful_timeout = 30
keepalive = 5

# Logging
errorlog = "-"  # stderr
accesslog = "-"  # stdout
loglevel = os.getenv("LOG_LEVEL", "info")

# Préload app pour économiser mémoire
preload_app = False  # False car Cloud Tasks peut lancer plusieurs requêtes parallèles

# Worker tmp directory
worker_tmp_dir = "/dev/shm"

# Max requests avant restart (évite memory leaks)
max_requests = 1000
max_requests_jitter = 50

# Process naming
proc_name = "horse-racing-orchestrator"

def on_starting(server):
    """Hook appelé au démarrage"""
    server.log.info("🐴 Horse Racing Orchestrator starting...")

def on_reload(server):
    """Hook appelé lors du reload"""
    server.log.info("🔄 Reloading workers...")

def worker_int(worker):
    """Hook appelé lors de l'interruption d'un worker"""
    worker.log.info(f"Worker {worker.pid} interrupted")

def post_fork(server, worker):
    """Hook appelé après fork d'un worker"""
    server.log.info(f"Worker {worker.pid} spawned")

def pre_exec(server):
    """Hook appelé avant exec"""
    server.log.info("Forked child, re-executing")

def when_ready(server):
    """Hook appelé quand le serveur est prêt"""
    server.log.info(f"Server ready. Listening on {bind}")
