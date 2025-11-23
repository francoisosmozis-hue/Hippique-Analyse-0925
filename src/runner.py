"""
src/runner.py - Orchestrateur des Modules GPI v5.1

Exécute les modules Python existants via subprocess:
  - analyse_courses_du_jour_enrichie.py (principal)
  - p_finale_export.py
  - simulate_ev.py
  - pipeline_run.py
  - update_excel_with_results.py (post-course)
  - get_arrivee_geny.py (post-course)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from modules.tickets_store import render_ticket_html, save_ticket_html
from src.gcs import upload_artifacts
from src.logging_utils import get_logger

# from .config.config import config

logger = get_logger(__name__)

# Chemins des modules GPI
SRC_DIR = Path(__file__).parent
MODULES_DIR = Path(__file__).parent.parent / "modules"
DATA_DIR = Path(__file__).parent.parent / "data"

# Créer DATA_DIR si nécessaire
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ============================================
# Helpers
# ============================================

def _extract_rc_from_url(course_url: str) -> tuple[str, str]:
    """
    Extrait R et C depuis une URL ZEturf (pour logging uniquement).
    """
    match = re.search(r"/R(\d+)C(\d+)[-_]", course_url)
    if not match:
        raise ValueError(f"Cannot extract R/C from URL: {course_url}")

    r_num, c_num = match.groups()
    return f"R{int(r_num)}", f"C{int(c_num)}"

def _run_subprocess(
    cmd: list[str],
    timeout: int = 600,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """
    Exécute une commande subprocess et capture stdout/stderr.
    """
    logger.debug(f"Running: {' '.join(cmd)}", command=cmd)

    result = subprocess.run(
        cmd,
        check=False, capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd or Path.cwd(),
        env=env or os.environ.copy(),
    )
    return result.returncode, result.stdout, result.stderr

def _collect_artifacts(rc_dir: Path) -> list[str]:
    """
    Collecte tous les artefacts générés dans le répertoire de la course.
    """
    if not rc_dir.exists():
        return []

    artifacts = []
    for file_path in rc_dir.rglob("*"):
        if file_path.is_file():
            artifacts.append(str(file_path.relative_to(Path.cwd())))

    return sorted(artifacts)

def run_course(
    course_url: str,
    phase: str,
    date: str,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """
    Exécute l'analyse complète d'une course avec les modules GPI v5.1.
    """
    phase_clean = phase.upper().replace("-", "")
    try:
        reunion, course = _extract_rc_from_url(course_url)
    except ValueError as e:
        logger.error(str(e))
        return {"ok": False, "phase": phase_clean, "returncode": -1, "error": str(e), "artifacts": []}

    logger.info("Starting course analysis", correlation_id=correlation_id, reunion=reunion, course=course, phase=phase_clean, date=date, course_url=course_url)

    rc_dir = DATA_DIR / f"{reunion}{course}"
    rc_dir.mkdir(parents=True, exist_ok=True)

    # Préparer l'environnement pour les sous-processus
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd())
    # Injecter explicitement la configuration pour les scripts enfants
    if config.gcs_bucket:
        env["GCS_BUCKET"] = config.gcs_bucket
    if config.project_id:
        env["PROJECT_ID"] = config.project_id # Utilise PROJECT_ID
    if config.service_account_email:
        env["SERVICE_ACCOUNT_EMAIL"] = config.service_account_email # Utilise SERVICE_ACCOUNT_EMAIL


    if phase_clean == "H30":
        logger.info("Step 1/1: Snapshot H30", correlation_id=correlation_id)
        cmd_analyse = [sys.executable, str(MODULES_DIR / "analyse_courses_du_jour_enrichie.py"), "--reunion", reunion, "--course", course, "--phase", "H30", "--data-dir", str(DATA_DIR), "--course-url", course_url]
        rc, stdout, stderr = _run_subprocess(cmd_analyse, timeout=config.timeout_seconds, env=env)
        if rc != 0:
            logger.error("H30 analysis failed", correlation_id=correlation_id, returncode=rc, stderr=stderr)
            return {"ok": False, "phase": "H30", "returncode": rc, "stdout": stdout, "stderr": stderr, "artifacts": _collect_artifacts(rc_dir)}
        
        artifacts = _collect_artifacts(rc_dir)
        if config.gcs_bucket:
            upload_artifacts(rc_dir, artifacts)
        logger.info("H30 analysis complete", correlation_id=correlation_id)
        return {"ok": True, "phase": "H30", "returncode": 0, "stdout": stdout, "artifacts": artifacts}

    logger.info("Starting H5 pipeline", correlation_id=correlation_id)
    
    logger.info("Step 1/6: analyse_courses_du_jour_enrichie H5", correlation_id=correlation_id)
    cmd_analyse = [sys.executable, str(MODULES_DIR / "analyse_courses_du_jour_enrichie.py"), "--reunion", reunion, "--course", course, "--phase", "H5", "--data-dir", str(DATA_DIR), "--course-url", course_url]
    rc, stdout, stderr = _run_subprocess(cmd_analyse, timeout=config.timeout_seconds, env=env)
    if rc != 0:
        logger.error("analyse_courses_du_jour_enrichie failed", correlation_id=correlation_id, returncode=rc, stderr=stderr)
        return {"ok": False, "phase": "H5", "returncode": rc, "stdout": stdout, "stderr": stderr, "artifacts": _collect_artifacts(rc_dir)}

    logger.info("Step 2/6: p_finale_export", correlation_id=correlation_id)
    cmd_p_finale = [sys.executable, str(MODULES_DIR / "p_finale_export.py"), "--rc-dir", str(rc_dir)]
    rc, stdout, stderr = _run_subprocess(cmd_p_finale, timeout=180, env=env)
    if rc != 0:
        logger.error("p_finale_export failed", correlation_id=correlation_id, returncode=rc, stderr=stderr)
        return {"ok": False, "phase": "H5", "returncode": rc, "stdout": stdout, "stderr": stderr, "artifacts": _collect_artifacts(rc_dir)}

    logger.info("Step 3/6: simulate_ev", correlation_id=correlation_id)
    cmd_simulate = [sys.executable, str(MODULES_DIR / "simulate_ev.py"), "--p-finale", str(rc_dir / "p_finale.json"), "--output", str(rc_dir / "ev_simulation.json")]
    rc, stdout, stderr = _run_subprocess(cmd_simulate, timeout=180, env=env)
    if rc != 0:
        logger.warning("simulate_ev failed (non-critical)", correlation_id=correlation_id, returncode=rc)

    logger.info("Step 4/6: pipeline_run (ticket generation)", correlation_id=correlation_id)
    cmd_pipeline = [sys.executable, str(SRC_DIR / "pipeline_run.py"), f"--reunion={reunion}", f"--course={course}", f"--budget={config.budget_per_race}"]
    rc, stdout, stderr = _run_subprocess(cmd_pipeline, timeout=300, env=env)
    if rc != 0:
        logger.error("pipeline_run failed", correlation_id=correlation_id, returncode=rc, stderr=stderr)
        return {"ok": False, "phase": "H5", "returncode": rc, "stdout": stdout, "stderr": stderr, "artifacts": _collect_artifacts(rc_dir)}

    logger.info("Step 5/6: Rendering and saving HTML ticket", correlation_id=correlation_id)
    try:
        analysis_path = rc_dir / "analysis_H5.json"
        if analysis_path.exists():
            with open(analysis_path) as f:
                analysis_result = json.load(f)
            
            tickets_list = analysis_result.get("tickets")
            if tickets_list:
                tickets_json_path = rc_dir / "tickets.json"
                with open(tickets_json_path, "w", encoding="utf-8") as f_json:
                    json.dump(tickets_list, f_json, ensure_ascii=False, indent=2)
                logger.info(f"tickets.json saved to {tickets_json_path}", correlation_id=correlation_id)
            
            if not analysis_result.get("abstain") and analysis_result.get("tickets"):
                html_content = render_ticket_html(payload=analysis_result, reunion=reunion, course=course, phase=phase_clean, budget=config.budget_per_race)
                save_ticket_html(html_content, date_str=date, rxcy=rc_dir.name)
                logger.info(f"HTML ticket saved for {rc_dir.name}", correlation_id=correlation_id)
        else:
            logger.warning("analysis_H5.json not found, cannot generate HTML ticket.", correlation_id=correlation_id)
    except Exception as e:
        logger.error(f"Failed to generate or save HTML ticket: {e}", correlation_id=correlation_id, exc_info=True)

    logger.info("Step 6/6: Collecting artifacts", correlation_id=correlation_id)
    artifacts = _collect_artifacts(rc_dir)
    if config.gcs_bucket:
        upload_artifacts(rc_dir, artifacts)

    logger.info("H5 pipeline complete", correlation_id=correlation_id, artifacts_count=len(artifacts))
    return {"ok": True, "phase": "H5", "returncode": 0, "stdout": stdout, "artifacts": artifacts}

def update_with_results(
    course_url: str,
    date: str,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """
    Met à jour l'Excel avec les résultats officiels (post-course).
    """
    try:
        reunion, course = _extract_rc_from_url(course_url)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    logger.info("Updating with results", correlation_id=correlation_id, reunion=reunion, course=course)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path.cwd())

    cmd_arrivee = [sys.executable, str(MODULES_DIR / "get_arrivee_geny.py"), "--course-url", course_url, "--date", date]
    rc, stdout, stderr = _run_subprocess(cmd_arrivee, timeout=60, env=env)
    if rc != 0:
        logger.error(f"get_arrivee_geny failed: {stderr}")
        return {"ok": False, "returncode": rc, "message": "Failed to fetch results"}

    cmd_update = [sys.executable, str(MODULES_DIR / "update_excel_with_results.py"), "--reunion", reunion, "--course", course, "--date", date]
    rc, stdout, stderr = _run_subprocess(cmd_update, timeout=120, env=env)
    if rc != 0:
        logger.error(f"update_excel_with_results failed: {stderr}")
        return {"ok": False, "returncode": rc, "message": "Failed to update Excel"}

    logger.info("Results updated successfully", correlation_id=correlation_id)
    return {"ok": True, "returncode": 0, "message": "Results updated successfully"}
