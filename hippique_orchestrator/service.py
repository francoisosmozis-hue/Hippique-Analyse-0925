"""
src/service.py - FastAPI Service Principal

Service Cloud Run orchestrant l'analyse hippique quotidienne.
"""

import asyncio
import contextlib
import hashlib
import json
import os
import uuid
from datetime import datetime
from io import StringIO
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import (
    APIRouter,
    BackgroundTasks,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from hippique_orchestrator import firestore_client, time_utils
from hippique_orchestrator.auth import auth_middleware
from hippique_orchestrator.config import get_config
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.plan import build_plan_async
from hippique_orchestrator.runner import run_course
from hippique_orchestrator.scheduler import enqueue_run_task, schedule_all_races
from google.cloud import tasks_v2

# ============================================
# Configuration
# ============================================

logger = get_logger(__name__)
config = get_config()

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static")
templates = Jinja2Templates(directory="templates")


app = FastAPI(
    title="Hippique Orchestrator",
    description="Cloud Run service for automated horse racing analysis (GPI v5.2)",
    version="2.1.0",
)

# Mount the static directory to serve static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ============================================
# Task Utilities
# ============================================


def get_scheduled_tasks(
    project: str, location: str, queue: str, limit: int = 10
) -> list[dict]:
    """Lists the next scheduled tasks from a Cloud Tasks queue."""
    try:
        client = tasks_v2.CloudTasksClient()
        queue_path = client.queue_path(project, location, queue)
        tasks = client.list_tasks(
            parent=queue_path,
            response_view=tasks_v2.Task.View.BASIC,
            page_size=limit,
        )

        # Cloud Tasks API ne supporte pas le tri direct, donc on trie en mémoire
        # On ne récupère que les tâches avec une schedule_time
        pending_tasks = [task for task in tasks if task.schedule_time]
        
        # Tri par schedule_time
        sorted_tasks = sorted(pending_tasks, key=lambda t: t.schedule_time.timestamp())

        task_list = []
        for task in sorted_tasks[:limit]:
            # Extrait le nom de la course depuis le payload si possible
            race_info = "Analyse de course"
            try:
                if task.http_request.body:
                    payload = json.loads(task.http_request.body)
                    # Exemple: "R1C1 H-30"
                    race_info = f"{payload.get('rc', '')} {payload.get('phase', '')}".strip()
            except (json.JSONDecodeError, KeyError):
                pass # Garder l'information générique

            task_list.append(
                {
                    "name": os.path.basename(task.name),
                    "schedule_time_utc": task.schedule_time.isoformat(),
                    "info": race_info
                }
            )
        return task_list
    except Exception as e:
        logger.error(f"Failed to list scheduled tasks: {e}", exc_info=True)
        return []


# ============================================
# Request/Response Models
# ============================================



class ScheduleRequest(BaseModel):
    date: str = Field("today", description="Date in YYYY-MM-DD format or 'today'")
    mode: str = Field("tasks", description="Scheduling mode: 'tasks' or 'scheduler'")


class RunRequest(BaseModel):
    course_url: str = Field(..., description="Full course URL")
    phase: str = Field(..., description="Analysis phase: 'H-30', 'H-5', etc.")
    date: str = Field(..., description="Race date in YYYY-MM-DD format")
    trace_id: str | None = None


# ============================================
# Middleware
# ============================================

# The auth middleware is placed here but applied selectively based on path
app.middleware("http")(auth_middleware)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request.state.correlation_id = correlation_id

    try:
        response = await call_next(request)
        # Use the same correlation_id for the response log
        logger.info(
            f"{request.method} {request.url.path}",
            extra={
                "correlation_id": correlation_id,
                "status_code": response.status_code,
            },
        )
        response.headers["X-Correlation-ID"] = correlation_id
        return response
    except Exception as e:
        logger.error(
            f"Request failed: {e}",
            exc_info=True,
            extra={"correlation_id": correlation_id},
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Internal server error", "correlation_id": correlation_id},
            headers={"X-Correlation-ID": correlation_id},
        )


# ============================================
# API Router
# ============================================

api_router = APIRouter(prefix="/api")


@api_router.get("/pronostics/ui", response_class=HTMLResponse)
async def pronostics_ui(request: Request):
    """Serves the main HTML page for pronostics."""
    # Serve index.html directly from the static directory
    with open(os.path.join(STATIC_DIR, "index.html")) as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)


