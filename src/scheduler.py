"""Scheduling utilities for Cloud Tasks and Cloud Scheduler."""
import logging
import json
import hashlib
from datetime import datetime
from typing import Dict, Any

from google.cloud import tasks_v2
from google.cloud import scheduler_v1
from google.protobuf import timestamp_pb2

from config import Config
from time_utils import format_rfc3339, paris_to_utc

logger = logging.getLogger(__name__)


class CloudTasksScheduler:
    """Schedule tasks using Cloud Tasks."""
    
    def __init__(self, config: Config):
        self.config = config
        self.client = tasks_v2.CloudTasksClient()
        self.queue_path = self.client.queue_path(
            config.PROJECT_ID,
            config.QUEUE_LOCATION,
            config.QUEUE_ID
        )
    
    def schedule_task(
        self,
        run_url: str,
        race_id: str,
        phase: str,
        when_local: datetime,
        payload: Dict[str, Any],
        date: str
    ) -> Dict[str, str]:
        """
        Schedule a task to run at when_local (Europe/Paris).
        
        Returns task info dict.
        """
        # Convert to UTC for Cloud Tasks
        when_utc = paris_to_utc(when_local)
        
        # Create deterministic task name (RFC-1035 compliant)
        task_name_base = f"run-{date.replace('-', '')}-{race_id.lower()}-{phase.lower()}"
        task_name = self._make_task_name(task_name_base)
        task_path = f"{self.queue_path}/tasks/{task_name}"
        
        # Check if task already exists (idempotence)
        try:
            existing = self.client.get_task(name=task_path)
            logger.info(f"Task {task_name} already exists, skipping")
            return {
                "name": task_name,
                "status": "existing",
                "schedule_time": when_utc.isoformat()
            }
        except Exception:
            pass  # Task doesn't exist, create it
        
        # Create task
        task = {
            "name": task_path,
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": run_url,
                "headers": {
                    "Content-Type": "application/json"
                },
                "body": json.dumps(payload).encode(),
            },
            "schedule_time": timestamp_pb2.Timestamp(
                seconds=int(when_utc.timestamp())
            ),
        }
        
        # Add OIDC token if service account configured
        if self.config.SERVICE_ACCOUNT:
            task["http_request"]["oidc_token"] = {
                "service_account_email": self.config.SERVICE_ACCOUNT,
                "audience": run_url
            }
        
        try:
            response = self.client.create_task(
                parent=self.queue_path,
                task=task
            )
            logger.info(f"Created task {task_name} for {when_utc.isoformat()}")
            return {
                "name": task_name,
                "status": "created",
                "schedule_time": when_utc.isoformat(),
                "task_path": response.name
            }
        except Exception as e:
            logger.error(f"Failed to create task {task_name}: {e}")
            raise
    
    def _make_task_name(self, base: str) -> str:
        """Create RFC-1035 compliant task name."""
        # Hash to ensure uniqueness and compliance
        h = hashlib.md5(base.encode()).hexdigest()[:8]
        safe_base = base.replace("_", "-").lower()
        # Limit to 63 chars
        return f"{safe_base[:50]}-{h}"


class CloudSchedulerFallback:
    """Fallback scheduler using Cloud Scheduler (for one-shot jobs)."""
    
    def __init__(self, config: Config):
        self.config = config
        self.client = scheduler_v1.CloudSchedulerClient()
        self.parent = f"projects/{config.PROJECT_ID}/locations/{config.REGION}"
    
    def schedule_task(
        self,
        run_url: str,
        race_id: str,
        phase: str,
        when_local: datetime,
        payload: Dict[str, Any],
        date: str
    ) -> Dict[str, str]:
        """
        Create one-shot Cloud Scheduler job.
        
        Note: Cloud Scheduler doesn't support one-shot jobs natively.
        This creates a job that runs once then must be manually deleted.
        """
        job_name = f"run-{date.replace('-', '')}-{race_id.lower()}-{phase.lower()}"
        job_path = f"{self.parent}/jobs/{job_name}"
        
        # Check if exists
        try:
            existing = self.client.get_job(name=job_path)
            logger.info(f"Scheduler job {job_name} already exists")
            return {
                "name": job_name,
                "status": "existing",
                "schedule_time": when_local.isoformat()
            }
        except Exception:
            pass
        
        # Convert to cron schedule (run once at specific time)
        # Format: minute hour day month dayofweek
        cron = f"{when_local.minute} {when_local.hour} {when_local.day} {when_local.month} *"
        
        job = {
            "name": job_path,
            "schedule": cron,
            "time_zone": "Europe/Paris",
            "http_target": {
                "uri": run_url,
                "http_method": scheduler_v1.HttpMethod.POST,
                "headers": {
                    "Content-Type": "application/json"
                },
                "body": json.dumps(payload).encode(),
            },
        }
        
        # Add OIDC if configured
        if self.config.SERVICE_ACCOUNT:
            job["http_target"]["oidc_token"] = {
                "service_account_email": self.config.SERVICE_ACCOUNT,
                "audience": run_url
            }
        
        try:
            response = self.client.create_job(
                parent=self.parent,
                job=job
            )
            logger.info(f"Created scheduler job {job_name}")
            return {
                "name": job_name,
                "status": "created",
                "schedule_time": when_local.isoformat(),
                "cron": cron
            }
        except Exception as e:
            logger.error(f"Failed to create job {job_name}: {e}")
            raise
