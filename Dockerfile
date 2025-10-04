FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    TZ=Europe/Paris

WORKDIR /app
COPY . /app

# Installe les dépendances (requirements.txt doit exister)
RUN pip install --no-cache-dir -r requirements.txt

# Lance l'API FastAPI
CMD ["sh","-lc","uvicorn cloud.app:app --host 0.0.0.0 --port ${PORT}"]
