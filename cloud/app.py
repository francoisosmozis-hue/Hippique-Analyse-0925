# cloud/app.py
import os
import subprocess
from fastapi import FastAPI, Body
from dotenv import load_dotenv

# Charge le .env monté depuis Secret Manager (via --set-secrets)
ENV_PATH = "/secrets/.env"
if os.path.exists(ENV_PATH):
    load_dotenv(ENV_PATH)

app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True, "budget": os.getenv("GPI_BUDGET", "5")}

@app.post("/run/hminus")
def run_hminus(payload: dict = Body(...)):
    """
    Déclenche une analyse pour une course donnée.
    Ex :
    curl -X POST "https://.../run/hminus" \
      -H "Content-Type: application/json" \
      -d '{"R":"R1","C":"C3","when":"H-5"}'
    """
    R = payload.get("R") or payload.get("reunion")
    C = payload.get("C") or payload.get("course")
    when = payload.get("when", "H-5")

    # Exemple d’URL ZEturf : à remplacer selon la course réelle
    course_url = f"https://www.zeturf.fr/fr/course/2025-09-06/{R}{C}-vincennes"

    # 1) Lancer l’analyse enrichie
    rc1 = subprocess.call([
        "python", "analyse_courses_du_jour_enrichie.py",
        "--course-url", course_url,
        "--phase", "H5" if when.upper() == "H-5" else "H30",
        "--budget", os.getenv("GPI_BUDGET", "5")
    ])

    # 2) Validation EV/ROI
    rc2 = subprocess.call([
        "python", "validator_ev.py",
        "--reunion", R,
        "--course", C,
        "--rules", "gpi_v51.yml"
    ])

    return {
        "ok": (rc1 == 0 and rc2 == 0),
        "R": R,
        "C": C,
        "phase": when,
        "rc_analysis": rc1,
        "rc_validator": rc2
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
