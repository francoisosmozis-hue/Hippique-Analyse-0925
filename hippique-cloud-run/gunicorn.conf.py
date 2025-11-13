
workers = 2
worker_class = "uvicorn.workers.UvicornWorker"
bind = "0.0.0.0:8080"
timeout = 600
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = "info"