@api_router.get("/pronostics")
async def get_pronostics(
    date: str | None = Query(
        default=None,
        description="Date in YYYY-MM-DD format. Defaults to today (Paris time).",
    ),
    if_none_match: str | None = Header(None, alias="If-None-Match"),
):
    date_to_use = date
    if date_to_use is None:
        today = datetime.now(ZoneInfo("Europe/Paris")).date()
        date_to_use = today.strftime("%Y-%m-%d")
    else:
        try:
            datetime.strptime(date_to_use, "%Y-%m-%d")
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid date format. Please use YYYY-MM-DD.",
            ) from e

    correlation_id = str(uuid.uuid4())
    log_extra = {"correlation_id": correlation_id, "date": date_to_use}
    logger.info(f"Fetching pronostics for date: {date_to_use} from Firestore", extra=log_extra)
    logger.debug(f"DEBUG: get_pronostics for date: {date_to_use}", extra=log_extra)

    try:
        race_documents = firestore_client.get_races_by_date_prefix(date_to_use)
        logger.debug(
            f"DEBUG: Fetched {len(race_documents)} raw race documents for {date_to_use}",
            extra=log_extra,
        )

        all_pronostics = []
        latest_update_time = None
        for doc in race_documents:
            analysis = doc.get("tickets_analysis")
            if analysis and analysis.get("tickets"):
                all_pronostics.append(
                    {
                        "rc": doc.get("rc", "N/A"),
                        "gpi_decision": analysis.get("gpi_decision", "N/A"),
                        "tickets": analysis.get("tickets", []),
                    }
                )

                # Track the latest update time
                last_analyzed_str = doc.get("last_analyzed_at")
                if last_analyzed_str:
                    try:
                        # Ensure timestamp is offset-aware for correct comparison
                        current_doc_time = datetime.fromisoformat(last_analyzed_str)
                        if latest_update_time is None or current_doc_time > latest_update_time:
                            latest_update_time = current_doc_time
                    except (ValueError, TypeError):
                        logger.warning(f"Could not parse last_analyzed_at: {last_analyzed_str}")

        final_last_updated = (
            latest_update_time
            if latest_update_time
            else datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
        )

        response_content = {
            "ok": True,
            "total_races": len(all_pronostics),
            "date": date_to_use,
            "last_updated": final_last_updated.isoformat().replace("+00:00", "Z"),
            "pronostics": all_pronostics,
        }

        # Generate ETag
        raw_etag = hashlib.sha1(json.dumps(response_content, sort_keys=True).encode("utf-8")).hexdigest()
        etag = f'"{raw_etag}"' # Enclose ETag in quotes

        # Check If-None-Match header
        if if_none_match:
            clean_if_none_match = if_none_match.strip().strip('"')
            if clean_if_none_match == raw_etag: # Compare raw etag to cleaned header value
                logger.debug(f"ETag match: {clean_if_none_match} == {raw_etag}. Returning 304 Not Modified.")
                return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})

        # Return response with ETag header
        return JSONResponse(content=response_content, headers={"ETag": etag})
    except Exception as e:
        logger.error("Error fetching pronostics from Firestore", exc_info=True, extra=log_extra)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch pronostics from Firestore.",
        ) from e


@api_router.get("/schedule/next")
async def get_next_scheduled_tasks():
    """Returns the next 10 scheduled tasks from the Cloud Tasks queue."""
    tasks = get_scheduled_tasks(
        project=config.PROJECT_ID,
        location=config.REGION,
        queue=config.QUEUE_ID,
        limit=10,
    )
    return {"ok": True, "tasks": tasks}


app.include_router(api_router)


@app.get("/ping")
async def ping():
    return {"status": "pong"}


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "hippique-orchestrator",
        "version": "2.1.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.post("/schedule", status_code=status.HTTP_202_ACCEPTED)
