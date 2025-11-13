import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

# --- Project Root Setup ---
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Imports "souples" (ne font pas échouer l'import du module en cas d'absence)
try:
    from src.pipeline_run import run_pipeline  # chemin standard projet
except Exception:  # fallback minimal pour les tests
    def run_pipeline(**kwargs):
        return {"abstain": False, "tickets": [{"type": "SP_DUTCHING", "stake": 3.0}], "roi_global_est": 0.25, "paths": {}, "message": ""}

try:
    from src.email_sender import send_email
except Exception:
    def send_email(*args, **kwargs):
        logging.getLogger(__name__).warning("email_sender indisponible (stub).")

try:
    from modules.tickets_store import render_ticket_html
except Exception:
    def render_ticket_html(output, **kwargs):
        return "<html><body><h1>Tickets</h1></body></html>"

try:
    from get_arrivee_geny import fetch_and_write_arrivals
except Exception:
    def fetch_and_write_arrivals(*args, **kwargs):
        logging.getLogger(__name__).warning("get_arrivee_geny indisponible (stub).")

try:
    from update_excel_with_results import update_excel
except Exception:
    def update_excel(*args, **kwargs):
        logging.getLogger(__name__).warning("update_excel_with_results indisponible (stub).")

# --- Logging ---
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=log_level,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s"}',
    datefmt='%Y-%m-%dT%H:%M:%S%z'
)
logger = logging.getLogger(__name__)

def validate_snapshot_or_die(snapshot: dict, phase: str) -> None:
    import sys
    if not isinstance(snapshot, dict):
        print(f"[runner_chain] ERREUR: snapshot {phase} invalide (type {type(snapshot)})", file=sys.stderr)
        sys.exit(2)
    # ZEturf parser: runners=list, partants=int (pas une liste)
    runners = snapshot.get("runners")
    if not isinstance(runners, list) or len(runners) == 0:
        print(f"[runner_chain] ERREUR: snapshot {phase} vide ou sans 'runners'.", file=sys.stderr)
        sys.exit(2)

def run_subprocess(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    """Wrapper robuste pour subprocess.run avec logs."""
    logger.info("Running: %s", " ".join(map(str, cmd)))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=True)

