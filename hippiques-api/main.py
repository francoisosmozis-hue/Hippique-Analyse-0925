from fastapi import FastAPI, Query, HTTPException
import subprocess, json

app = FastAPI(title="Arrivee API", redirect_slashes=False)

@app.get("/", tags=["meta"])
def root():
    return {"service":"get-arrivee-geny","docs":"/docs","health":"/healthz","arrivee":"/arrivee?race_id=..."}

@app.get("/healthz", tags=["meta"])
def healthz_no_slash(): return {"ok": True}

@app.get("/healthz/", include_in_schema=False)
def healthz_with_slash(): return {"ok": True}

# --- STUB pour valider la route ---
@app.get("/arrivee", tags=["arrivee"])
def arrivee(race_id: str = Query(..., description="ID de course Geny")):
    return {"race_id": race_id, "status": "stub OK"}
