from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="Arrivee API")

@app.get("/", tags=["meta"])
def root():
    return {"service":"get-arrivee-geny","docs":"/docs","health":"/healthz"}

@app.get("/healthz", tags=["meta"])
@app.get("/healthz/", include_in_schema=False)
def healthz():
    return {"ok": True}

# WILDCARD: attrape tout le reste pour diagnostiquer (retourne 200)
@app.api_route("/{full_path:path}", methods=["GET","HEAD","POST","PUT","PATCH","DELETE"])
def catch_all(full_path: str):
    return JSONResponse({"path": f"/{full_path}", "note": "wildcard handler"}, status_code=200)
