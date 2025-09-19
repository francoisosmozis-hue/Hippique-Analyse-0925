cd ~/Hippique-Analyse-0925
mkdir -p cloud
cat > cloud/app.py <<'PY'
import os
import subprocess
from fastapi import FastAPI, Body, HTTPException
from dotenv import load_dotenv

# Charge le .env monté depuis Secret Manager
ENV_PATH = "/secrets/.env"
if os.path.exists(ENV_PATH):
    load_dotenv(ENV_PATH)

app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True, "budget": os.getenv("GPI_BUDGET", "5")}

def run_cmd(args: list[str]) -> int:
    print(">>", " ".join(args), flush=True)
    # /app = racine de l'image
    return subprocess.call(args, cwd="/app")

@app.post("/run/hminus")
def run_hminus(payload: dict = Body(...)):
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
    rc1 = run_cmd(cmd)

    # 2) Validation EV/ROI
    rc2 = run_cmd(["python", "validator_ev.py",
                   "--reunion", R or "", "--course", C or "", "--rules", "gpi_v51.yml"])

    return {"ok": (rc1 == 0 and rc2 == 0), "R": R, "C": C, "phase": when, "url": course_url or reunion_url}
PY
t("course")
    when = payload.ge
