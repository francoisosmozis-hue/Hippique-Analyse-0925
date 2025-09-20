from fastapi import FastAPI, HTTPException, Query

app = FastAPI(title="Arrivee API")


@app.get("/")
async def root() -> dict[str, str]:
    """Point d'entrée par défaut pour confirmer que l'API est joignable."""
    return {"message": "Bienvenue sur l'Arrivee API"}
    

@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Endpoint de santé très simple."""
    return {"status": "ok"}


@app.get("/arrivee")
async def arrivee(rc: str = Query(..., description="Identifiant de type R#C#")) -> dict[str, object]:
    """Endpoint temporaire renvoyant une charge JSON factice."""
    # from get_arrivee_geny import get_arrivee  # type: ignore[import-not-found]
    #
    # try:
    #     return get_arrivee(rc=rc)
    # except Exception as exc:
    #     raise HTTPException(status_code=500, detail=str(exc)) from exc    
   
    return {
        "rc": rc,
        "arrivee": [],
        "message": "Stub de réponse - à remplacer par get_arrivee_geny.get_arrivee",
    }