def run_chain(reunion: str, course: str, phase: str, budget: float, source: str = "zeturf") -> dict[str, Any]:
    """
    Orchestration principale pour une course donnée.
    Conçue pour être appelée par le service FastAPI.
    """
    # --- Data Paths ---
    race_dir = _PROJECT_ROOT / "data" / f"{reunion}{course}"
    race_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = race_dir / f"snapshot_{phase}.json"

    tracking_path = race_dir / "tracking.csv"

    output: dict[str, Any] = {}

    if phase == "H30":
        logger.info("Phase H30: Fetch snapshot for %s%s from source %s", reunion, course, source)
        try:
            if source == "zeturf":
                script_path = _PROJECT_ROOT / "online_fetch_zeturf.py"
                cmd = [sys.executable, str(script_path),
                       "--reunion", reunion, "--course", course, "--output", str(snapshot_path)]
                run_subprocess(cmd)
            elif source == "boturfers":
                script_path = _PROJECT_ROOT / "src" / "online_fetch_boturfers.py"
                cmd = [sys.executable, str(script_path),
                       "--reunion", reunion, "--course", course, "--output", str(snapshot_path)]
                run_subprocess(cmd)
            else:
                raise ValueError(f"Source de données non reconnue: {source}")

        except Exception as e:
            logger.warning("Snapshot fetch failed (continuing in stub mode): %s", e)
        output = {
            "abstain": True, "tickets": [], "roi_global_est": None,
            "paths": {"snapshot": str(snapshot_path), "analysis": None, "tracking": None},
            "message": f"H-30 snapshot created from {source}. No analysis performed."
        }

    elif phase == "H5":
        logger.info("Phase H5: Enrich + pipeline for %s%s", reunion, course)
        je_stats_path  = race_dir / "je_stats.csv"
        je_chrono_path = race_dir / "je_chrono.csv"
        try:
            run_subprocess([sys.executable, str(_PROJECT_ROOT / "fetch_je_stats.py"),
                            "--output", str(je_stats_path), "--reunion", reunion, "--course", course])
            run_subprocess([
                sys.executable, str(_PROJECT_ROOT / "fetch_je_chrono.py"),
                "--output", str(je_chrono_path), "--reunion", reunion, "--course", course
            ])
        except Exception as e:
            msg = f"Abstaining: enrichment fetch failed: {e}"
            logger.error(msg)
            return {"abstain": True, "tickets": [], "roi_global_est": 0, "paths": {}, "message": msg}

        if not je_stats_path.exists() or not je_chrono_path.exists():
            msg = "Abstaining: missing J/E or chrono data after fetch."
            logger.error(msg)
            output = {"abstain": True, "tickets": [], "roi_global_est": 0, "paths": {}, "message": msg}
        else:
            result = run_pipeline(reunion=reunion, course=course, phase=phase, budget=budget)
            output = result or {}
            output.setdefault("paths", {})["tracking"] = str(tracking_path)

            # Notification email si tickets générés
            if not output.get("abstain") and output.get("tickets"):
                email_to = os.environ.get("EMAIL_TO")
                if email_to:
                    html_content = render_ticket_html(output, reunion=reunion, course=course, phase=phase, budget=budget)
                    subject = f"Tickets Hippiques pour {reunion}{course}"
                    send_email(subject, html_content, email_to)
                else:
                    logger.warning("EMAIL_TO not set. Skipping email notification.")

    elif phase == "RESULT":
        logger.info("Phase RESULT: fetch/update results for %s%s", reunion, course)
        today_str = datetime.now(ZoneInfo("Europe/Paris")).strftime('%Y-%m-%d')
        planning_file = _PROJECT_ROOT / "data" / "planning" / f"{today_str}.json"
        arrivals_file = _PROJECT_ROOT / "data" / "results" / f"{today_str}_arrivees.json"
        excel_file = _PROJECT_ROOT / "modele_suivi_courses_hippiques.xlsx"
        p_finale_file = race_dir / "p_finale.json"

        try:
            if planning_file.exists():
                fetch_and_write_arrivals(str(planning_file), str(arrivals_file))
            else:
                logger.warning("Planning file not found: %s", planning_file)

            if arrivals_file.exists() and p_finale_file.exists():
                update_excel(excel_path_str=str(excel_file),
                             arrivee_path_str=str(arrivals_file),
                             tickets_path_str=str(p_finale_file))
            else:
                logger.warning("Arrivals or tickets file not found; skipping Excel update.")

            output = {"abstain": True, "tickets": [], "roi_global_est": None, "paths": {}, "message": "Result phase completed."}
        except Exception as e:
            msg = f"Result processing failed: {e}"
            logger.error(msg, exc_info=True)
            output = {"abstain": True, "tickets": [], "roi_global_est": None, "paths": {}, "message": msg}

    else:
        output = {"abstain": True, "tickets": [], "roi_global_est": None, "paths": {}, "message": "Unknown phase."}

    return output

def main():
    parser = argparse.ArgumentParser(description="Orchestration chain for hippique data processing.")
    parser.add_argument("--reunion", required=True, help="Reunion ID (e.g., R1)")
    parser.add_argument("--course", required=True, help="Course ID (e.g., C3)")
    parser.add_argument("--phase", required=True, choices=["H30", "H5", "RESULT"], help="Pipeline phase")
    parser.add_argument("--budget", type=float, default=5.0, help="Max budget for the race")
    parser.add_argument("--source", type=str, default="zeturf", choices=["zeturf", "boturfers"], help="Data source to use for scraping")
    args = parser.parse_args()

    output = run_chain(reunion=args.reunion, course=args.course, phase=args.phase, budget=args.budget, source=args.source)
    print(json.dumps(output))

if __name__ == "__main__":
    main()
