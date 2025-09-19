# cloud/app.py
import os
import subprocess
from datetime import datetime
from typing import Dict, Optional

from fastapi import FastAPI, Body, HTTPException, Header
from dotenv import load_dotenv

# Charge le .env monté depuis Secret Manager
ENV_PATH = "/secrets/.env"
if os.path.exists(ENV_PATH):
    load_dotenv(ENV_PATH)

# --- timezone util ---
def now_paris_iso() -> str:
    try:
        # Python 3.9+ : zoneinfo
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Paris")).isoformat(timespec="seconds")
    except Exception:
        # Fallback UTC si tz absente
        return datetime.utcnow().isoformat(timespec="seconds") + "Z"

app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True, "budget": os.getenv("GPI_BUDGET", "5")}

def run_cmd(args: list[str]) -> tuple[int, str, str]:
    """Exécute un script et renvoie (code, stdout, stderr)."""
    print(">>", " ".join(args), flush=True)
    p = subprocess.run(args, cwd="/app", capture_output=True, text=True)
    # log court en sortie serveur
    if p.stdout:
        print(p.stdout[-1200:], flush=True)
    if p.stderr:
        print("STDERR:", p.stderr[-1200:], flush=True)
    return p.returncode, (p.stdout or ""), (p.stderr or "")

def tail(text: str, n_chars: int = 800) -> str:
    return text[-n_chars:] if text else ""

@app.post("/run/hminus")
def run_hminus(
    payload: Dict = Body(...),
    x_api_key: Optional[str] = Header(None)  # active si tu as mis API_KEY dans .env
):
    # Sécurité simple optionnelle
    api_key = os.getenv("API_KEY")
    if api_key and x_api_key != api_key:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Paramètres reçus
    R = payload.get("R") or payload.get("reunion")
    C = payload.get("C") or payload.get("course")
    when = payload.get("when", "H-5")
    course_url = payload.get("course_url")
    reunion_url = payload.get("reunion_url")
    budget = os.getenv("GPI_BUDGET", "5")

    if not (R and C) and not (course_url or reunion_url):
        raise HTTPException(status_code=400, detail="R/C ou course_url/reunion_url requis")

    # 1) Analyse enrichie
    cmd = ["python", "analyse_courses_du_jour_enrichie.py", "--phase", when, "--budget", budget]
    if R and C:
        cmd += ["--reunion", R, "--course", C]
    if course_url:
        cmd += ["--course-url", course_url]
    if reunion_url:
        cmd += ["--reunion-url", reunion_url]

    rc1, out1, err1 = run_cmd(cmd)

    # 2) Validation EV/ROI
    rc2, out2, err2 = run_cmd([
        "python", "validator_ev.py",
        "--reunion", R or "", "--course", C or "", "--rules", "gpi_v51.yml"
    ])

    ok = (rc1 == 0 and rc2 == 0)

    # Sauvegarde d’un mini récap dans /tmp (utile si tu veux une route /last)
    summary = {
        "ok": ok,
        "timestamp": now_paris_iso(),
        "reunion": R, "course": C, "phase": when,
        "course_url": course_url, "reunion_url": reunion_url,
        "rc_analysis": rc1, "rc_validator": rc2,
        "log_excerpt": tail(out1 or err1 or "")  # extrait court pour voir la course traitée
    }
    try:
        import json
        with open("/tmp/last_run.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False)
    except Exception:
        pass

    return summary

@app.get("/last")
def last():
    """Retourne le dernier récap /run/hminus enregistré."""
    try:
        import json
        with open("/tmp/last_run.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        raise HTTPException(status_code=404, detail="Aucun run enregistré pour le moment.")
etenv("PORT", "8080")))
