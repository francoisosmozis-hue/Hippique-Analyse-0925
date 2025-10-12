import os

bind = os.getenv("BIND", "0.0.0.0:8080")
worker_class = "uvicorn.workers.UvicornWorker"
workers = int(os.getenv("WEB_CONCURRENCY", "1")) or 1
threads = int(os.getenv("WEB_THREADS", "1")) or 1
timeout = int(os.getenv("WEB_TIMEOUT", "600"))
loglevel = os.getenv("LOG_LEVEL", "info")
accesslog = "-"
errorlog = "-"
