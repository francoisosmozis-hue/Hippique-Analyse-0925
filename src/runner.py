"""
src/runner.py - Orchestrateur d'exécution des analyses GPI v5.1
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import get_config
from logging_utils import get_logger

logger = get_logger(__name__)
config = get_config()

# Chemins des modules GPI
MODULES_DIR = Path(__file__).parent.parent / "modules"
DATA_DIR = Path(__file__).parent.parent / "data"


def _run_subprocess(
    cmd: List[str],
    timeout: int = 600,
    cwd: Optional[Path] = None,
) -> tuple[int, str, str]:
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


def run_course(
    course_url: str,
    phase: str,
    date: str,
) -> Dict[str, Any]:
    """
    Exécute l'analyse complète d'une course.
    
    Args:
        course_url: URL ZEturf de la course
        phase: "H30" ou "H5"
        date: YYYY-MM-DD
        
    Returns:
        {ok: bool, phase: str, returncode: int, stdout_tail: str, artifacts: [...]}
    """
    phase_clean = phase.upper().replace("-", "")
    correlation_id = f"run-{date.replace('-', '')}-{course_url.split('/')[-1]}-{phase_clean.lower()}"
    
    logger.info(
        f"Starting course analysis",
        correlation_id=correlation_id,
        course_url=course_url,
        phase=phase_clean,
        date=date
    )
    
    artifacts = []
    
    # Étape 1 : Analyse enrichie (H30 ou H5)
    logger.info("Step 1/5: analyse_courses_du_jour_enrichie", correlation_id=correlation_id)
    cmd_analyse = [
        sys.executable,
        str(MODULES_DIR / "analyse_courses_du_jour_enrichie.py"),
        "--course-url", course_url,
        "--phase", phase_clean,
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
            "phase": phase_clean,
            "returncode": rc,
            "stdout_tail": stdout[-1000:] if stdout else "",
            "stderr": stderr[:500],
            "artifacts": artifacts,
        }
    
    # Si H30, on s'arrête là (snapshot simple)
    if phase_clean == "H30":
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
    
    # Étape 2 : Export p_finale (si nécessaire)
    logger.info("Step 2/5: p_finale_export", correlation_id=correlation_id)
    cmd_p_finale = [
        sys.executable,
        str(MODULES_DIR / "p_finale_export.py"),
        "--data-dir", str(DATA_DIR),
    ]
    rc, stdout2, stderr2 = _run_subprocess(cmd_p_finale, timeout=120)
    if rc != 0:
        logger.warning(f"p_finale_export failed (non-blocking)", returncode=rc)
    
    # Étape 3 : Simulation EV
    logger.info("Step 3/5: simulate_ev", correlation_id=correlation_id)
    cmd_ev = [
        sys.executable,
        str(MODULES_DIR / "simulate_ev.py"),
        "--data-dir", str(DATA_DIR),
        "--budget", str(config.budget_total),
    ]
    rc, stdout3, stderr3 = _run_subprocess(cmd_ev, timeout=180)
    if rc != 0:
        logger.warning(f"simulate_ev failed (non-blocking)", returncode=rc)
    
    # Étape 4 : Pipeline run (génération tickets)
    logger.info("Step 4/5: pipeline_run", correlation_id=correlation_id)
    cmd_pipeline = [
        sys.executable,
        str(MODULES_DIR / "pipeline_run.py"),
        "--data-dir", str(DATA_DIR),
        "--budget", str(config.budget_total),
        "--ev-min", str(config.ev_min_global),
        "--roi-min", str(config.roi_min_global),
    ]
    rc, stdout4, stderr4 = _run_subprocess(cmd_pipeline, timeout=300)
    
    if rc != 0:
        logger.error(
            f"pipeline_run failed",
            correlation_id=correlation_id,
            returncode=rc,
            stderr=stderr4[:500]
        )
        return {
            "ok": False,
            "phase": "H5",
            "returncode": rc,
            "stdout_tail": stdout4[-1000:] if stdout4 else "",
            "stderr": stderr4[:500],
            "artifacts": artifacts,
        }
    
    # Étape 5 : Export Excel (optionnel)
    logger.info("Step 5/5: update_excel_with_results", correlation_id=correlation_id)
    cmd_excel = [
        sys.executable,
        str(MODULES_DIR / "update_excel_with_results.py"),
        "--data-dir", str(DATA_DIR),
    ]
    rc, stdout5, stderr5 = _run_subprocess(cmd_excel, timeout=60)
    if rc != 0:
        logger.warning(f"update_excel_with_results failed (non-blocking)", returncode=rc)
    
    # Collecter artifacts
    artifacts = _collect_artifacts(date, course_url)
    
    logger.info(
        f"H5 pipeline complete",
        correlation_id=correlation_id,
        artifacts_count=len(artifacts)
    )
    
    # Upload GCS si configuré
    if config.gcs_bucket:
        _upload_artifacts_to_gcs(artifacts)
    
    return {
        "ok": True,
        "phase": "H5",
        "returncode": 0,
        "stdout_tail": stdout[-500:] if stdout else "",
        "artifacts": artifacts,
    }


def _collect_artifacts(date: str, course_url: str) -> List[str]:
    """
    Collecte les artefacts générés dans data/.
    
    Returns:
        Liste de chemins relatifs
    """
    artifacts = []
    
    # Extraire R/C de l'URL
    match = re.search(r"R(\d+)C(\d+)", course_url)
    if not match:
        return artifacts
    
    r, c = match.groups()
    rc_dir = DATA_DIR / f"R{r}C{c}"
    
    if not rc_dir.exists():
        return artifacts
    
    # Lister les fichiers importants
    patterns = [
        "snapshot_*.json",
        "p_finale.json",
        "decision.json",
        "tickets_*.json",
        "*.csv",
        "*.xlsx",
    ]
    
    import glob
    for pattern in patterns:
        for file in glob.glob(str(rc_dir / pattern)):
            artifacts.append(str(Path(file).relative_to(DATA_DIR.parent)))
    
    return artifacts


def _upload_artifacts_to_gcs(artifacts: List[str]) -> None:
    """
    Upload les artefacts vers GCS.
    
    Args:
        artifacts: Liste de chemins relatifs à uploader
    """
    if not config.gcs_bucket:
        return
    
    logger.info(f"Uploading {len(artifacts)} artifacts to GCS", bucket=config.gcs_bucket)
    
    try:
        from google.cloud import storage
        
        client = storage.Client()
        bucket = client.bucket(config.gcs_bucket)
        
        for artifact in artifacts:
            local_path = DATA_DIR.parent / artifact
            if not local_path.exists():
                logger.warning(f"Artifact not found: {artifact}")
                continue
            
            blob_name = f"{config.gcs_prefix}/{artifact}"
            blob = bucket.blob(blob_name)
            
            blob.upload_from_filename(str(local_path))
            logger.debug(f"Uploaded {artifact} to gs://{config.gcs_bucket}/{blob_name}")
        
        logger.info(f"GCS upload complete")
    except Exception as e:
        logger.error(f"Failed to upload to GCS: {e}", exc_info=e)


# ============================================================================
# Post-course : récupération résultats
# ============================================================================

def run_post_race_results(date: str) -> Dict[str, Any]:
    """
    Récupère les résultats des courses terminées et met à jour Excel.
    
    Args:
        date: YYYY-MM-DD
        
    Returns:
        {ok: bool, results_count: int}
    """
    logger.info(f"Fetching post-race results for {date}")
    
    # Étape 1 : get_arrivee_geny
    cmd_arrivee = [
        sys.executable,
        str(MODULES_DIR / "get_arrivee_geny.py"),
        "--date", date,
        "--out", str(DATA_DIR / "results" / f"arrivees_{date}.json"),
    ]
    
    rc, stdout, stderr = _run_subprocess(cmd_arrivee, timeout=180)
    if rc != 0:
        logger.error(f"get_arrivee_geny failed", returncode=rc, stderr=stderr[:500])
        return {"ok": False, "results_count": 0}
    
    # Étape 2 : update_excel_with_results
    cmd_excel = [
        sys.executable,
        str(MODULES_DIR / "update_excel_with_results.py"),
        "--results", str(DATA_DIR / "results" / f"arrivees_{date}.json"),
    ]
    
    rc, stdout2, stderr2 = _run_subprocess(cmd_excel, timeout=60)
    if rc != 0:
        logger.warning(f"update_excel_with_results failed", returncode=rc)
    
    # Uploader Excel vers GCS
    excel_path = Path("excel/modele_suivi_courses_hippiques.xlsx")
    if config.gcs_bucket and excel_path.exists():
        _upload_artifacts_to_gcs([str(excel_path)])
    
    logger.info("Post-race results processed")
    return {"ok": True, "results_count": 1}


import re  # Ajout de l'import manquant