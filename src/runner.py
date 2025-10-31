"""
src/runner.py - Orchestrateur des Modules GPI v5.1

Exécute les modules Python existants via subprocess:
  - analyse_courses_du_jour_enrichie.py (principal)
  - p_finale_export.py
  - simulate_ev.py
  - pipeline_run.py
  - update_excel_with_results.py (post-course)
  - get_arrivee_geny.py (post-course)

Correction bug #3: Mode simplifié avec --course-url directement
(pas besoin de --reunion --course --course-id)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from google.cloud import storage

<<<<<<< HEAD
from config import get_config
from logging_utils import get_logger

logger = get_logger(__name__)
config = get_config()

# Chemins des modules GPI
=======
from src.config import Config
from src.logging_utils import get_logger
from modules.tickets_store import render_ticket_html, save_ticket_html

logger = get_logger(__name__)

# Chemins des modules GPI
SRC_DIR = Path(__file__).parent
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
MODULES_DIR = Path(__file__).parent.parent / "modules"
DATA_DIR = Path(__file__).parent.parent / "data"

# Créer DATA_DIR si nécessaire
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ============================================
# Helpers
# ============================================

def _extract_rc_from_url(course_url: str) -> Tuple[str, str]:
    """
    Extrait R et C depuis une URL ZEturf (pour logging uniquement).
    
    Args:
        course_url: https://www.zeturf.fr/fr/course/2025-10-16/R1C3-...
        
    Returns:
        ("R1", "C3")
        
    Raises:
        ValueError si format incorrect
    """
    match = re.search(r"/R(\d+)C(\d+)[-_]", course_url)
    if not match:
        raise ValueError(f"Cannot extract R/C from URL: {course_url}")
    
    r_num, c_num = match.groups()
    return f"R{int(r_num)}", f"C{int(c_num)}"

def _run_subprocess(
    cmd: List[str],
    timeout: int = 600,
    cwd: Optional[Path] = None,
) -> Tuple[int, str, str]:
    """
    Exécute une commande subprocess et capture stdout/stderr.
    
    Args:
        cmd: Liste de commande et arguments
        timeout: Timeout en secondes
        cwd: Working directory
        
    Returns:
        (returncode, stdout, stderr)
    """
    logger.debug(f"Running: {' '.join(cmd)}", command=cmd)
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd or Path.cwd(),
            env=os.environ.copy(),
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as e:
        logger.error(f"Command timed out after {timeout}s: {' '.join(cmd)}")
        return -1, "", f"Timeout after {timeout}s"
    except Exception as e:
        logger.error(f"Command failed: {e}", exc_info=e)
        return -1, "", str(e)

def _collect_artifacts(rc_dir: Path) -> List[str]:
    """
    Collecte tous les artefacts générés dans le répertoire de la course.
    
    Args:
        rc_dir: Répertoire data/R1C3/
        
    Returns:
        Liste de chemins relatifs
    """
    if not rc_dir.exists():
        return []
    
    artifacts = []
    for file_path in rc_dir.rglob("*"):
        if file_path.is_file():
            artifacts.append(str(file_path.relative_to(Path.cwd())))
    
    return sorted(artifacts)

def _upload_artifacts_to_gcs(rc_dir: Path, artifacts: List[str]) -> None:
    """
    Upload les artefacts vers GCS (si configuré).
    
    Args:
        rc_dir: Répertoire data/R1C3/
        artifacts: Liste de chemins d'artefacts
    """
    if not config.gcs_bucket:
        return
    
    try:
        client = storage.Client()
        bucket = client.bucket(config.gcs_bucket)
        
        for artifact_path in artifacts:
            local_file = Path(artifact_path)
            if not local_file.exists():
                continue
            
            # GCS path: {prefix}/YYYY-MM-DD/R1C3/filename
            gcs_path = f"{config.gcs_prefix}/{local_file.parent.name}/{local_file.name}"
            
            blob = bucket.blob(gcs_path)
            blob.upload_from_filename(str(local_file))
            
            logger.debug(f"Uploaded {artifact_path} → gs://{config.gcs_bucket}/{gcs_path}")
        
        logger.info(f"Uploaded {len(artifacts)} artifacts to GCS")
    
    except Exception as e:
        logger.error(f"Failed to upload artifacts to GCS: {e}", exc_info=e)

# ============================================
# Main Runner
# ============================================

def run_course(
    course_url: str,
    phase: str,
    date: str,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Exécute l'analyse complète d'une course avec les modules GPI v5.1.
    
    MODE SIMPLIFIÉ : Utilise directement --course-url (correction bug #3).
    
    Args:
        course_url: URL ZEturf de la course
        phase: "H30" ou "H5" (case-insensitive, avec ou sans dash)
        date: YYYY-MM-DD
        correlation_id: ID de corrélation pour logs
        
    Returns:
        {
          "ok": bool,
          "phase": str,
          "returncode": int,
          "stdout_tail": str,
          "stderr": str,
          "artifacts": [...]
        }
    """
    # Normalize phase
    phase_clean = phase.upper().replace("-", "")
    
    # Extraire R/C pour logging et artefacts
    try:
        reunion, course = _extract_rc_from_url(course_url)
    except ValueError as e:
        logger.error(str(e))
        return {
            "ok": False,
            "phase": phase_clean,
            "returncode": -1,
            "error": str(e),
            "artifacts": [],
        }
    
    logger.info(
        f"Starting course analysis",
        correlation_id=correlation_id,
        reunion=reunion,
        course=course,
        phase=phase_clean,
        date=date,
        course_url=course_url,
    )
    
    artifacts = []
    
    # Créer répertoire de sortie
    rc_dir = DATA_DIR / f"{reunion}{course}"
    rc_dir.mkdir(parents=True, exist_ok=True)
    
    # ========================================================================
    # Pipeline H30 : Snapshot simple
    # ========================================================================
    
    if phase_clean == "H30":
        logger.info("Step 1/1: Snapshot H30", correlation_id=correlation_id)
        
        # MODE SIMPLIFIÉ : --course-url directement
        cmd_analyse = [
            sys.executable,
            str(MODULES_DIR / "analyse_courses_du_jour_enrichie.py"),
            "--course-url", course_url,
            "--phase", "H30",
            "--data-dir", str(DATA_DIR),
        ]
        
        rc, stdout, stderr = _run_subprocess(cmd_analyse, timeout=config.timeout_seconds)
        
        if rc != 0:
            logger.error(
                f"H30 analysis failed",
                correlation_id=correlation_id,
                returncode=rc,
                stderr=stderr[:500]
            )
            return {
                "ok": False,
                "phase": "H30",
                "returncode": rc,
                "stdout_tail": stdout[-1000:] if stdout else "",
                "stderr": stderr[:500],
                "artifacts": _collect_artifacts(rc_dir),
            }
        
        # Collecter artefacts
        artifacts = _collect_artifacts(rc_dir)
        
        # Upload GCS si configuré
        if config.gcs_bucket:
            _upload_artifacts_to_gcs(rc_dir, artifacts)
        
        logger.info("H30 analysis complete", correlation_id=correlation_id)
        return {
            "ok": True,
            "phase": "H30",
            "returncode": 0,
            "stdout_tail": stdout[-500:] if stdout else "",
            "artifacts": artifacts,
        }
    
    # ========================================================================
    # Pipeline H5 complet
    # ========================================================================
    
    logger.info("Starting H5 pipeline", correlation_id=correlation_id)
    
    # Étape 1 : Analyse enrichie H5
    logger.info("Step 1/6: analyse_courses_du_jour_enrichie H5", correlation_id=correlation_id)
    
    # MODE SIMPLIFIÉ : --course-url directement
    cmd_analyse = [
        sys.executable,
        str(MODULES_DIR / "analyse_courses_du_jour_enrichie.py"),
        "--course-url", course_url,
        "--phase", "H5",
        "--data-dir", str(DATA_DIR),
    ]
    
    rc, stdout, stderr = _run_subprocess(cmd_analyse, timeout=config.timeout_seconds)
    
    if rc != 0:
        logger.error(
            f"analyse_courses_du_jour_enrichie failed",
            correlation_id=correlation_id,
            returncode=rc,
            stderr=stderr[:500]
        )
        return {
            "ok": False,
            "phase": "H5",
            "returncode": rc,
            "stdout_tail": stdout[-1000:] if stdout else "",
            "stderr": stderr[:500],
            "artifacts": _collect_artifacts(rc_dir),
        }
    
