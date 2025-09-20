from fastapi import FastAPI, Query, HTTPException
import subprocess, json

# Désactive les redirections automatiques /healthz <-> /healthz/
app = FastAPI(title="Arrivee API", redirect_slashes=False)

@app.get("/", tags=["meta"])
def root():
    return {"service":"get-arrivee-geny","docs":"/docs","health":"/healthz"}

# Expose les DEUX chemins explicitement (sans redir)
@app.get("/healthz", tags=["meta"])
def healthz_no_slash():
    return {"ok": True}

@app.get("/healthz/", include_in_schema=False)
def healthz_with_slash():
    return {"ok": True}

# Tu pourras remettre /arrivee ensuite (on stabilise /healthz d'abord)