async def schedule_daily_plan(body: ScheduleRequest):
    correlation_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    log_extra = {
        "correlation_id": correlation_id,
        "trace_id": trace_id,
        "date": body.date,
        "mode": body.mode,
    }
    logger.info("Schedule request received", extra=log_extra)

    try:
        plan = await build_plan_async(body.date)
        if not plan:
            logger.warning("Empty plan generated", extra=log_extra)
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={"ok": False, "error": "No races found for this date"},
            )

        logger.info(f"Plan built: {len(plan)} races", extra=log_extra)

        scheduled = schedule_all_races(
            plan=plan,
            mode=body.mode,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )

        success_h30 = sum(1 for s in scheduled if s["phase"] == "H30" and s["ok"])
        success_h5 = sum(1 for s in scheduled if s["phase"] == "H5" and s["ok"])
        all_ok = all(s["ok"] for s in scheduled)

        logger.info(
            "Scheduling complete",
            extra={
                **log_extra,
                "success_h30": success_h30,
                "success_h5": success_h5,
            },
        )

        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "ok": all_ok,
                "date": body.date,
                "total_races": len(plan),
                "scheduled_h30": success_h30,
                "scheduled_h5": success_h5,
                "mode": body.mode,
                "correlation_id": correlation_id,
                "trace_id": trace_id,
            },
        )
    except Exception as e:
        logger.error(f"Schedule failed: {e}", exc_info=True, extra=log_extra)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"ok": False, "error": str(e)},
        )


@app.post("/run")
async def run_race_analysis(body: RunRequest):
    correlation_id = str(uuid.uuid4())
    trace_id = body.trace_id or correlation_id
    log_extra = {
        "correlation_id": correlation_id,
        "trace_id": trace_id,
        "course_url": body.course_url,
        "phase": body.phase,
    }
    logger.info("Run request received", extra=log_extra)

    try:
        result = run_course(
            course_url=body.course_url,
            phase=body.phase,
            date=body.date,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )
        result["correlation_id"] = correlation_id
        result["trace_id"] = trace_id

        status_code = (
            status.HTTP_200_OK if result.get("ok") else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(status_code=status_code, content=result)
    except Exception as e:
        logger.error(f"Run failed with exception: {e}", exc_info=True, extra=log_extra)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"ok": False, "error": str(e)},
        )


# ============================================
# Task Endpoints (for Cloud Tasks)
# ============================================


@app.post("/receive-trigger", status_code=status.HTTP_202_ACCEPTED)
async def receive_trigger(body: ScheduleRequest, background_tasks: BackgroundTasks):
    """
    Receives a trigger (likely from Cloud Scheduler) to start the daily bootstrap.
    This is a compatibility endpoint for a misconfigured scheduler.
    """
    correlation_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    logger.info(
        "Received trigger to start daily bootstrap",
        extra={
            "correlation_id": correlation_id,
            "trace_id": trace_id,
            "date": body.date,
        },
    )

    background_tasks.add_task(
        bootstrap_day_pipeline,
        date_str=body.date,
        correlation_id=correlation_id,
        trace_id=trace_id,
    )

    return {
        "ok": True,
        "message": f"Bootstrap for {body.date} initiated in background from trigger.",
    }


@app.post("/tasks/bootstrap-day", status_code=status.HTTP_202_ACCEPTED)
async def tasks_bootstrap_day(body: ScheduleRequest, background_tasks: BackgroundTasks):
    correlation_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    logger.info(
        "Bootstrap day task received",
        extra={
            "correlation_id": correlation_id,
            "trace_id": trace_id,
            "date": body.date,
        },
    )

    background_tasks.add_task(
        bootstrap_day_pipeline,
        date_str=body.date,
        correlation_id=correlation_id,
        trace_id=trace_id,
    )

    return {"ok": True, "message": f"Bootstrap for {body.date} initiated in background."}


@app.post("/tasks/run-phase", status_code=status.HTTP_200_OK)
async def tasks_run_phase(body: RunRequest):
    correlation_id = str(uuid.uuid4())
    trace_id = body.trace_id or correlation_id
    logger.info(
        f"Run phase task received for course: {body.course_url}",
        extra={"correlation_id": correlation_id, "trace_id": trace_id},
    )

    result = run_course(
        course_url=body.course_url,
        phase=body.phase,
        date=body.date,
        correlation_id=correlation_id,
        trace_id=trace_id,
    )

    return {
        "ok": result.get("ok", False),
        "phase": result.get("phase"),
        "artifacts": result.get("artifacts", []),
    }


# ============================================
# API & Debug Endpoints
# ============================================


@app.get("/debug/parse")
async def debug_parse(date: str = "2025-10-17"):
    result = await build_plan_async(date)
    return {
        "ok": True,
        "date": date,
        "count": len(result),
        "races": result[:3] if result else [],
    }


@app.get("/debug/config")
async def debug_config():
    """Returns the current application configuration."""
    config_dict = {k: str(v) for k, v in get_config().model_dump().items()}
    return {"ok": True, "config": config_dict}


