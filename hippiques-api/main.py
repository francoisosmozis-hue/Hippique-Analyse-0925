from fastapi import FastAPI, Query, HTTPException
import subprocess, json

# Coupe les redirections automatiques /foo <-> /foo/
app = FastAPI(title="Arrivee API", redirect_slashes=False)

@app.get("/", tags=["meta"])
def root():
    return {"service":"get-arrivee-geny","docs":"/docs","health":"/healthz"}

# Expose /healthz ET /healthz/ explicitement (pour éviter tout 307)
@app.get("/healthz", tags=["meta"])
def healthz_no_slash():
    return {"ok": True}

@app.get("/healthz/", include_in_schema=False)
def healthz_with_slash():
    return {"ok": True}

# (tu remettras /arrivee une fois /healthz validé)
