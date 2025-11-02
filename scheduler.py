"""
src/scheduler.py - Programmation des exécutions H-30 et H-5 via Cloud Tasks
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from google.api_core import exceptions as gcp_exceptions
from google.cloud import tasks_v2

from app_config import get_config
from logging_utils import get_logger
from time_utils import compute_snapshot_time, format_rfc3339, is_past

logger = get_logger(__name__)
config = get_config()


def _sanitize_task_name(name: str) -> str:
    """
    Normalise un nom de tâche selon RFC-1035.
    
    Règles :
    - Lowercase
    - Commence par une lettre
    - Max 500 chars
    - Caractères autorisés : [a-z0-9-]
    """
    name = name.lower()
    name = re.sub(r"[^a-z0-9-]", "-", name)
    name = re.sub(r"-+", "-", name)  # Collapser les tirets multiples
    name = name.strip("-")
    
    # Assurer que ça commence par une lettre
    if name and not name[0].isalpha():
        name = "task-" + name
    
    return name[:500]  # Limite GCP


def _generate_task_name(date: str, r_label: str, c_label: str, phase: str) -> str:
    """
    Génère un nom déterministe pour une tâche.
    
    Format : run-YYYYMMDD-r{R}c{C}-{phase}
    Exemple : run-20251015-r1c3-h30
    """
    date_compact = date.replace("-", "")
    r_num = r_label.replace("R", "").replace("r", "")
    c_num = c_label.replace("C", "").replace("c", "")
    phase_clean = phase.lower().replace("-", "")
    
    name = f"run-{date_compact}-r{r_num}c{c_num}-{phase_clean}"
    return _sanitize_task_name(name)


def enqueue_run_task(
    course_url: str,
    phase: str,
    date: str,
    race_time_local: str,
    r_label: str,
    c_label: str,
) -> Optional[str]:
    """
    Crée une tâche Cloud Tasks pour exécuter /run à l'heure snapshot.
    
    Args:
        course_url: URL ZEturf de la course
        phase: "H30" ou "H5"
        date: YYYY-MM-DD
        race_time_local: HH:MM (heure locale de départ)
        r_label: R1, R2, etc.
        c_label: C1, C2, etc.
        
    Returns:
        Nom de la tâche créée ou None si erreur
    """
    # Calculer l'heure de snapshot
    offset = -30 if phase.upper() in ("H30", "H-30") else -5
    snapshot_local, snapshot_utc = compute_snapshot_time(date, race_time_local, offset)
    
    # Vérifier que ce n'est pas dans le passé
    if is_past(snapshot_utc):
        logger.warning(
            f"Snapshot time {snapshot_utc.isoformat()} is in the past, skipping",
            r_label=r_label,
            c_label=c_label,
            phase=phase
        )
        return None
    
    # Générer nom de tâche déterministe
    task_name = _generate_task_name(date, r_label, c_label, phase)
    task_path = f"{config.queue_path}/tasks/{task_name}"
    
    # Vérifier si la tâche existe déjà (idempotence)
    client = tasks_v2.CloudTasksClient()
    try:
        existing = client.get_task(name=task_path)
        logger.info(
            f"Task {task_name} already exists, skipping",
            task_name=task_name,
            state=existing.state_
        )
        return task_name
    except gcp_exceptions.NotFound:
        pass  # OK, on crée
    
    # Préparer payload
    payload = {
        "course_url": course_url,
        "phase": phase.upper().replace("-", ""),
        "date": date,
    }
    
    # Construire la tâche
    task = {
        "name": task_path,
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{config.cloud_run_url}/run",
            "headers": {
                "Content-Type": "application/json",
            },
            "body": json.dumps(payload).encode(),
        },
        "schedule_time": format_rfc3339(snapshot_utc),
    }
    
    # Ajouter OIDC si requis
    if config.require_auth:
        task["http_request"]["oidc_token"] = {
            "service_account_email": config.service_account_email,
            "audience": config.cloud_run_url,
        }
    
    # Créer la tâche
    try:
        created_task = client.create_task(
            parent=config.queue_path,
            task=task
        )
        logger.info(
            f"Created task {task_name} scheduled at {snapshot_local.strftime('%Y-%m-%d %H:%M')} Paris",
            task_name=task_name,
            schedule_time_utc=snapshot_utc.isoformat(),
            schedule_time_local=snapshot_local.isoformat(),
            r_label=r_label,
            c_label=c_label,
            phase=phase
        )
        return task_name
    except gcp_exceptions.AlreadyExists:
        logger.info(f"Task {task_name} already exists (race condition), continuing")
        return task_name
    except Exception as e:
        logger.error(
            f"Failed to create task {task_name}: {e}",
            exc_info=e,
            task_name=task_name
        )
        return None


def schedule_race_tasks(race: Dict[str, Any]) -> Dict[str, Any]:
    """
    Programme les tâches H-30 et H-5 pour une course.
    
    Args:
        race: Dict avec keys: date, r_label, c_label, time_local, course_url
        
    Returns:
        Dict avec statut de programmation {h30_task, h5_task, status}
    """
    date = race["date"]
    r_label = race["r_label"]
    c_label = race["c_label"]
    time_local = race["time_local"]
    course_url = race["course_url"]
    
    logger.info(
        f"Scheduling {r_label}{c_label} at {time_local}",
        r_label=r_label,
        c_label=c_label,
        time_local=time_local
    )
    
    # Programmer H-30
    h30_task = enqueue_run_task(
        course_url=course_url,
        phase="H30",
        date=date,
        race_time_local=time_local,
        r_label=r_label,
        c_label=c_label,
    )
    
    # Programmer H-5
    h5_task = enqueue_run_task(
        course_url=course_url,
        phase="H5",
        date=date,
        race_time_local=time_local,
        r_label=r_label,
        c_label=c_label,
    )
    
    status = "ok" if (h30_task and h5_task) else "partial" if (h30_task or h5_task) else "failed"
    
    return {
        "r_label": r_label,
        "c_label": c_label,
        "time_local": time_local,
        "h30_task": h30_task,
        "h5_task": h5_task,
        "status": status,
    }


def schedule_all_races(plan: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Programme toutes les courses du plan.
    
    Args:
        plan: Liste de courses [{date, r_label, c_label, time_local, course_url, ...}]
        
    Returns:
        Résumé {total, scheduled, failed, tasks: [...]}
    """
    results = []
    scheduled = 0
    failed = 0
    
    for race in plan:
        result = schedule_race_tasks(race)
        results.append(result)
        
        if result["status"] == "ok":
            scheduled += 1
        elif result["status"] == "failed":
            failed += 1
    
    summary = {
        "total": len(plan),
        "scheduled": scheduled,
        "partial": len([r for r in results if r["status"] == "partial"]),
        "failed": failed,
        "tasks": results,
    }
    
    logger.info(
        f"Scheduling complete: {scheduled}/{len(plan)} races fully scheduled",
        **summary
    )
    
    return summary


# ============================================================================
# FALLBACK : Cloud Scheduler (si mode="scheduler")
# ============================================================================

def create_scheduler_job_fallback(
    job_name: str,
    schedule_time: datetime,
    payload: Dict[str, Any],
) -> bool:
    """
    Fallback : crée un job Cloud Scheduler one-shot (non recommandé).
    
    Note : Cloud Scheduler ne supporte pas vraiment les jobs "one-shot".
    Cette fonction est un exemple d'implémentation pour référence.
    Utiliser Cloud Tasks (recommandé).
    """
    logger.warning(
        "Using Cloud Scheduler fallback (not recommended). "
        "Prefer Cloud Tasks for one-shot executions."
    )
    
    # TODO: Implémenter avec google-cloud-scheduler si vraiment nécessaire
    # Nécessite de convertir schedule_time en cron expression
    # et de créer un job qui s'auto-détruit après exécution
    
    logger.error("Cloud Scheduler fallback not implemented")
    return False