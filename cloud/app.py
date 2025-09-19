import os
import subprocess
from fastapi import FastAPI, Body
from dotenv import load_dotenv

# Charger les variables d'environnement depuis Secret Manager
ENV_PATH = "/secrets/.env"
if os.path.exists(ENV_PATH):
    load_dotenv(ENV_PATH)

app = FastAPI()

@app.get("/health")
def health():
    """Endpoint de santé basique pour vérifier que l'API tourne."""
    return {"ok": True, "budget": os.getenv("GPI_BUDGET", "5")}

@app.post("/run/hminus")
def run_hminus(payload: dict = Body(...)):
    """
    Déclenche une analyse avec les scripts Python du projet.
    Reçoit un JSON de la forme :
    {
      "R": "R1",
      "C": "C3",
      "when": "H-5",
      "course_url": "...",
      "reunion_url": "..."
    }
    """
    R = payload.get("R") or payload.get("reunion")
    C = payload.get("C") or payload.get("course")
    when = payload.ge
