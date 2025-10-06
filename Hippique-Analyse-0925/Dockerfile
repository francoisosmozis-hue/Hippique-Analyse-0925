FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Paquets système utiles pour SSL, lxml, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl build-essential \
      libxml2 libxslt1.1 libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*
    
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Assure l'exécution du script de démarrage sur Cloud Run
RUN chmod +x start.sh

# Cloud Run / local lisent PORT
ENV PORT=8080
CMD ["./start.sh"]
