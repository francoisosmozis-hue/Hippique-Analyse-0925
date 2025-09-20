"""Application FastAPI exposant des endpoints de santé et d'arrivée."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import sys

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# Rendez accessible le dossier racine du dépôt pour importer les utilitaires existants.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

try:  # pragma: no cover - l'import peut échouer hors du dépôt complet.
    from get_arrivee_geny import PlanningEntry, fetch_arrival
except ModuleNotFoundError:  # pragma: no cover - route neutralisée lorsqu'absente.
    PlanningEntry = None  # type: ignore[assignment]
    fetch_arrival = None  # type: ignore[assignment]

app = FastAPI(title="Hippiques API", version="0.1.0", description="API légère pour les flux hippiques")


class ArriveeRequest(BaseModel):
    """Payload attendu par l'endpoint /arrivee."""

    rc: str = Field(..., description="Identifiant de type R#C#")
    reunion: Optional[str] = Field(None, description="Numéro de réunion")
    course: Optional[str] = Field(None, description="Numéro de course")
    course_id: Optional[str] = Field(None, description="Identifiant Geny")
    url_geny: Optional[str] = Field(None, description="URL directe de la course sur Geny")


@app.get("/healthz", tags=["monitoring"])
async def healthz() -> Dict[str, str]:
    """Endpoint de santé simple pour vérifier que l'API répond."""

    return {"status": "ok"}


@app.post("/arrivee", tags=["arrivees"])
async def arrivee(payload: ArriveeRequest) -> Dict[str, Any]:
    """Retourne les informations d'arrivée pour la course demandée."""

    if PlanningEntry is None or fetch_arrival is None:
        raise HTTPException(
            status_code=503,
            detail="Endpoint temporairement désactivé (dépendance manquante).",
        )

    entry = PlanningEntry(
        rc=payload.rc,
        reunion=payload.reunion,
        course=payload.course,
        course_id=payload.course_id,
        url_geny=payload.url_geny,
    )
    result = fetch_arrival(entry)

    # Normalise la structure pour éviter les surprises côté client.
    return {
        "rc": result.get("rc", entry.rc),
        "status": result.get("status", "unknown"),
        "result": result.get("result"),
        "url": result.get("url"),
        "retrieved_at": result.get("retrieved_at"),
        "error": result.get("error"),
    }


__all__ = ["app"]