<<<<<<< HEAD
    # Étape 2 : Fetch chronos (optionnel)
    logger.info("Step 2/6: fetch_je_chrono (optional)", correlation_id=correlation_id)
    
    cmd_chrono = [
        sys.executable,
        str(MODULES_DIR / "fetch_je_chrono.py"),
        "--course-url", course_url,
        "--data-dir", str(DATA_DIR),
    ]
    
    # Optionnel : échec non bloquant
    rc_chrono, _, _ = _run_subprocess(cmd_chrono, timeout=120)
    if rc_chrono != 0:
        logger.warning("fetch_je_chrono failed (non-blocking)", correlation_id=correlation_id)
    
    # Étape 3 : p_finale_export.py
    logger.info("Step 3/6: p_finale_export", correlation_id=correlation_id)
=======
    # Étape 2 : p_finale_export.py
    logger.info("Step 2/6: p_finale_export", correlation_id=correlation_id)
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
    
    cmd_p_finale = [
        sys.executable,
        str(MODULES_DIR / "p_finale_export.py"),
        "--rc-dir", str(rc_dir),
    ]
    
    rc, stdout, stderr = _run_subprocess(cmd_p_finale, timeout=180)
    
    if rc != 0:
        logger.error(
            f"p_finale_export failed",
            correlation_id=correlation_id,
            returncode=rc,
            stderr=stderr[:500]
        )
        return {
            "ok": False,
            "phase": "H5",
            "returncode": rc,
            "stdout_tail": stdout[-1000:] if stdout else "",
            "stderr": stderr[:500],
            "artifacts": _collect_artifacts(rc_dir),
        }
    
