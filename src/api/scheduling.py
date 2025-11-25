"""
API endpoints for scheduling and running analysis tasks.
"""
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException
from google.cloud import tasks_v2
from google.protobuf import duration_pb2, timestamp_pb2
from pydantic import BaseModel

from config.env_utils import get_env_variable
from hippique_orchestrator.plan import get_todays_races
from hippique_orchestrator.runner import run_course_analysis

router = APIRouter(prefix="/tasks", tags=["Scheduling"])

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Pydantic Models ---
class SnapshotTask(BaseModel):
    date: str | None = None
    meeting_urls: list[str] = []

class RunPhaseTask(BaseModel):
    phase: str
    course_id: str  # e.g., "R1C1"

class BootstrapTask(BaseModel):
    date: str | None = None

# --- Cloud Tasks Client ---
try:
    tasks_client = tasks_v2.CloudTasksClient()
    PROJECT_ID = get_env_variable("GCP_PROJECT_ID")
    REGION = get_env_variable("GCP_REGION")
    SERVICE_URL = get_env_variable("CLOUD_RUN_SERVICE_URL")
    SERVICE_ACCOUNT_EMAIL = get_env_variable("CLOUD_TASKS_INVOKER_SA")
    QUEUE_NAME = "hippique-analysis-queue"
    parent = tasks_client.queue_path(PROJECT_ID, REGION, QUEUE_NAME)
except Exception as e:
    logger.warning(f"Could not initialize Google Cloud Tasks client: {e}")
    tasks_client = None
    parent = None

# --- Helper Functions ---
def _create_cloud_task(course_id: str, phase: str, schedule_time: datetime):
    """Creates a Cloud Task to run a specific analysis phase for a course."""
    if not tasks_client or not parent:
        logger.error("Cloud Tasks client not initialized. Cannot create task.")
        raise HTTPException(status_code=500, detail="Cloud Tasks service is not configured.")

    # Convert schedule_time to Timestamp protobuf
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(schedule_time)

    # Construct the task payload
    payload = {"phase": phase, "course_id": course_id}
    
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{SERVICE_URL}/tasks/run-phase",
            "headers": {"Content-type": "application/json"},
            "body": str(payload).encode(),
            "oidc_token": {"service_account_email": SERVICE_ACCOUNT_EMAIL},
        },
        "schedule_time": timestamp,
    }

    try:
        request = tasks_v2.CreateTaskRequest(parent=parent, task=task)
        created_task = tasks_client.create_task(request=request)
        logger.info(f"Created task {created_task.name} for {course_id} phase {phase} at {schedule_time}")
        return created_task
    except Exception as e:
        logger.error(f"Failed to create task for {course_id} phase {phase}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create Cloud Task: {e}")


# --- API Endpoints ---

@router.post("/snapshot-9h")
async def snapshot_9h(task: SnapshotTask, background_tasks: BackgroundTasks):
    """
    Triggers the H9 snapshot for all French races of the day.
    This is intended to be called by Cloud Scheduler at 9 AM.
    """
    logger.info("Received request for H9 snapshot.")
    # For now, we simulate the snapshot by running an H30 analysis with a specific label.
    # In a real scenario, this would call a dedicated snapshot script.
    
    races = get_todays_races() # This function needs to be implemented to fetch daily races
    if not races:
        logger.warning("No races found for today.")
        return {"status": "no_races_found"}

    for race in races:
        # We use the H30 phase as a proxy for a snapshot
        background_tasks.add_task(run_course_analysis, race["id"], "H9")
        
    logger.info(f"Scheduled H9 snapshot for {len(races)} races.")
    return {"status": "H9 snapshot tasks scheduled", "races_count": len(races)}


@router.post("/run-phase")
async def run_phase(task: RunPhaseTask, background_tasks: BackgroundTasks):
    """
    Runs a specific analysis phase (H30, H5) for a given course.
    This is intended to be called by Cloud Tasks.
    """
    logger.info(f"Received request to run phase {task.phase} for course {task.course_id}")
    if task.phase not in ["H30", "H5", "H9"]:
        raise HTTPException(status_code=400, detail="Invalid phase. Must be H30, H5, or H9.")

    background_tasks.add_task(run_course_analysis, task.course_id, task.phase)
    
    return {"status": f"Task for phase {task.phase} on course {task.course_id} accepted."}


@router.post("/bootstrap-day")
async def bootstrap_day(task: BootstrapTask):
    """
    Bootstraps the analysis for the entire day by creating Cloud Tasks for each race.
    This is intended to be called by Cloud Scheduler early in the day.
    """
    logger.info("Received request to bootstrap day's analysis.")
    
    races = get_todays_races()
    if not races:
        logger.warning("No races found for today. Cannot bootstrap.")
        raise HTTPException(status_code=404, detail="No races found for today.")

    tasks_created = []
    for race in races:
        race_id = race["id"]
        race_time = race["start_time"] # Assuming start_time is a datetime object

        # Calculate H-30 and H-5 timestamps
        h30_time = race_time - timedelta(minutes=30)
        h5_time = race_time - timedelta(minutes=5)

        # Create Cloud Tasks for H-30 and H-5 phases
        try:
            task_h30 = _create_cloud_task(race_id, "H30", h30_time)
            tasks_created.append(task_h30.name)
            task_h5 = _create_cloud_task(race_id, "H5", h5_time)
            tasks_created.append(task_h5.name)
        except HTTPException as e:
            # Log the error and continue with other races
            logger.error(f"HTTPException while creating tasks for {race_id}: {e.detail}")
            continue # Or handle more gracefully

    logger.info(f"Successfully bootstrapped day. Created {len(tasks_created)} tasks.")
    return {"status": "bootstrap_successful", "tasks_created": len(tasks_created), "task_names": tasks_created}
