"""hippique_orchestrator.data_contract

Contrats Pydantic utilisés par l'orchestrateur et validés par la suite de tests.

- La CI de ce repo cible explicitement les modèles définis dans ce fichier.
- Parsing permissif (ex: heures au format "HH:MM")
- Champs optionnels afin de supporter les différents fournisseurs.
"""

from __future__ import annotations
import re

from datetime import date, datetime, time
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, ValidationInfo


class Runner(BaseModel):
    model_config = ConfigDict(extra="allow")

    num: int
    nom: str
    odds_win: Optional[float] = None
    odds_place: Optional[float] = None
    musique: Optional[str] = None

    @field_validator("nom")
    @classmethod
    def _non_empty_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Runner name cannot be empty")
        return v

    @field_validator("odds_win", "odds_place", mode="before")
    @classmethod
    def _sanitize_odds(cls, v: Any) -> Optional[float]:
        if v is None:
            return None
        try:
            f = float(v)
        except Exception:
            return None
        # Odds < 1.0 invalid -> None (tests), 1.0 allowed
        if f < 1.0:
            return None
        return f


class Race(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Core identifiers
    race_id: str
    reunion_id: int
    course_id: int

    # Core metadata
    hippodrome: str
    date: date
    country_code: str = "FR"

    # Optional fields
    rc: Optional[str] = None
    name: Optional[str] = None
    start_time: Optional[datetime] = None
    url: Optional[str] = None
    discipline: Optional[str] = None
    distance_m: Optional[int] = None
    runners_count: Optional[int | str] = None

    runners: List[Runner] = Field(default_factory=list)

    @field_validator("race_id")
    @classmethod
    def _race_id_non_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("race_id cannot be empty")
        return v

    @field_validator("hippodrome")
    @classmethod
    def _hippodrome_non_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("hippodrome cannot be empty")
        return v

    @field_validator("start_time", mode="before")
    @classmethod
    def _parse_start_time(cls, v, info: "ValidationInfo"):
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        # If a time object, combine with date
        if isinstance(v, time):
            d = info.data.get("date")
            if isinstance(d, str):
                try:
                    d = date.fromisoformat(d)
                except Exception:
                    d = None
            return datetime.combine(d, v) if d else None

        if isinstance(v, str):
            s = v.strip()
            # Accept HH:MM
            if re.fullmatch(r"\d{2}:\d{2}", s):
                d = info.data.get("date")
                if isinstance(d, str):
                    try:
                        d = date.fromisoformat(d)
                    except Exception:
                        d = None
                if not d:
                    return None
                hh, mm = s.split(":")
                return datetime.combine(d, time(int(hh), int(mm)))
            # Accept ISO datetime
            try:
                return datetime.fromisoformat(s)
            except Exception:
                return None

        # Any other type -> let pydantic handle or null
        return None


    @model_validator(mode="after")
    def _coerce_start_time(self) -> "Race":
        # Accept "HH:MM" strings and normalize to datetime
        if isinstance(self.start_time, str):
            s = self.start_time.strip()
            try:
                hh, mm = s.split(":", 1)
                t = time(int(hh), int(mm))
                self.start_time = datetime.combine(self.date, t)
            except Exception:
                self.start_time = None
        elif isinstance(self.start_time, time):
            self.start_time = datetime.combine(self.date, self.start_time)
        return self

    @property
    def id(self) -> str:
        return f"{self.date.isoformat()}_{self.race_id}"


class Programme(BaseModel):
    model_config = ConfigDict(extra="allow")

    date: date
    races: List[Race] = Field(default_factory=list)


class Meeting(BaseModel):
    model_config = ConfigDict(extra="allow")

    hippodrome: str
    date: date
    country_code: str = "FR"
    races: List[Race] = Field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.date.isoformat()}_{self.hippodrome}"


class QualityReport(BaseModel):
    status: str
    score: float
    reason: str


class RaceSnapshot(BaseModel):
    race: Race
    provider: str
    fetched_at: datetime
    quality: QualityReport

    @classmethod
    def from_race(cls, race: Race, provider: str) -> "RaceSnapshot":
        runners = race.runners or []
        total = len(runners)

        if total == 0:
            quality = QualityReport(status="FAILED", score=0.0, reason="No runners in snapshot")
        else:
            complete_odds = sum(
                1 for r in runners if (r.odds_win is not None and r.odds_place is not None)
            )
            music = sum(1 for r in runners if (r.musique is not None and str(r.musique).strip()))

            odds_cov = complete_odds / total
            music_cov = music / total

            # Matches tests: 2/4 odds + 2/4 musique -> 0.50
            score = round(0.5 * odds_cov + 0.5 * music_cov, 2)

            if score < 0.4:
                status = "FAILED"
            elif score < 0.8:
                status = "DEGRADED"
            else:
                status = "OK"

            reason = f"{complete_odds}/{total} runners with complete odds"
            quality = QualityReport(status=status, score=score, reason=reason)

        return cls(race=race, provider=provider, fetched_at=datetime.utcnow(), quality=quality)
