import os
import subprocess
from typing import Dict
from fastapi import FastAPI, Body, HTTPException
from dotenv import load_dotenv

ENV_PATH = "/secrets/.env"
if os.path.exists(ENV_PATH):
    load_dotenv(ENV_PATH)

app = FastAPI()


@app.get("/health")
def health():
    return {"ok": True, "budget": os.getenv("GPI_BUDGET", "5")}


def run_cmd(args: list[str]) -> int:
    print(">>", " ".join(args), flush=True)
    # IMPORTANT: cwd=/app (racine dans l'image)
    return subprocess.call(args, cwd="/app")


@app.post("/run/hminus")
def run_hminus(payload: Dict = Body(...)):
    R = payload.get("R") or payload.get("reunion")
    C = payload.get("C") or payload.get("course")
    when = payload.get("when", "H-5")
    if not R or not C:
        raise HTTPException(
            status_code=400, detail="Body JSON requis: R/reunion et C/course"
        )

    budget = os.getenv("GPI_BUDGET", "5")

    rc1 = run_cmd(
        [
            "python",
            "analyse_courses_du_jour_enrichie.py",
            "--reunion",
            R,
            "--course",
            C,
            "--phase",
            when,
            "--budget",
            budget,
        ]
    )

    rc2 = run_cmd(
        [
            "python",
            "validator_ev.py",
            "--reunion",
            R,
            "--course",
            C,
            "--rules",
            "gpi_v51.yml",
        ]
    )

    ok = rc1 == 0 and rc2 == 0
    return {
        "ok": ok,
        "R": R,
        "C": C,
        "phase": when,
        "rc_analyse": rc1,
        "rc_validator": rc2,
    }
