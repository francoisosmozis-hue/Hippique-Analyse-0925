
from __future__ import annotations

from pydantic import BaseModel, validator


class Runner(BaseModel):
    num: str
    nom: str
    cote: float | None = None

class RaceSnapshot(BaseModel):
    source: str
    url: str
    scraped_at: str
    rc: str
    hippodrome: str | None = None
    discipline: str | None = None
    runners: list[Runner]

class NormalizedRaceSnapshot(BaseModel):
    rc: str
    hippodrome: str | None = None
    discipline: str | None = None
    date: str
    runners: list[Runner]
    id2name: dict[str, str]
    odds: dict[str, float]

    @validator('odds')
    def odds_values_must_be_positive(cls, v):
        for key, value in v.items():
            if value <= 0:
                raise ValueError(f"Odds for runner {key} must be positive, but got {value}")
        return v