@app.get("/debug/cloudtasks/ping")
async def debug_cloudtasks_ping(request: Request):
    """
    Pings the Cloud Tasks queue to verify connectivity and permissions.
    """

    # Use the correlation_id from the middleware
    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    log_extra = {"correlation_id": correlation_id}
    logger.info("Starting Cloud Tasks ping debug.", extra=log_extra)

    try:
        # 1. Log effective project and environment
        try:
            credentials, inferred_project = google.auth.default()
            logger.info(
                f"google.auth.default() inferred_project: {inferred_project}",
                extra=log_extra,
            )

            # Log service account email if available
            if hasattr(credentials, "service_account_email"):
                logger.info(
                    f"Service Account Email: {credentials.service_account_email}",
                    extra=log_extra,
                )
            else:
                logger.info(
                    "Service Account Email: Not available on credentials.",
                    extra=log_extra,
                )

        except (google.auth.exceptions.DefaultCredentialsError, AttributeError) as e:
            inferred_project = None
            logger.error(
                f"Could not determine project via google.auth.default(): {e}",
                extra=log_extra,
            )

        env_project = os.getenv("GOOGLE_CLOUD_PROJECT")
        logger.info(f"os.getenv('GOOGLE_CLOUD_PROJECT'): {env_project}", extra=log_extra)

        # 2. Get client and config
        client = tasks_v2.CloudTasksClient()
        task_config = get_config()
        project = task_config.PROJECT_ID
        location = task_config.REGION
        queue = task_config.QUEUE_ID

        logger.info(
            f"Using config: project={project}, location={location}, queue={queue}",
            extra=log_extra,
        )

        # 3. Construct queue path and call get_queue
        parent = client.queue_path(project, location, queue)
        logger.info(f"Attempting to get_queue with name: {parent}", extra=log_extra)

        try:
            queue_info = client.get_queue(name=parent)
            logger.info("Successfully got queue info.", extra=log_extra)
            return {
                "ok": True,
                "status": "Successfully pinged queue",
                "queue_name": queue_info.name,
                "queue_state": str(queue_info.state),
                "inferred_project": inferred_project,
                "env_project": env_project,
            }
        except Exception as e:
            # This is the critical part for debugging the 404
            logger.error(
                f"get_queue failed with exception: {e}",
                exc_info=True,
                extra=log_extra,
            )

            error_details = {"message": str(e)}
            if hasattr(e, "details"):
                error_details["details"] = e.details()
            if hasattr(e, "code"):
                error_details["code"] = e.code().name

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "ok": False,
                    "status": "Failed to get queue",
                    "error": error_details,
                    "queue_name_constructed": parent,
                    "inferred_project": inferred_project,
                    "env_project": env_project,
                },
            ) from e

    except Exception as e:
        logger.error(
            f"An unexpected error occurred in the ping endpoint: {e}",
            exc_info=True,
            extra=log_extra,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "ok": False,
                "error": "An unexpected error occurred in the ping endpoint.",
            },
        ) from e


@app.post("/debug/force-bootstrap/{date_str}", status_code=status.HTTP_200_OK)
async def debug_force_bootstrap(date_str: str):
    """
    Forces the daily bootstrap pipeline for a specific date, and returns the logs.
    """
    correlation_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id, "date": date_str}
    logger.warning(
        f"Forcing bootstrap pipeline for {date_str} via debug endpoint.",
        extra=log_extra,
    )

    firestore_client.unmark_day_as_planned(date_str)

    log_stream = StringIO()
    with contextlib.redirect_stdout(log_stream):
        try:
            plan_details = await bootstrap_day_pipeline(
                date_str=date_str,
                correlation_id=correlation_id,
                trace_id=trace_id,
            )
            logs = log_stream.getvalue()
            return {
                "ok": True,
                "message": f"Forced bootstrap for {date_str} completed.",
                "plan_details": plan_details,
                "logs": logs.splitlines(),
            }
        except Exception as e:
            logs = log_stream.getvalue()
            logger.error(f"Debug bootstrap failed: {e}", exc_info=True, extra=log_extra)
            # Get the traceback as a string
            import traceback
            exc_traceback = traceback.format_exc()
            return {
                "ok": False,
                "error": str(e),
                "traceback": exc_traceback.splitlines(),
                "logs": logs.splitlines(),
            }


