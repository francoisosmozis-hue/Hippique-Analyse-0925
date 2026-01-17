import datetime
from typing import Any, Dict, List, Literal, Optional, TypeAlias

from pydantic import BaseModel, Field, field_validator, computed_field

# --- Enums and Literals ---

QualityStatus = Literal["OK", "DEGRADED", "FAILED"]
Discipline = Literal["Trot Attelé", "Trot Monté", "Plat", "Obstacle", "Haies", "Steeple-Chase", "Attelé"]
Corde = Literal["D", "G"]


# --- Core Data Models ---

class Runner(BaseModel):
    """Data contract for a single runner in a race."""
    num: int
    nom: str
    age: Optional[int] = None
    sexe: Optional[str] = None
    musique: Optional[str] = None
    driver: Optional[str] = None
    trainer: Optional[str] = None
    gains: Optional[str] = None
    draw: Optional[int] = Field(None, description="Corridor number or rope")

    # Odds - often fetched separately or later
    odds_win: Optional[float] = None
    odds_place: Optional[float] = None

    @field_validator("odds_place", "odds_win")
    @classmethod
    def check_odds_value(cls, v: Optional[float]) -> Optional[float]:
        """Validate that odds are >= 1.0 if they exist."""
        if v is not None and v < 1.0:
            return None  # Invalidate data instead of raising an error
        return v

class Race(BaseModel):
    """Data contract for a single race."""
    # Core identifiers
    race_id: str # Natural key, e.g., "R1C1"
    reunion_id: int
    course_id: int
    hippodrome: Optional[str] = None
    country_code: str = "FR"

    # Date and time
    date: datetime.date
    start_time: Optional[datetime.time] = None

    # Race specifics
    name: Optional[str] = None
    discipline: Optional[Discipline] = None
    distance: Optional[int] = None
    corde: Optional[Corde] = None
    type_course: Optional[str] = None
    prize: Optional[str] = None
    partants: Optional[int] = None

    # Linked data
    runners: List[Runner] = Field(default_factory=list)
    url: Optional[str] = None  # The unique URL to the race page

    @computed_field
    @property
    def id(self) -> str:
        """Computes a unique, persistent ID for the race."""
        return f"{self.date.strftime('%Y-%m-%d')}_R{self.reunion_id}C{self.course_id}"

# Type alias for backward compatibility
RaceData: TypeAlias = Race

class Meeting(BaseModel):
    """Data contract for a meeting, which is a collection of races."""
    hippodrome: str
    country_code: str = "FR"
    date: datetime.date

    # Computed fields
    races_count: int = 0
    races: List[Race] = Field(default_factory=list)

    @computed_field
    @property
    def id(self) -> str:
        """Computes a unique, persistent ID for the meeting."""
        return f"{self.date.strftime('%Y-%m-%d')}_{self.hippodrome.upper().replace(' ', '-')}"


# --- Quality and Snapshot Models ---

class QualityReport(BaseModel):
    """Provides a quality assessment of the data for a race."""
    score: float
    status: QualityStatus
    reason: str

class RaceSnapshot(BaseModel):
    """
    Represents the complete data for a race at a point in time,
    including a quality assessment.
    """
    race: Race
    quality: QualityReport
    source_provider: str  # The provider that generated this snapshot (e.g., 'boturfers')
    meta: Dict[str, Any] = Field(default_factory=dict) # For additional metadata

    @classmethod
    def from_race(cls, race: Race, provider_name: str, meta: Optional[Dict] = None) -> "RaceSnapshot":
        """Factory method to create a snapshot from a Race object and assess its quality."""
        if not race.runners:
            quality = QualityReport(score=0.0, status="FAILED", reason="No runners in snapshot")
        else:
            total_runners = len(race.runners)
            runners_with_odds = sum(1 for r in race.runners if r.odds_win and r.odds_place)
            runners_with_musique = sum(1 for r in race.runners if r.musique)

            # Simple weighted scoring
            score = (
                0.7 * (runners_with_odds / total_runners) +
                0.3 * (runners_with_musique / total_runners)
            )

            if score < 0.4:
                status: QualityStatus = "FAILED"
            elif score < 0.8:
                status: QualityStatus = "DEGRADED"
            else:
                status: QualityStatus = "OK"

            quality = QualityReport(
                score=round(score, 2),
                status=status,
                reason=f"{runners_with_odds}/{total_runners} runners with complete odds"
            )

        return cls(
            race=race,
            quality=quality,
            source_provider=provider_name,
            meta=meta or {}
        )


class Programme(BaseModel):
    """Data contract for a full day's programme of races."""
    date: datetime.date
    races: List[Race] = Field(default_factory=list)

    @computed_field
    @property
    def races_count(self) -> int:
        return len(self.races)
