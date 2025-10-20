import json
import subprocess

from fastapi import FastAPI, HTTPException, Query

app = FastAPI(title="Arrivee API", redirect_slashes=False)


@app.get("/", tags=["meta"])
def root():
    return {
        "service": "get-arrivee-geny",
        "docs": "/docs",
        "health": "/healthz",
        "arrivee": "/arrivee?race_id=...",
    }


@app.get("/healthz", tags=["meta"])
def healthz_no_slash():
    return {"ok": True}


@app.get("/healthz/", include_in_schema=False)
def healthz_with_slash():
    return {"ok": True}


@app.get("/arrivee", tags=["arrivee"])
def arrivee(race_id: str = Query(..., description="ID de course Geny")):
    try:
        out = subprocess.check_output(
            ["python", "get_arrivee_geny.py", "--race", race_id],
            text=True,
            timeout=35,
        ).strip()
        return json.loads(out) if out.startswith("{") else {"race_id": race_id, "raw": out}
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=e.output or "script error")
