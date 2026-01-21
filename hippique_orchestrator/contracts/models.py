# hippique_orchestrator/contracts/models.py
"""
Pydantic models for data contracts. This is the single source of truth
for data structures throughout the application.
"""
from datetime import datetime, date
from typing import List, Dict, Optional, Any

from pydantic import BaseModel, Field, model_validator
import re

class Meeting(BaseModel):
    id_provider: str
    date: date
    venue: str = Field(..., description="Normalized venue name, e.g., 'VINCENNES'")
    race_count: int


    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_inputs(cls, data):
        if not isinstance(data, dict):
            return data

        # If already canonical
        if "race_uid" in data and "meeting_ref" in data and "scheduled_time_local" in data:
            return data

        race_id = data.get("race_id") or data.get("id") or data.get("raceId")
        hippo = data.get("hippo") or data.get("venue") or data.get("hippodrome") or ""
        discipline = data.get("discipline") or data.get("type") or data.get("code_discipline") or ""
        distance_m = data.get("distance_m") or data.get("distance") or data.get("distanceMeters") or 0

        # runners_count legacy
        runners = data.get("runners")
        runners_count = data.get("runners_count") or data.get("nb_partants") or data.get("partants")
        if isinstance(runners, list):
            runners_count = len(runners)
        runners_count = int(runners_count or 0)

        # race_number legacy
        race_number = data.get("race_number")
        if race_number is None and isinstance(race_id, str):
            m = re.search(r"C(\d+)$", race_id)
            if m:
                try:
                    race_number = int(m.group(1))
                except Exception:
                    race_number = 0
        race_number = int(race_number or 0)

        # scheduled_time_local legacy
        d = data.get("date")
        t = data.get("time") or data.get("scheduled_time") or data.get("heure")
        scheduled_dt = data.get("scheduled_time_local")
        if scheduled_dt is None:
            if d and t:
                tt = str(t)
                if len(tt) == 5:
                    scheduled_dt = datetime.fromisoformat(f"{d}T{tt}:00")
                else:
                    scheduled_dt = datetime.fromisoformat(f"{d}T{tt}")
            elif d:
                scheduled_dt = datetime.fromisoformat(f"{d}T00:00:00")
            else:
                scheduled_dt = datetime.fromisoformat("1970-01-01T00:00:00")

        meeting_ref = data.get("meeting_ref") or f"{d or ''}:{hippo}"

        # make race_uid with best-effort import
        make_race_uid = None
        for mod_path in (
            "hippique_orchestrator.contracts.ids",
            "hippique_orchestrator.ids",
            "hippique_orchestrator.contracts.utils",
        ):
            try:
                mod = __import__(mod_path, fromlist=["make_race_uid"])
                make_race_uid = getattr(mod, "make_race_uid", None)
                if make_race_uid:
                    break
            except Exception:
                continue

        if make_race_uid:
            try:
                race_uid = make_race_uid(
                    date=str(d or ""),
                    hippo=str(hippo),
                    race_number=int(race_number),
                    discipline=str(discipline),
                    distance_m=int(distance_m),
                    scheduled_time_local=scheduled_dt.isoformat() if hasattr(scheduled_dt, "isoformat") else str(scheduled_dt),
                )
            except Exception:
                race_uid = f"{meeting_ref}:{race_number}:{discipline}:{distance_m}"
        else:
            race_uid = f"{meeting_ref}:{race_number}:{discipline}:{distance_m}"

        data["race_uid"] = data.get("race_uid") or race_uid
        data["meeting_ref"] = data.get("meeting_ref") or meeting_ref
        data["race_number"] = data.get("race_number") or race_number
        data["scheduled_time_local"] = data.get("scheduled_time_local") or scheduled_dt
        data["discipline"] = data.get("discipline") or discipline
        data["distance_m"] = int(data.get("distance_m") or distance_m or 0)
        data["runners_count"] = int(data.get("runners_count") or runners_count)

        # keep legacy fields if present
        if "race_id" not in data:
            data["race_id"] = race_id
        if "hippo" not in data:
            data["hippo"] = hippo

        return data
class Race(BaseModel):
    race_uid: str = Field(..., description="Stable, unique hash-based ID for the race")
    meeting_ref: str
    race_number: int
    scheduled_time_local: datetime
    discipline: str = Field(..., description="e.g., 'ATTELE', 'PLAT', 'OBSTACLE'")
    distance_m: int
    runners_count: int
    status: str = Field("SCHEDULED", description="e.g., SCHEDULED, CANCELED")

class Runner(BaseModel):
    runner_uid: str = Field(..., description="Stable, unique hash-based ID for the runner")
    race_uid: str
    program_number: int
    name_norm: str = Field(..., description="Normalized horse name")
    age: Optional[int] = None
    sex: Optional[str] = None
    driver_jockey: Optional[str] = None
    trainer: Optional[str] = None
    gains: Optional[int] = None
    music_recent: Optional[str] = None
    chrono_recent: Optional[float] = None

class OddsSnapshot(BaseModel):
    race_uid: str
    phase: str = Field(..., description="e.g., 'AM0900', 'H30', 'H5'")
    timestamp_utc: datetime = Field(default_factory=datetime.utcnow)
    odds_place: Dict[str, float] = Field(default_factory=dict)
    odds_win: Optional[Dict[str, float]] = None
    source: str
    overround_place: Optional[float] = None

class Derived(BaseModel):
    implicit_probs: Optional[Dict[str, float]] = None
    drift: Dict[str, float] = Field(default_factory=dict, description="Drift H-30 -> H-5 per runner_uid")
    steam_flags: Dict[str, str] = Field(default_factory=dict, description="e.g., 'STEAM', 'DRIFT', 'STABLE'")

class DataQualityReport(BaseModel):
    score: int
    reasons: List[str]
    missing_fields: List[str]
    sources_used: List[str]
    phase_coverage: List[str]

class Ticket(BaseModel):
    type: str  # e.g., 'SP_DUTCHING', 'COUPLE_PLACE'
    stake: float
    roi_est: float
    horses: List[int]
    details: Dict[str, float] = Field(default_factory=dict)

class GPIOutput(BaseModel):
    race_uid: str
    playable: bool
    abstention_reasons: List[str] = Field(default_factory=list)
    tickets: List[Ticket] = Field(default_factory=list)
    ev_estimate: Optional[float] = None
    roi_estimate: Optional[float] = None
    quality_report: DataQualityReport
    derived_data: Optional[Derived] = None
