# Dockerfile - Hippique-Analyse-0925
# Refonte avec build multi-stage pour optimiser la taille et la sécurité

# --- 1. Builder Stage ---
# Installe les dépendances de compilation et les packages Python
FROM python:3.11-slim as builder

WORKDIR /app

# Crée un environnement virtuel
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Installe les dépendances système nécessaires à la compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    pkg-config \
    libdbus-1-dev \
    && rm -rf /var/lib/apt/lists/*

# Copie le fichier de dépendances et installe les packages dans le venv
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

# --- 2. Final Stage ---
# Construit l'image finale avec le code et les packages installés
FROM python:3.11-slim

WORKDIR /app

# Installe les dépendances système d'exécution
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Copie l'environnement virtuel depuis le stage "builder"
COPY --from=builder /opt/venv /opt/venv

# Copie le code de l'application
COPY . .

# Ajoute le venv au PATH et configure l'environnement
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# Assure l'exécution du script de démarrage
RUN chmod +x start.sh

# Expose le port et lance l'application via le script existant
EXPOSE 8080
CMD ["./start.sh"]