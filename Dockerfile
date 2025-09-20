FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Par facilité on fixe un PORT par défaut, Cloud Run écrasera la variable à 8080
ENV PORT=8080
# Démarre l'app en lisant PORT (évite les soucis d'expansion bash)
CMD ["python", "main.py"]