<<<<<<< HEAD
    # Étape 4 : simulate_ev.py
    logger.info("Step 4/6: simulate_ev", correlation_id=correlation_id)
=======
    # Étape 3 : simulate_ev.py
    logger.info("Step 3/6: simulate_ev", correlation_id=correlation_id)
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
    
    cmd_simulate = [
        sys.executable,
        str(MODULES_DIR / "simulate_ev.py"),
        "--p-finale", str(rc_dir / "p_finale.json"),
        "--output", str(rc_dir / "ev_simulation.json"),
    ]
    
    rc, stdout, stderr = _run_subprocess(cmd_simulate, timeout=180)
    
    if rc != 0:
        logger.warning(
            f"simulate_ev failed (non-critical)",
            correlation_id=correlation_id,
            returncode=rc,
        )
    
<<<<<<< HEAD
    # Étape 5 : pipeline_run.py (génération tickets)
    logger.info("Step 5/6: pipeline_run (ticket generation)", correlation_id=correlation_id)
    
    cmd_pipeline = [
        sys.executable,
        str(MODULES_DIR / "pipeline_run.py"),
        "--rc-dir", str(rc_dir),
        "--budget", str(config.budget_per_race),
=======
    # Étape 4 : pipeline_run.py (génération tickets)
    logger.info("Step 4/6: pipeline_run (ticket generation)", correlation_id=correlation_id)
    
    cmd_pipeline = [
        sys.executable,
        str(SRC_DIR / "pipeline_run.py"), # BUG FIX: Path was incorrect
        f"--reunion={reunion}",
        f"--course={course}",
        f"--budget={config.budget_per_race}",
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
    ]
    
    rc, stdout, stderr = _run_subprocess(cmd_pipeline, timeout=300)
    
    if rc != 0:
        logger.error(
            f"pipeline_run failed",
            correlation_id=correlation_id,
            returncode=rc,
            stderr=stderr[:500]
        )
        return {
            "ok": False,
            "phase": "H5",
            "returncode": rc,
            "stdout_tail": stdout[-1000:] if stdout else "",
            "stderr": stderr[:500],
            "artifacts": _collect_artifacts(rc_dir),
        }
<<<<<<< HEAD
=======

    # Étape 5 : Rendu et sauvegarde du ticket HTML
    logger.info("Step 5/6: Rendering and saving HTML ticket", correlation_id=correlation_id)
    try:
        analysis_path = rc_dir / "analysis_H5.json"
        if analysis_path.exists():
            with open(analysis_path, "r") as f:
                analysis_result = json.load(f)
            
            if not analysis_result.get("abstain") and analysis_result.get("tickets"):
                html_content = render_ticket_html(
                    payload=analysis_result,
                    reunion=reunion,
                    course=course,
                    phase=phase_clean,
                    budget=config.budget_per_race,
                )
                
                save_ticket_html(html_content, date_str=date, rxcy=rc_dir.name)
                logger.info(f"HTML ticket saved for {rc_dir.name}", correlation_id=correlation_id)
            else:
                logger.info(f"Abstaining or no tickets for {rc_dir.name}, skipping HTML generation.", correlation_id=correlation_id)
        else:
            logger.warning(f"analysis_H5.json not found, cannot generate HTML ticket.", correlation_id=correlation_id)
    except Exception as e:
        logger.error(f"Failed to generate or save HTML ticket: {e}", correlation_id=correlation_id, exc_info=True)
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
    
    # Étape 6 : Collecter artefacts
    logger.info("Step 6/6: Collecting artifacts", correlation_id=correlation_id)
    
    artifacts = _collect_artifacts(rc_dir)
    
    # Upload GCS si configuré
    if config.gcs_bucket:
        _upload_artifacts_to_gcs(rc_dir, artifacts)
    
    logger.info(
        "H5 pipeline complete",
        correlation_id=correlation_id,
        artifacts_count=len(artifacts),
    )
    
    return {
        "ok": True,
        "phase": "H5",
        "returncode": 0,
        "stdout_tail": stdout[-500:] if stdout else "",
        "artifacts": artifacts,
    }

# ============================================
# Post-course Updates (optional)
# ============================================

def update_with_results(
    course_url: str,
    date: str,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Met à jour l'Excel avec les résultats officiels (post-course).
    
    Exécute:
      1. get_arrivee_geny.py (fetch résultats)
      2. update_excel_with_results.py (mise à jour Excel)
    
    Args:
        course_url: URL ZEturf de la course
        date: YYYY-MM-DD
        correlation_id: ID de corrélation pour logs
        
    Returns:
        {
          "ok": bool,
          "returncode": int,
          "message": str
        }
    """
    try:
        reunion, course = _extract_rc_from_url(course_url)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    
    logger.info(
        "Updating with results",
        correlation_id=correlation_id,
        reunion=reunion,
        course=course,
    )
    
    # Étape 1 : Fetch arrivée
    cmd_arrivee = [
        sys.executable,
        str(MODULES_DIR / "get_arrivee_geny.py"),
        "--course-url", course_url,
        "--date", date,
    ]
    
    rc, stdout, stderr = _run_subprocess(cmd_arrivee, timeout=60)
    
    if rc != 0:
        logger.error(f"get_arrivee_geny failed: {stderr[:200]}")
        return {
            "ok": False,
            "returncode": rc,
            "message": "Failed to fetch results",
        }
    
    # Étape 2 : Update Excel
    cmd_update = [
        sys.executable,
        str(MODULES_DIR / "update_excel_with_results.py"),
        "--reunion", reunion,
        "--course", course,
        "--date", date,
    ]
    
    rc, stdout, stderr = _run_subprocess(cmd_update, timeout=120)
    
    if rc != 0:
        logger.error(f"update_excel_with_results failed: {stderr[:200]}")
        return {
            "ok": False,
            "returncode": rc,
            "message": "Failed to update Excel",
        }
    
    logger.info("Results updated successfully", correlation_id=correlation_id)
    return {
        "ok": True,
        "returncode": 0,
        "message": "Results updated successfully",
<<<<<<< HEAD
    }
=======
    }
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
