# cloud/app.py
import os, json, glob, subprocess
from datetime import datetime
from typing import Dict, Optional

from fastapi import FastAPI, Body, HTTPException
from dotenv import load_dotenv

ENV_PATH = "/secrets/.env"
if os.path.exists(ENV_PATH):
    load_dotenv(ENV_PATH)

app = FastAPI()

def now_fr():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Paris")).isoformat(timespec="seconds")
    except Exception:
        return datetime.utcnow().isoformat(timespec="seconds")+"Z"

def run_cmd(args: list[str]) -> int:
    print(">>", " ".join(args), flush=True)
    return subprocess.call(args, cwd="/app")

def find_latest_json() -> Optional[str]:
    """
    Cherche un fichier JSON de pronostics produit par le pipeline.
    Adapte les motifs selon ton projet si besoin.
    """
    candidates = []
    # exemples de fichiers présents dans ton dépôt
    patterns = [
        "/app/*.json",
        "/app/out/*.json",
        "/app/results/*.json",
        "/app/p_finale*.json",
    ]
    for p in patterns:
        candidates.extend(glob.glob(p))
    if not candidates:
        return None
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return candidates[0]

@app.get("/health")
def health():
    return {"ok": True, "budget": os.getenv("GPI_BUDGET", "5")}

@app.post("/run/hminus")
def run_hminus(payload: Dict = Body(...)):
    """Lance l'analyse + export JSON, puis renvoie un résumé + chemin du fichier."""
    R = payload.get("R") or payload.get("reunion")
    C = payload.get("C") or payload.get("course")
    when = payload.get("when", "H-5")
    course_url = payload.get("course_url")
    reunion_url = payload.get("reunion_url")
    budget = os.getenv("GPI_BUDGET", "5")

    if not (R and C) and not (course_url or reunion_url):
        raise HTTPException(status_code=400, detail="R/C ou course_url/reunion_url requis")

    # 1) Analyse
    cmd = ["python", "analyse_courses_du_jour_enrichie.py", "--phase", when, "--budget", budget]
    if R and C: cmd += ["--reunion", R, "--course", C]
    if course_url: cmd += ["--course-url", course_url]
    if reunion_url: cmd += ["--reunion-url", reunion_url]
    rc1 = run_cmd(cmd)

    # 2) Validation
    rc2 = run_cmd(["python", "validator_ev.py",
                   "--reunion", R or "", "--course", C or "", "--rules", "gpi_v51.yml"])

    # 3) Export JSON (si ton projet l’utilise ; sinon commente cette ligne)
    # Beaucoup de setups exportent un JSON final ici :
    if os.path.exists("/app/p_finale_export.py"):
        _ = run_cmd(["python", "p_finale_export.py"])

    latest = find_latest_json()
    summary = {
        "ok": (rc1 == 0 and rc2 == 0),
        "timestamp": now_fr(),
        "reunion": R, "course": C, "phase": when,
        "course_url": course_url, "reunion_url": reunion_url,
        "rc_analysis": rc1, "rc_validator": rc2,
        "json_path": latest
    }
    # On garde un mémo du dernier run
    try:
        with open("/tmp/last_run.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False)
    except Exception:
        pass
    return summary

@app.get("/last")
def last():
    """
    Renvoie le DERNIER pronostic complet (JSON) trouvé sur le disque.
    Idéal pour affichage direct sur Android.
    """
    latest = find_latest_json()
    if not latest:
        raise HTTPException(status_code=404, detail="Aucun fichier JSON de pronostic trouvé.")
    try:
        with open(latest, "r", encoding="utf-8") as f:
            data = json.load(f)
        # tu peux ici filtrer/renommer des champs si besoin
        return {"file": latest, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Impossible de lire {latest}: {e}")
