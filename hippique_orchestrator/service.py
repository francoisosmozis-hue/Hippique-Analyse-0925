"""
src/service.py - Main FastAPI application for the Hippique Orchestrator.
"""

from __future__ import annotations

import hashlib
import json
import os
import logging
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo
from typing import Any, Optional

from fastapi.middleware.cors import CORSMiddleware

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

# Exposed for tests (they patch these symbols)
from hippique_orchestrator import plan as plan  # noqa
from hippique_orchestrator import firestore_client as firestore_client  # noqa
from hippique_orchestrator import analysis_pipeline as analysis_pipeline # noqa
from hippique_orchestrator.auth import _require_api_key
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.schemas import BootstrapDayRequest
from hippique_orchestrator.api.tasks import (
    router as tasks_router,
    bootstrap_day_task,
    OIDC_TOKEN_DEPENDENCY,
)
from hippique_orchestrator.firestore_client import (
    get_races_for_date,
    get_processing_status_for_date,
    update_race_document,
)
from hippique_orchestrator.programme_provider import get_programme_for_date
from hippique_orchestrator.orchestrator_runner import run_course_analysis_pipeline
from hippique_orchestrator.config import (
    REQUIRE_AUTH,
    INTERNAL_API_SECRET,
    PROJECT_ID,
    LOCATION,
    BUCKET_NAME,
    TASK_QUEUE,
    TASK_OIDC_SA_EMAIL,
)

app = FastAPI(
    title="hippique-orchestrator",
    description="API for managing horse racing data and pronostics.",
    version="1.0.0",
    openapi_tags=[
        {"name": "Pronostics", "description": "Endpoints for retrieving horse racing predictions."},
        {"name": "Operational", "description": "Endpoints for triggering and monitoring internal operations."},
        {"name": "Tasks", "description": "Endpoints for Cloud Tasks workers."},
        {"name": "Monitoring", "description": "Endpoints for system health and status."},
        {"name": "Debug", "description": "Endpoints for debugging and configuration inspection."},
    ],
)

app.include_router(tasks_router, prefix="/tasks")

from fastapi.middleware.cors import CORSMiddleware

# Configure CORS
origins = ["*"]  # Allow all origins for now, restrict in production

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Root and UI Endpoints ---
@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/pronostics")

@app.get("/pronostics", response_class=HTMLResponse, include_in_schema=False)
async def pronostics_ui():
    # In a real app, you might have more robust static file handling
    try:
        with open("static/index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>UI not found</h1>"

# --- Health Check Endpoints ---
@app.get("/health", tags=["Monitoring"])
async def health_check():
    return {"ok": True, "status": "healthy"}

@app.get("/healthz", include_in_schema=False)  # Alias for /health
async def healthz():
    return await health_check()

@app.get("/__health", include_in_schema=False)  # Another alias for /health
async def double_underscore_health():
    return await health_check()

# --- API Endpoints ---
@app.get("/api/pronostics", tags=["Pronostics"])
async def get_pronostics_data(
    request: Request,
    date: Optional[date] = None,
    phase: Optional[str] = None,
):
    if date is None:
        date = datetime.now(timezone.utc).date()

    etag_content = f"{date.isoformat()}-{phase or ''}"
    etag = hashlib.sha256(etag_content.encode()).hexdigest()

    if "if-none-match" in request.headers and request.headers["if-none-match"] == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED)

    programme = await run_in_threadpool(get_programme_for_date, date)
    firestore_races = await get_races_for_date(date)

    merged_races = []
    if programme and programme.races:
        for race_in_plan in programme.races:
            fs_race_data = next(
                (
                    r.to_dict()
                    for r in firestore_races
                    if hasattr(r, "id") and r.id == f"{race_in_plan.date.isoformat()}_{race_in_plan.rc}"
                ),
                {},
            )
            merged_race = {**race_in_plan.model_dump(mode='json'), **fs_race_data}
            if phase:
                if (
                    "gpi_decision" in merged_race
                    and merged_race["gpi_decision"].lower() == "play"
                ):
                    merged_races.append(merged_race)
            else:
                merged_races.append(merged_race)

    response_content = {"ok": True, "date": date.isoformat(), "races": merged_races}
    response = JSONResponse(content=response_content)
    response.headers["ETag"] = etag
    return response

@app.get("/api/plan", tags=["Pronostics"])
async def get_daily_plan_endpoint(date: Optional[date] = None):
    if date is None:
        date = datetime.now(timezone.utc).date()
    daily_plan = await run_in_threadpool(get_programme_for_date, date)
    if daily_plan:
        response_content = {"ok": True, **daily_plan.model_dump(by_alias=True, mode='json')}
        return JSONResponse(content=response_content)
    return JSONResponse(content={"ok": True, "date": date.isoformat(), "races": []})

# --- Operational Endpoints ---
@app.post("/ops/run", tags=["Operational"])
async def run_single_race_analysis(request: Request, rc: str, phase: str):
    _require_api_key(request)
    course_url = f"http://example.com/races/{rc}"
    gpi_output = await run_course_analysis_pipeline(course_url, phase)
    await update_race_document(rc, gpi_output.model_dump(mode='json'))
    return {"ok": True, "status": "ok", "rc": rc, "gpi_decision": gpi_output.gpi_decision}

@app.get("/ops/status", tags=["Operational"])
async def get_ops_status(request: Request, date: Optional[date] = None):
    _require_api_key(request)
    if date is None:
        date = datetime.now(timezone.utc).date()
    daily_plan = await run_in_threadpool(get_programme_for_date, date)
    status_data = await firestore_client.get_processing_status_for_date(date.isoformat(), [r.model_dump(mode='json') for r in daily_plan.races] if daily_plan else [])
    status_data["ok"] = True # Add ok: True to status_data
    return status_data

# --- Debug Endpoints ---
@app.get("/debug/config", tags=["Debug"])
async def debug_config(request: Request):
    _require_api_key(request)
    return {
        "ok": True,
        "project_id": PROJECT_ID,
        "location": LOCATION,
        "gcs_bucket_name": BUCKET_NAME,
        "cloud_tasks_queue": TASK_QUEUE,
        "cloud_tasks_oidc_sa_email": TASK_OIDC_SA_EMAIL,
        "require_auth": REQUIRE_AUTH,
        "internal_api_secret_is_set": bool(INTERNAL_API_SECRET),
        "environment": os.getenv("ENV", "development"),
        "version": "1.0.0",
    }

# Legacy stubs (for compatibility)
@app.post("/schedule", include_in_schema=False)
async def legacy_schedule_stub(request: Request, body: BootstrapDayRequest):
    _require_api_key(request)
    return await bootstrap_day_task(request, body)

@app.post("/analyse", include_in_schema=False)
async def legacy_analyse_stub(request: Request):
    _require_api_key(request)
    return {"ok": True, "message": "Analyser not implemented"}

@app.post("/pipeline/run", include_in_schema=False)
async def legacy_pipeline_run_stub(request: Request):
    _require_api_key(request)
    return {"ok": True, "message": "Pipeline runner not implemented"}