@app.get("/debug/races/{race_doc_id}")
async def debug_get_race_document(race_doc_id: str):
    """
    Fetches a specific race document from the 'races' collection in Firestore.
    """
    correlation_id = str(uuid.uuid4())
    log_extra = {"correlation_id": correlation_id, "race_doc_id": race_doc_id}
    logger.info(
        f"Fetching race document: {race_doc_id} from Firestore via debug endpoint",
        extra=log_extra,
    )

    try:
        logger.debug(
            f"Calling firestore_client.get_race_document for {race_doc_id}",
            extra=log_extra,
        )
        doc = firestore_client.get_race_document("races", race_doc_id)
        logger.debug(f"firestore_client.get_race_document returned: {doc}", extra=log_extra)
        if doc:
            return {"ok": True, "race_doc_id": race_doc_id, "data": doc}
        # This will now correctly raise a 404 if the document is not found
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Race document '{race_doc_id}' not found.",
        )
    except Exception as e:
        logger.error(
            f"An unexpected error occurred in debug_get_race_document: {e}",
            exc_info=True,
            extra=log_extra,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred while fetching race document {race_doc_id}.",
        ) from e


# ============================================
# Core Logic (used by startup and endpoints)
# ============================================


async def bootstrap_day_pipeline(
    date_str: str, correlation_id: str, trace_id: str
) -> dict[str, Any] | None:
    """Builds the plan for the day and schedules all races."""
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id, "date": date_str}
    logger.info(f"Starting bootstrap pipeline for {date_str}", extra=log_extra)
    plan = await build_plan_async(date_str)
    if not plan:
        logger.warning(f"No plan built for {date_str}. Aborting bootstrap.", extra=log_extra)
        return None

    logger.info(f"Plan built with {len(plan)} races. Now scheduling tasks.", extra=log_extra)
    logger.info(
        f"DEBUG_SERVICE: About to call schedule_all_races with {len(plan)} races.",
        extra=log_extra,
    )
    print(f"DEBUG_PRINT_SERVICE: Plan before scheduling: {plan}")

    try:
        scheduled_tasks_results = schedule_all_races(
            plan=plan,
            mode="tasks",
            correlation_id=correlation_id,
            trace_id=trace_id,
        )
    except Exception as e:
        logger.error(f"Failed to schedule all races: {e}", exc_info=True, extra=log_extra)
        scheduled_tasks_results = []  # Ensure it's still iterable for subsequent logic

    # Mark the day as planned ONLY if scheduling was successful for at least one race
    if plan and any(s["ok"] for s in scheduled_tasks_results):
        firestore_client.mark_day_as_planned(
            date_str,
            {
                "created_at": datetime.now(time_utils.get_tz()).isoformat(),
                "races_count": len(plan),
                "correlation_id": correlation_id,
            },
        )
        logger.info(
            f"Successfully marked {date_str} as planned in Firestore.",
            extra=log_extra,
        )
    else:
        logger.warning(
            f"No races successfully scheduled for {date_str}. Not marking as planned.",
            extra=log_extra,
        )

    return {"races_count": len(plan), "races": plan}


async def run_bootstrap_if_needed():
    """
    Checks if the daily planning has been done and runs it if not.
    This provides resilience against failed scheduler triggers.
    """
    await asyncio.sleep(10)  # Wait a bit for other services to be ready if needed

    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    today_str = today.strftime("%Y-%m-%d")

    correlation_id = str(uuid.uuid4())
    log_extra = {
        "correlation_id": correlation_id,
        "trace_id": correlation_id,
        "date": today_str,
    }

    logger.info("Startup check: Verifying if daily planning is needed.", extra=log_extra)

    if firestore_client.is_day_planned(today_str):
        logger.info(
            f"Daily planning for {today_str} already completed. Startup check passed.",
            extra=log_extra,
        )
        return

    logger.warning(
        f"Daily planning for {today_str} not found. Starting bootstrap process now.",
        extra=log_extra,
    )

    try:
        plan_details = await bootstrap_day_pipeline(
            date_str=today_str,
            correlation_id=correlation_id,
            trace_id=correlation_id,
        )
        if plan_details:
            # Mark as planned is now handled inside bootstrap_day_pipeline
            logger.info(
                f"Successfully completed bootstrap for {today_str} on startup.",
                extra=log_extra,
            )
    except Exception:
        logger.error(
            f"Startup bootstrap process for {today_str} failed.",
            exc_info=True,
            extra=log_extra,
        )


# ============================================
# Startup/Shutdown Events
# ============================================


@app.on_event("startup")
async def startup_event():
    logger.info(
        "Service starting",
        extra={"version": "2.1.0", "project_id": config.PROJECT_ID},
    )
    asyncio.create_task(run_bootstrap_if_needed())


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Service shutting down")
