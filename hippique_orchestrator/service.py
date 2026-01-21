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

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

# Exposed for tests (they patch these symbols)
from hippique_orchestrator import plan as plan  # noqa
from hippique_orchestrator import firestore_client as firestore_client  # noqa
from hippique_orchestrator import analysis_pipeline as analysis_pipeline # noqa
from hippique_orchestrator.auth import _require_api_key
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.api.tasks import bootstrap_day_task, OIDC_TOKEN_DEPENDENCY # Added this import
from hippique_orchestrator.schemas import BootstrapDayRequest # Added this import


from hippique_orchestrator.api.tasks import router as tasks_router # Import the tasks router

app = FastAPI(title="hippique-orchestrator")

app.include_router(tasks_router) # Include the tasks router

logger = get_logger(__name__)

UTC = ZoneInfo("UTC")

# ... (rest of the file remains the same until legacy_schedule_stub)

@app.post("/schedule", include_in_schema=False)
async def legacy_schedule_stub(request: Request, body: BootstrapDayRequest, token_claims: dict = OIDC_TOKEN_DEPENDENCY):
    _require_api_key(request)
    # Re-use the logic from bootstrap_day_task
    return await bootstrap_day_task(request, body, token_claims)



@app.post("/analyse", include_in_schema=False)

async def legacy_analyse_stub(request: Request):

    _require_api_key(request)

    return {"ok": True, "message": "Analyser not implemented"}



@app.post("/pipeline/run", include_in_schema=False)

async def legacy_pipeline_run_stub(request: Request):

    _require_api_key(request)

    return {"ok": True, "message": "Pipeline runner not implemented"}
