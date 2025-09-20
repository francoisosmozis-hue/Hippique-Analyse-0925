from fastapi import FastAPI

app = FastAPI(title="Arrivee API")


@app.get("/", tags=["meta"])
async def meta_root() -> dict[str, str]:
    return {"service": "Arrivee API"}


@app.get("/healthz", tags=["meta"])
@app.get("/healthz/", tags=["meta"])
async def meta_healthz() -> dict[str, bool]:
    return {"ok": True}
