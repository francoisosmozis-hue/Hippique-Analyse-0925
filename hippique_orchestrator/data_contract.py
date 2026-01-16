import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class RunnerStats(BaseModel):
    """Stats normalisées pour un jockey ou un entraîneur."""
    driver_rate: float | None = Field(None, description="Taux de réussite du jockey/driver")
    trainer_rate: float | None = Field(None, description="Taux de réussite de l'entraîneur")
    last_3_chrono: list[float] = Field(default_factory=list, description="Liste des 3 derniers chronos")
    record_rk: float | None = Field(None, description="Record sur la distance ou parcours")
    source_stats: str | None = Field(None, description="Provider qui a fourni ces stats (e.g., 'LeTrot')")


class RunnerData(BaseModel):
    """Contrat de données pour un partant."""
    num: int
    nom: str
    musique: str | None = None
    odds_place: float | None = None
    odds_win: float | None = None
    driver: str | None = None
    trainer: str | None = None
    age: int | None = None
    gains: str | None = None
    draw: int | None = Field(None, description="Numéro de corde ou de couloir")
    stats: RunnerStats = Field(default_factory=RunnerStats)


class RaceData(BaseModel):
    """Contrat de données pour une course."""
    date: datetime.date
    rc_label: str  # e.g., "R1C1"
    discipline: Literal["Trot Attelé", "Trot Monté", "Plat", "Obstacle", "Haies", "Steeple-Chase", "Attelé"] | None = None
    distance: int | None = None
    corde: Literal["D", "G"] | None = None
    type_course: str | None = None
    prize: str | None = None
    start_time_local: datetime.time | None = None


class RaceSnapshotNormalized(BaseModel):
    """Le Data Contract complet pour un snapshot de course."""
    race: RaceData
    runners: list[RunnerData]
    source_snapshot: str  # Provider qui a fourni le le snapshot principal (e.g., 'Zeturf')
    meta: dict[str, Any] = Field(default_factory=dict) # Added meta field for additional metadata


QualityStatus = Literal["OK", "DEGRADED", "FAILED"]

def calculate_quality_score(snapshot: RaceSnapshotNormalized) -> dict:
    """
    Calcule le score de qualité d'un snapshot.
    - FAILED: Pas de partants ou infos de course manquantes.
    - DEGRADED: Données partielles (ex: cotes manquantes).
    - OK: Données jugées complètes.
    """
    if not snapshot.runners:
        return {"score": 0.0, "status": "FAILED", "reason": "No runners in snapshot"}

    total_runners = len(snapshot.runners)
    runners_with_place_odds = sum(1 for r in snapshot.runners if r.odds_place is not None and r.odds_place > 1.0)
    runners_with_musique = sum(1 for r in snapshot.runners if r.musique)
    runners_with_stats = sum(1 for r in snapshot.runners if r.stats.driver_rate or r.stats.trainer_rate)

    # Pondération simple : les cotes sont les plus importantes
    score = (
        0.6 * (runners_with_place_odds / total_runners) +
        0.2 * (runners_with_musique / total_runners) +
        0.2 * (runners_with_stats / total_runners)
    )

    status: QualityStatus
    if score < 0.5:
        status = "FAILED"
    elif score < 0.85:
        status = "DEGRADED"
    else:
        status = "OK"

    return {"score": round(score, 2), "status": status, "reason": f"{runners_with_place_odds}/{total_runners} place_odds"}


def compute_odds_place_ratio(place_odds: dict[str, float], num_partants: int) -> float:
    """
    Calcule le ratio de couverture des cotes de place.
    """
    if not place_odds or num_partants <= 0:
        return 0.0

    covered_runners = len(place_odds)
    return covered_runners / num_partants
