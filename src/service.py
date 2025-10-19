"""FastAPI service exposing scheduling and runner endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pydantic import BaseModel, Field, field_validator

from .config import Settings, get_settings
from .logging_utils import get_logger, setup_logging
from .plan import build_plan
from .runner import run_course
from .scheduler import create_one_shot_job, enqueue_run_task
from .time_utils import (
    combine_local_datetime,
    minutes,
    now_local,
    parse_plan_date,
)

setup_logging()
LOGGER = get_logger(__name__)
app = FastAPI(title="Hippique Analyse Orchestrator", version="1.0.0")


class ScheduleRequest(BaseModel):
    date: str = Field(default="today", description="Date YYYY-MM-DD or 'today'")
    mode: str = Field(default="tasks", description="Scheduling backend: tasks or scheduler")

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        value = value.lower()
        if value not in {"tasks", "scheduler"}:
            raise ValueError("mode must be 'tasks' or 'scheduler'")
        return value


class RunRequest(BaseModel):
    course_url: str
    phase: str
    date: str

    @field_validator("phase")
    @classmethod
    def normalise_phase(cls, value: str) -> str:
        cleaned = value.replace("-", "").upper()
        if cleaned not in {"H30", "H5"}:
            raise ValueError("phase must be H-30/H30 or H-5/H5")
        return cleaned


class ScheduleSummary(BaseModel):
    identifier: str
    phase: str
    method: str
    scheduled: bool
    schedule_time_local: str | None = None
    schedule_time_utc: str | None = None
    skipped_reason: str | None = None
    name: str | None = None


class ScheduleResponse(BaseModel):
    plan: list[dict[str, Any]]
    scheduled: list[ScheduleSummary]
    plan_path: str
    plan_uploaded: str | None


class RunResponse(BaseModel):
    ok: bool
    rc: int
    stdout_tail: str
    artifacts: list[str]
    uploaded: list[str] | None = None


async def ensure_authenticated(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """Validate the request authentication if required."""

    if not settings.require_auth:
        return
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    token = auth_header.split(" ", 1)[1]
    try:
        id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            audience=settings.service_audience or settings.resolved_service_url,
        )
    except Exception as exc:  # pragma: no cover - dependent on env
        LOGGER.warning("auth_failed", extra={"error": str(exc)})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token") from exc


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    settings = get_settings()
    if settings.require_auth:
        try:
            await ensure_authenticated(request, settings)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/schedule", response_model=ScheduleResponse)
async def schedule_endpoint(request: ScheduleRequest, http_request: Request) -> ScheduleResponse:
    settings = get_settings()
    plan_date = parse_plan_date(request.date, tz_name=settings.timezone)
    plan = build_plan(plan_date.isoformat())
    plan_path = _persist_plan(plan, settings, plan_date.isoformat())
    uploaded = _upload_plan(plan, settings, plan_date.isoformat())

    run_url = _resolve_run_url(settings, http_request)
    summaries: list[ScheduleSummary] = []
    now = now_local(settings.timezone)

    for entry in plan:
        identifier = f"{entry['date']}-{entry['r_label']}{entry['c_label']}"
        if not entry.get("time_local"):
            summaries.append(
                ScheduleSummary(
                    identifier=identifier,
                    phase="-",
                    method=request.mode,
                    scheduled=False,
                    skipped_reason="missing_time",
                )
            )
            continue
        course_time = combine_local_datetime(plan_date, entry["time_local"], tz_name=settings.timezone)
        offsets = [("H30", minutes(30)), ("H5", minutes(5))]
        for phase, delta in offsets:
            run_time = course_time - delta
            if run_time <= now:
                summaries.append(
                    ScheduleSummary(
                        identifier=identifier,
                        phase=phase,
                        method=request.mode,
                        scheduled=False,
                        schedule_time_local=run_time.isoformat(),
                        skipped_reason="in_past",
                    )
                )
                continue
            payload = {
                "course_url": entry["course_url"],
                "phase": phase,
                "date": entry["date"],
            }
            correlation_id = f"{entry['date']}-{entry['r_label'].lower()}-{entry['c_label'].lower()}-{phase.lower()}"
            if request.mode == "tasks":
                result = enqueue_run_task(
                    settings,
                    run_url=run_url,
                    payload=payload,
                    course_url=entry["course_url"],
                    phase=phase,
                    when_local=run_time,
                    correlation_id=correlation_id,
                )
                created = result.get("created", True)
                summaries.append(
                    ScheduleSummary(
                        identifier=identifier,
                        phase=phase,
                        method="tasks",
                        scheduled=created,
                        schedule_time_local=result["schedule_time_local"],
                        schedule_time_utc=result["schedule_time_utc"],
                        name=result["name"],
                        skipped_reason=None if created else "already_exists",
                    )
                )
            else:
                job_name = _build_scheduler_job_name(entry, phase)
                result = create_one_shot_job(
                    settings,
                    job_name=job_name,
                    run_url=run_url,
                    payload=payload,
                    when_local=run_time,
                    correlation_id=correlation_id,
                )
                created = result.get("created", True)
                summaries.append(
                    ScheduleSummary(
                        identifier=identifier,
                        phase=phase,
                        method="scheduler",
                        scheduled=created,
                        schedule_time_local=result.get("schedule_time_local"),
                        schedule_time_utc=result.get("schedule_time_utc"),
                        name=result.get("name"),
                        skipped_reason=None if created else "already_exists",
                    )
                )

    return ScheduleResponse(
        plan=plan,
        scheduled=summaries,
        plan_path=str(plan_path),
        plan_uploaded=uploaded,
    )


@app.post("/run", response_model=RunResponse)
async def run_endpoint(request: RunRequest) -> RunResponse:
    try:
        result = run_course(
            request.course_url,
            request.phase,
            extra_env={
                "RUN_DATE": request.date,
                "PLAN_DATE": request.date,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return RunResponse(**result)


def _resolve_run_url(settings: Settings, http_request: Request) -> str:
    if settings.resolved_service_url:
        return settings.resolved_service_url.rstrip("/") + "/run"
    return str(http_request.url_for("run_endpoint"))


def _persist_plan(plan: list[dict[str, Any]], settings: Settings, plan_date: str) -> Path:
    path = settings.plan_path
    data = {
        "date": plan_date,
        "generated_at": now_local(settings.timezone).isoformat(),
        "entries": plan,
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _upload_plan(plan: list[dict[str, Any]], settings: Settings, plan_date: str) -> str | None:
    if not settings.gcs_bucket:
        return None
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(settings.gcs_bucket)
    prefix = settings.gcs_prefix.strip("/") if settings.gcs_prefix else ""
    blob_name = f"plan-{plan_date}.json"
    if prefix:
        blob_name = f"{prefix}/{blob_name}"
    blob = bucket.blob(blob_name)
    blob.upload_from_string(
        data=json.dumps({"date": plan_date, "entries": plan}, ensure_ascii=False),
        content_type="application/json",
    )
    return blob.public_url or blob.name


def _build_scheduler_job_name(entry: dict[str, Any], phase: str) -> str:
    base = f"run-{entry['date'].replace('-', '')}-{entry['r_label'].lower()}-{entry['c_label'].lower()}-{phase.lower()}"
    return base.replace("_", "-")


__all__ = ["app"]
