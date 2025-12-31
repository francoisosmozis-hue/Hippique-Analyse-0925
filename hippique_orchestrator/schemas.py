from pydantic import BaseModel, Field


class AnalyseGPIRequest(BaseModel):
    reunion: str
    course: str
    date: str
    budget: float


class BootstrapDayRequest(BaseModel):
    date: str
    mode: str = "tasks"


class Snapshot9HRequest(BaseModel):
    date: str | None = None
    meeting_urls: list[str] | None = Field(default_factory=list)
    rc_labels: list[str] | None = Field(default_factory=list)


class RunPhaseRequest(BaseModel):
    course_url: str
    phase: str
    date: str
    correlation_id: str | None = None


class ScheduleRequest(BaseModel):
    date: str | None = None
    force: bool = False
    dry_run: bool = False


class ScheduleDetail(BaseModel):
    race: str
    phase: str
    task_name: str | None
    ok: bool
    reason: str | None = None


class ScheduleResponse(BaseModel):
    message: str
    races_in_plan: int
    details: list[ScheduleDetail]
