FROM python:3.11-slim

WORKDIR /app

# Dépendances système
RUN apt-get update && apt-get install -y             gcc             g++             && rm -rf /var/lib/apt/lists/*

# Dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code source
COPY src/ ./src/
COPY gunicorn.conf.py .

# Scripts GPI (à copier depuis votre repo existant)
# COPY gpi_scripts/*.py ./

ENV PYTHONUNBUFFERED=1
ENV PORT=8080

EXPOSE 8080

CMD ["gunicorn", "src.service:app", "-c", "gunicorn.conf.py"]
