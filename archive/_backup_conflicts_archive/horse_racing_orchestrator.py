"""
=============================================================================
ORCHESTRATEUR HIPPIQUE GCP - Architecture complète Cloud Run + Tasks
=============================================================================

Structure du projet:
/
├── src/
│   ├── service.py          # API FastAPI (endpoints)
│   ├── plan.py             # Construction du plan ZEturf/Geny
│   ├── scheduler.py        # Cloud Tasks + Scheduler fallback
│   ├── runner.py           # Exécution modules GPI v5.1
│   ├── config.py           # Configuration & env
│   ├── logging_utils.py    # Logging structuré JSON
│   └── time_utils.py       # Gestion timezone Europe/Paris
├── scripts/
│   ├── deploy_cloud_run.sh
│   └── create_scheduler_0900.sh
├── Dockerfile
├── gunicorn.conf.py
├── requirements.txt
└── .env.example

=============================================================================
"""

# ============================================================================
# src/config.py - Configuration centralisée
# ============================================================================

import os

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class Config(BaseModel):
    # GCP
    PROJECT_ID: str = Field(default_factory=lambda: os.getenv("PROJECT_ID", ""))
    REGION: str = Field(default_factory=lambda: os.getenv("REGION", "europe-west1"))
    SERVICE_NAME: str = Field(
        default_factory=lambda: os.getenv("SERVICE_NAME", "horse-racing-orchestrator")
    )
    SERVICE_URL: str = Field(default_factory=lambda: os.getenv("SERVICE_URL", ""))
    QUEUE_ID: str = Field(default_factory=lambda: os.getenv("QUEUE_ID", "horse-racing-queue"))

    # Scheduler & Tasks
    SCHEDULER_SA_EMAIL: str = Field(default_factory=lambda: os.getenv("SCHEDULER_SA_EMAIL", ""))
    SCHEDULER_JOB_0900: str = Field(
        default_factory=lambda: os.getenv("SCHEDULER_JOB_0900", "daily-plan-0900")
    )

    # Auth & Security
    REQUIRE_AUTH: bool = Field(
        default_factory=lambda: os.getenv("REQUIRE_AUTH", "true").lower() == "true"
    )
    OIDC_AUDIENCE: str | None = Field(default_factory=lambda: os.getenv("OIDC_AUDIENCE"))

    # Storage
    GCS_BUCKET: str | None = Field(default_factory=lambda: os.getenv("GCS_BUCKET"))
    LOCAL_DATA_DIR: str = Field(
        default_factory=lambda: os.getenv("LOCAL_DATA_DIR", "/tmp/horse_data")
    )

    # Timezone & Scheduling
    TIMEZONE: str = Field(default_factory=lambda: os.getenv("TIMEZONE", "Europe/Paris"))
    DAILY_SCHEDULE_HOUR: int = Field(
        default_factory=lambda: int(os.getenv("DAILY_SCHEDULE_HOUR", "9"))
    )

    # Throttling & Retries
    REQUEST_TIMEOUT: int = Field(default_factory=lambda: int(os.getenv("REQUEST_TIMEOUT", "30")))
    MAX_RETRIES: int = Field(default_factory=lambda: int(os.getenv("MAX_RETRIES", "3")))
    RATE_LIMIT_DELAY: float = Field(
        default_factory=lambda: float(os.getenv("RATE_LIMIT_DELAY", "1.0"))
    )

    # User Agent
    USER_AGENT: str = Field(
        default_factory=lambda: os.getenv(
            "USER_AGENT", "HorseRacingAnalyzer/5.1 (Educational; contact@example.com)"
        )
    )

    # GPI Budget
    GPI_BUDGET_PER_RACE: float = Field(
        default_factory=lambda: float(os.getenv("GPI_BUDGET_PER_RACE", "5.0"))
    )
    GPI_MIN_EV_PERCENT: float = Field(
        default_factory=lambda: float(os.getenv("GPI_MIN_EV_PERCENT", "40.0"))
    )

    class Config:
        case_sensitive = True


config = Config()


# ============================================================================
# src/logging_utils.py - Logging structuré JSON pour Cloud Logging
# ============================================================================

import json
import logging
import sys
import traceback
from datetime import datetime
from typing import Any

from pythonjsonlogger import jsonlogger


class CloudLoggingFormatter(jsonlogger.JsonFormatter):
    """Formatter compatible avec Cloud Logging (structured logs)"""

    def add_fields(
        self, log_record: dict[str, Any], record: logging.LogRecord, message_dict: dict
    ) -> None:
        super().add_fields(log_record, record, message_dict)

        # Cloud Logging fields
        log_record['severity'] = record.levelname
        log_record['timestamp'] = datetime.utcnow().isoformat() + 'Z'
        log_record['message'] = record.getMessage()

        # Correlation ID pour tracer une course
        if hasattr(record, 'correlation_id'):
            log_record['correlation_id'] = record.correlation_id

        # Exception info
        if record.exc_info:
            log_record['exception'] = traceback.format_exception(*record.exc_info)


def setup_logger(name: str = "horse_racing") -> logging.Logger:
    """Configure un logger JSON structuré"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Éviter les doublons
    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)
    formatter = CloudLoggingFormatter('%(timestamp)s %(severity)s %(name)s %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


logger = setup_logger()


# ============================================================================
# src/time_utils.py - Gestion timezone Europe/Paris <-> UTC
# ============================================================================

from datetime import timedelta
from zoneinfo import ZoneInfo

PARIS_TZ = ZoneInfo("Europe/Paris")
UTC_TZ = ZoneInfo("UTC")


def now_paris() -> datetime:
    """Heure actuelle en Europe/Paris"""
    return datetime.now(PARIS_TZ)


def parse_local_time(date_str: str, time_str: str) -> datetime:
    """
    Parse date + heure locale (Europe/Paris)
    Args:
        date_str: "YYYY-MM-DD"
        time_str: "HH:MM"
    Returns:
        datetime en timezone Europe/Paris
    """
    dt_naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    return dt_naive.replace(tzinfo=PARIS_TZ)


def to_utc(dt_paris: datetime) -> datetime:
    """Convertit Europe/Paris -> UTC"""
    if dt_paris.tzinfo is None:
        dt_paris = dt_paris.replace(tzinfo=PARIS_TZ)
    return dt_paris.astimezone(UTC_TZ)


def to_paris(dt_utc: datetime) -> datetime:
    """Convertit UTC -> Europe/Paris"""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=UTC_TZ)
    return dt_utc.astimezone(PARIS_TZ)


def to_rfc3339(dt: datetime) -> str:
    """Convertit datetime en RFC3339 (requis par Cloud Tasks)"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    return dt.isoformat()


def calculate_snapshots(race_time_local: datetime) -> tuple[datetime, datetime]:
    """
    Calcule H-30 et H-5 en Europe/Paris
    Returns: (h30_time_paris, h5_time_paris)
    """
    h30 = race_time_local - timedelta(minutes=30)
    h5 = race_time_local - timedelta(minutes=5)
    return (h30, h5)


# ============================================================================
# src/plan.py - Construction du plan quotidien (ZEturf + Geny fallback)
# ============================================================================

import re
import time

import requests
from bs4 import BeautifulSoup

from .config import config
from .logging_utils import logger
from .time_utils import now_paris, parse_local_time


class PlanBuilder:
    """Construit le plan du jour depuis ZEturf (+ fallback Geny pour heures)"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                'User-Agent': config.USER_AGENT,
                'Accept': 'text/html,application/xhtml+xml',
                'Accept-Language': 'fr-FR,fr;q=0.9',
            }
        )

    def build_plan(self, date_str: str) -> list[dict]:
        """
        Construit le plan complet pour une date
        Args:
            date_str: "YYYY-MM-DD" ou "today"
        Returns:
            Liste de courses avec structure:
            {
                "date": "YYYY-MM-DD",
                "r_label": "R1",
                "c_label": "C3",
                "meeting": "VINCENNES",
                "time_local": "14:15",
                "course_url": "https://...",
                "reunion_url": "https://..."
            }
        """
        if date_str == "today":
            date_str = now_paris().strftime("%Y-%m-%d")

        logger.info(f"Building plan for date {date_str}")

        # Étape 1: Parser ZEturf pour URLs et structure R/C
        zeturf_plan = self._parse_zeturf_program(date_str)

        if not zeturf_plan:
            logger.warning("No races found on ZEturf, trying Geny as primary source")
            return self._parse_geny_program(date_str)

        # Étape 2: Compléter les heures depuis Geny si manquantes
        self._fill_times_from_geny(date_str, zeturf_plan)

        # Étape 3: Déduplication et tri
        plan = self._deduplicate_and_sort(zeturf_plan)

        logger.info(f"Plan built: {len(plan)} races")
        return plan

    def _parse_zeturf_program(self, date_str: str) -> list[dict]:
        """Parse la page 'Programmes et pronostics' ZEturf"""
        url = f"https://www.zeturf.fr/fr/programme-pronostic/{date_str}"

        try:
            time.sleep(config.RATE_LIMIT_DELAY)
            resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, 'lxml')
            races = []

            # Pattern URL: /fr/course/YYYY-MM-DD/R1C2-hippodrome-name
            course_links = soup.find_all(
                'a', href=re.compile(r'/fr/course/\d{4}-\d{2}-\d{2}/R\d+C\d+')
            )

            for link in course_links:
                href = link.get('href')
                match = re.search(r'/course/(\d{4}-\d{2}-\d{2})/R(\d+)C(\d+)', href)
                if not match:
                    continue

                race_date, r_num, c_num = match.groups()

                # Extraire meeting depuis le texte ou l'URL
                meeting = self._extract_meeting(link, href)

                races.append(
                    {
                        "date": race_date,
                        "r_label": f"R{r_num}",
                        "c_label": f"C{c_num}",
                        "meeting": meeting.upper(),
                        "time_local": None,  # À compléter
                        "course_url": f"https://www.zeturf.fr{href}",
                        "reunion_url": f"https://www.zeturf.fr/fr/reunion/{race_date}/R{r_num}",
                    }
                )

            logger.info(f"Parsed {len(races)} races from ZEturf")
            return races

        except Exception as e:
            logger.error(f"Error parsing ZEturf: {e}", exc_info=True)
            return []

    def _extract_meeting(self, link_elem, href: str) -> str:
        """Extrait le nom de l'hippodrome"""
        # Essayer depuis le texte du lien
        text = link_elem.get_text(strip=True)
        if text:
            parts = text.split('-')
            if len(parts) > 1:
                return parts[-1].strip()

        # Sinon depuis l'URL
        match = re.search(r'R\d+C\d+-(.+)', href)
        if match:
            return match.group(1).replace('-', ' ').strip()

        return "UNKNOWN"

    def _fill_times_from_geny(self, date_str: str, plan: list[dict]) -> None:
        """Fallback: récupère les heures depuis Geny.com"""
        url = f"https://www.geny.com/courses-pmu/{date_str}"

        try:
            time.sleep(config.RATE_LIMIT_DELAY)
            resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, 'lxml')

            # Parser les blocs réunion/course avec heures
            # Structure typique: <div class="race-time">14h15</div>
            for race in plan:
                if race["time_local"]:
                    continue

                # Rechercher pattern "R1C3" + heure
                pattern = f"{race['r_label']}{race['c_label']}"
                # Logique de parsing simplifiée - à adapter selon HTML réel
                time_elem = soup.find(text=re.compile(pattern))
                if time_elem:
                    # Chercher heure proche (format 14h15 ou 14:15)
                    parent = time_elem.find_parent()
                    if parent:
                        time_match = re.search(r'(\d{1,2})[h:](\d{2})', parent.get_text())
                        if time_match:
                            hour, minute = time_match.groups()
                            race["time_local"] = f"{hour.zfill(2)}:{minute}"

            logger.info("Filled times from Geny")

        except Exception as e:
            logger.warning(f"Could not fetch times from Geny: {e}")

    def _parse_geny_program(self, date_str: str) -> list[dict]:
        """Parser Geny comme source principale si ZEturf échoue"""
        url = f"https://www.geny.com/courses-pmu/{date_str}"

        try:
            time.sleep(config.RATE_LIMIT_DELAY)
            resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, 'lxml')
            races = []

            # Parser structure Geny (à adapter selon HTML réel)
            race_blocks = soup.find_all('div', class_=re.compile('race-card|course-item'))

            for block in race_blocks:
                # Extraire R/C/hippodrome/heure
                # Exemple simplifié - ajuster selon structure réelle
                text = block.get_text()
                rc_match = re.search(r'R(\d+)C(\d+)', text)
                time_match = re.search(r'(\d{1,2})[h:](\d{2})', text)

                if rc_match:
                    r_num, c_num = rc_match.groups()
                    time_local = None
                    if time_match:
                        h, m = time_match.groups()
                        time_local = f"{h.zfill(2)}:{m}"

                    races.append(
                        {
                            "date": date_str,
                            "r_label": f"R{r_num}",
                            "c_label": f"C{c_num}",
                            "meeting": "UNKNOWN",  # À extraire
                            "time_local": time_local,
                            "course_url": f"https://www.zeturf.fr/fr/course/{date_str}/R{r_num}C{c_num}",
                            "reunion_url": f"https://www.zeturf.fr/fr/reunion/{date_str}/R{r_num}",
                        }
                    )

            return races

        except Exception as e:
            logger.error(f"Error parsing Geny: {e}", exc_info=True)
            return []

    def _deduplicate_and_sort(self, plan: list[dict]) -> list[dict]:
        """Déduplique par (date, R, C) et tri par heure"""
        seen = set()
        unique = []

        for race in plan:
            key = (race["date"], race["r_label"], race["c_label"])
            if key not in seen:
                seen.add(key)
                unique.append(race)

        # Tri par heure (celles sans heure en fin)
        def sort_key(r):
            if r["time_local"]:
                try:
                    h, m = r["time_local"].split(':')
                    return (0, int(h), int(m))
                except:
                    pass
            return (1, 99, 99)  # Sans heure -> fin

        unique.sort(key=sort_key)
        return unique


# ============================================================================
# src/scheduler.py - Cloud Tasks (+ fallback Scheduler)
# ============================================================================

from datetime import datetime

from google.cloud import scheduler_v1, tasks_v2
from google.protobuf import timestamp_pb2

from .time_utils import to_utc


class TaskScheduler:
    """Planification via Cloud Tasks (recommandé) ou Scheduler fallback"""

    def __init__(self):
        self.tasks_client = tasks_v2.CloudTasksClient()
        self.scheduler_client = scheduler_v1.CloudSchedulerClient()
        self.queue_path = self.tasks_client.queue_path(
            config.PROJECT_ID, config.REGION, config.QUEUE_ID
        )

    def enqueue_run_task(
        self,
        run_url: str,
        course_url: str,
        phase: str,
        when_paris: datetime,
        date_str: str,
        r_label: str,
        c_label: str,
    ) -> str | None:
        """
        Crée une tâche Cloud Tasks pour exécuter /run
        Args:
            run_url: URL du endpoint POST /run
            course_url: URL de la course
            phase: "H30" ou "H5"
            when_paris: datetime en Europe/Paris
            date_str, r_label, c_label: pour le nom déterministe
        Returns:
            Task name ou None si erreur
        """
        try:
            # Nom déterministe RFC-1035 (a-z0-9-, max 500 chars)
            phase_clean = phase.lower().replace('-', '')
            r_num = re.search(r'(\d+)', r_label).group(1)
            c_num = re.search(r'(\d+)', c_label).group(1)
            task_id = f"run-{date_str}-r{r_num}c{c_num}-{phase_clean}"
            task_name = f"{self.queue_path}/tasks/{task_id}"

            # Vérifier si existe déjà
            try:
                self.tasks_client.get_task(name=task_name)
                logger.info(f"Task {task_id} already exists, skipping")
                return task_name
            except Exception:
                pass  # N'existe pas, on continue

            # Payload
            payload = {"course_url": course_url, "phase": phase, "date": date_str}

            # Schedule time en UTC
            when_utc = to_utc(when_paris)
            timestamp = timestamp_pb2.Timestamp()
            timestamp.FromDatetime(when_utc)

            # Construire la tâche
            task = {
                "name": task_name,
                "http_request": {
                    "http_method": tasks_v2.HttpMethod.POST,
                    "url": run_url,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps(payload).encode(),
                },
                "schedule_time": timestamp,
            }

            # OIDC si requis
            if config.REQUIRE_AUTH and config.SCHEDULER_SA_EMAIL:
                task["http_request"]["oidc_token"] = {
                    "service_account_email": config.SCHEDULER_SA_EMAIL,
                    "audience": run_url,
                }

            response = self.tasks_client.create_task(parent=self.queue_path, task=task)

            logger.info(
                f"Task created: {task_id} at {when_paris.strftime('%Y-%m-%d %H:%M %Z')} "
                f"(UTC: {when_utc.strftime('%H:%M')})"
            )
            return response.name

        except Exception as e:
            logger.error(f"Error creating task: {e}", exc_info=True)
            return None

    def create_one_shot_scheduler_job(
        self, job_name: str, when_paris: datetime, target_url: str, payload: dict
    ) -> bool:
        """
        Fallback: crée un job Scheduler one-shot
        Args:
            job_name: Nom du job (doit être unique)
            when_paris: datetime en Europe/Paris
            target_url: URL cible
            payload: JSON body
        """
        try:
            parent = f"projects/{config.PROJECT_ID}/locations/{config.REGION}"
            job_path = f"{parent}/jobs/{job_name}"

            # Vérifier si existe
            try:
                self.scheduler_client.get_job(name=job_path)
                logger.info(f"Scheduler job {job_name} already exists")
                return True
            except Exception:
                pass

            # Convertir en cron expression one-shot (pas idéal, mais possible)
            # Alternative: utiliser schedule avec date précise (non standard)
            # Pour simplifier, on utilise Cloud Tasks recommandé
            logger.warning("Scheduler fallback not fully implemented, use Cloud Tasks")
            return False

        except Exception as e:
            logger.error(f"Error creating scheduler job: {e}", exc_info=True)
            return False


# ============================================================================
# src/runner.py - Exécution des modules GPI v5.1
# ============================================================================

import subprocess
from pathlib import Path


class GPIRunner:
    """Exécute les modules d'analyse GPI v5.1"""

    def __init__(self, data_dir: str | None = None):
        self.data_dir = Path(data_dir or config.LOCAL_DATA_DIR)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Modules GPI (à adapter selon votre arborescence)
        self.gpi_base = Path("gpi_modules")  # Ajuster le chemin

    def run_course(
        self, course_url: str, phase: str, date_str: str, correlation_id: str | None = None
    ) -> dict:
        """
        Exécute l'analyse complète d'une course
        Args:
            course_url: URL ZEturf de la course
            phase: "H30", "H-30", "H5", "H-5"
            date_str: "YYYY-MM-DD"
            correlation_id: ID de traçabilité
        Returns:
            {
                "ok": bool,
                "rc": int,
                "stdout_tail": str,
                "stderr_tail": str,
                "artifacts": list[str]
            }
        """
        # Normaliser phase
        phase_norm = self._normalize_phase(phase)

        logger.info(
            f"Running GPI analysis for {course_url} phase={phase_norm}",
            extra={"correlation_id": correlation_id},
        )

        results = {"ok": False, "rc": -1, "stdout_tail": "", "stderr_tail": "", "artifacts": []}

        try:
            # Environnement pour subprocess
            env = os.environ.copy()
            env.update(
                {
                    "COURSE_URL": course_url,
                    "PHASE": phase_norm,
                    "DATE": date_str,
                    "DATA_DIR": str(self.data_dir),
                    "GPI_BUDGET": str(config.GPI_BUDGET_PER_RACE),
                    "GPI_MIN_EV": str(config.GPI_MIN_EV_PERCENT),
                }
            )

            # Séquence d'exécution
            steps = [
                ("analyse_enrichie", self._run_analyse_enrichie),
                ("p_finale_export", self._run_p_finale_export),
                ("simulate_ev", self._run_simulate_ev),
                ("pipeline_run", self._run_pipeline_run),
            ]

            all_stdout = []
            all_stderr = []

            for step_name, step_func in steps:
                logger.info(f"Step: {step_name}", extra={"correlation_id": correlation_id})

                rc, stdout, stderr = step_func(env)
                all_stdout.append(f"=== {step_name} ===\n{stdout}")
                all_stderr.append(f"=== {step_name} ===\n{stderr}")

                if rc != 0:
                    logger.error(
                        f"Step {step_name} failed with rc={rc}",
                        extra={"correlation_id": correlation_id},
                    )
                    results["rc"] = rc
                    break

            # Succès si dernière étape OK
            if rc == 0:
                results["ok"] = True
                results["rc"] = 0

            # Tails (dernières lignes)
            full_stdout = "\n".join(all_stdout)
            full_stderr = "\n".join(all_stderr)
            results["stdout_tail"] = self._tail(full_stdout, 50)
            results["stderr_tail"] = self._tail(full_stderr, 30)

            # Collecter artefacts
            results["artifacts"] = self._collect_artifacts(date_str)

            # Upload GCS si configuré
            if config.GCS_BUCKET:
                self._upload_to_gcs(results["artifacts"], date_str, correlation_id)

            logger.info(
                f"Analysis complete: ok={results['ok']}", extra={"correlation_id": correlation_id}
            )

        except Exception as e:
            logger.error(
                f"Runner error: {e}", exc_info=True, extra={"correlation_id": correlation_id}
            )
            results["stderr_tail"] = str(e)

        return results

    def _normalize_phase(self, phase: str) -> str:
        """Normalise H-30/H30 -> H30, H-5/H5 -> H5"""
        phase = phase.upper().replace('-', '').replace('_', '')
        if phase in ('H30', 'H5'):
            return phase
        raise ValueError(f"Invalid phase: {phase}")

    def _run_analyse_enrichie(self, env: dict) -> tuple[int, str, str]:
        """Exécute analyse_courses_du_jour_enrichie.py"""
        script = self.gpi_base / "analyse_courses_du_jour_enrichie.py"
        if not script.exists():
            return (1, "", f"Script not found: {script}")

        cmd = [
            "python",
            str(script),
            "--course-url",
            env["COURSE_URL"],
            "--phase",
            env["PHASE"],
            "--output-dir",
            env["DATA_DIR"],
        ]

        return self._run_subprocess(cmd, env)

    def _run_p_finale_export(self, env: dict) -> tuple[int, str, str]:
        """Exécute p_finale_export.py"""
        script = self.gpi_base / "p_finale_export.py"
        if not script.exists():
            return (0, "Script skipped (optional)", "")

        cmd = ["python", str(script), "--data-dir", env["DATA_DIR"]]
        return self._run_subprocess(cmd, env)

    def _run_simulate_ev(self, env: dict) -> tuple[int, str, str]:
        """Exécute simulate_ev.py"""
        script = self.gpi_base / "simulate_ev.py"
        if not script.exists():
            return (0, "Script skipped (optional)", "")

        cmd = [
            "python",
            str(script),
            "--data-dir",
            env["DATA_DIR"],
            "--min-ev",
            str(config.GPI_MIN_EV_PERCENT),
        ]
        return self._run_subprocess(cmd, env)

    def _run_pipeline_run(self, env: dict) -> tuple[int, str, str]:
        """Exécute pipeline_run.py"""
        script = self.gpi_base / "pipeline_run.py"
        if not script.exists():
            return (0, "Script skipped (optional)", "")

        cmd = ["python", str(script), "--data-dir", env["DATA_DIR"]]
        return self._run_subprocess(cmd, env)

    def _run_subprocess(
        self, cmd: list[str], env: dict, timeout: int = 300
    ) -> tuple[int, str, str]:
        """Exécute une commande subprocess avec timeout"""
        try:
            proc = subprocess.run(
                cmd, env=env, capture_output=True, text=True, timeout=timeout, check=False
            )
            return (proc.returncode, proc.stdout, proc.stderr)
        except subprocess.TimeoutExpired:
            return (124, "", f"Timeout after {timeout}s")
        except Exception as e:
            return (1, "", str(e))

    def _tail(self, text: str, lines: int) -> str:
        """Retourne les N dernières lignes"""
        return "\n".join(text.splitlines()[-lines:])

    def _collect_artifacts(self, date_str: str) -> list[str]:
        """Liste les fichiers artefacts générés"""
        artifacts = []
        patterns = ["*.json", "*.csv", "*.xlsx", "*.pdf"]

        for pattern in patterns:
            artifacts.extend([str(p) for p in self.data_dir.glob(pattern)])

        return artifacts

    def _upload_to_gcs(
        self, artifacts: list[str], date_str: str, correlation_id: str | None
    ) -> None:
        """Upload artefacts vers GCS"""
        if not config.GCS_BUCKET:
            return

        try:
            from google.cloud import storage

            client = storage.Client()
            bucket = client.bucket(config.GCS_BUCKET)

            for artifact in artifacts:
                blob_name = (
                    f"results/{date_str}/{correlation_id or 'unknown'}/{Path(artifact).name}"
                )
                blob = bucket.blob(blob_name)
                blob.upload_from_filename(artifact)
                logger.info(f"Uploaded to GCS: {blob_name}")

        except Exception as e:
            logger.error(f"GCS upload error: {e}", exc_info=True)


# ============================================================================
# src/service.py - API FastAPI avec endpoints
# ============================================================================

import uuid
from datetime import datetime
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .plan import PlanBuilder
from .runner import GPIRunner
from .scheduler import TaskScheduler
from .time_utils import calculate_snapshots

app = FastAPI(title="Horse Racing Orchestrator", version="1.0.0")

plan_builder = PlanBuilder()
scheduler = TaskScheduler()
runner = GPIRunner()

# ============ Models ============


class ScheduleRequest(BaseModel):
    date: str = "today"  # "YYYY-MM-DD" ou "today"
    mode: Literal["tasks", "scheduler"] = "tasks"


class RunRequest(BaseModel):
    course_url: str
    phase: str  # "H-30", "H30", "H-5", "H5"
    date: str  # "YYYY-MM-DD"


# ============ Auth ============


async def verify_oidc(request: Request):
    """Vérifie le token OIDC si REQUIRE_AUTH=true"""
    if not config.REQUIRE_AUTH:
        return True

    # Implémenter vérification JWT OIDC
    # Pour l'instant, passer (déploiement nécessite config IAM)
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    # TODO: Vérifier signature JWT avec google.auth
    return True


# ============ Endpoints ============


@app.get("/healthz")
async def healthz():
    """Health check"""
    return {"status": "ok", "timestamp": now_paris().isoformat()}


@app.post("/schedule")
async def schedule(req: ScheduleRequest, _auth=Depends(verify_oidc)):
    """
    Génère le plan du jour et programme les exécutions H-30/H-5
    """
    correlation_id = str(uuid.uuid4())
    logger.info(
        f"POST /schedule date={req.date} mode={req.mode}", extra={"correlation_id": correlation_id}
    )

    try:
        # Construire le plan
        plan = plan_builder.build_plan(req.date)

        if not plan:
            raise HTTPException(status_code=404, detail="No races found for this date")

        # Sauvegarder plan.json
        plan_path = config.LOCAL_DATA_DIR / "plan.json"
        with open(plan_path, 'w', encoding='utf-8') as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)

        # Programmer les tâches
        scheduled_tasks = []
        run_url = f"{config.SERVICE_URL}/run"

        for race in plan:
            if not race.get("time_local"):
                logger.warning(f"Skipping {race['r_label']}{race['c_label']}: no time")
                continue

            try:
                race_time = parse_local_time(race["date"], race["time_local"])
                h30_time, h5_time = calculate_snapshots(race_time)

                # Tâche H-30
                if req.mode == "tasks":
                    task_h30 = scheduler.enqueue_run_task(
                        run_url=run_url,
                        course_url=race["course_url"],
                        phase="H30",
                        when_paris=h30_time,
                        date_str=race["date"],
                        r_label=race["r_label"],
                        c_label=race["c_label"],
                    )

                    # Tâche H-5
                    task_h5 = scheduler.enqueue_run_task(
                        run_url=run_url,
                        course_url=race["course_url"],
                        phase="H5",
                        when_paris=h5_time,
                        date_str=race["date"],
                        r_label=race["r_label"],
                        c_label=race["c_label"],
                    )

                    scheduled_tasks.append(
                        {
                            "race": f"{race['r_label']}{race['c_label']}",
                            "meeting": race["meeting"],
                            "time_local": race["time_local"],
                            "h30_task": task_h30,
                            "h30_time_utc": to_utc(h30_time).strftime("%Y-%m-%d %H:%M:%S UTC"),
                            "h5_task": task_h5,
                            "h5_time_utc": to_utc(h5_time).strftime("%Y-%m-%d %H:%M:%S UTC"),
                        }
                    )

            except Exception as e:
                logger.error(f"Error scheduling {race['r_label']}{race['c_label']}: {e}")

        return {
            "ok": True,
            "correlation_id": correlation_id,
            "plan_path": str(plan_path),
            "races_count": len(plan),
            "tasks_scheduled": len(scheduled_tasks),
            "tasks": scheduled_tasks,
        }

    except Exception as e:
        logger.error(f"Schedule error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/run")
async def run(req: RunRequest, _auth=Depends(verify_oidc)):
    """
    Exécute l'analyse d'une course (H-30 ou H-5)
    """
    correlation_id = str(uuid.uuid4())
    logger.info(
        f"POST /run url={req.course_url} phase={req.phase}",
        extra={"correlation_id": correlation_id},
    )

    try:
        result = runner.run_course(
            course_url=req.course_url,
            phase=req.phase,
            date_str=req.date,
            correlation_id=correlation_id,
        )

        return {
            "ok": result["ok"],
            "correlation_id": correlation_id,
            "returncode": result["rc"],
            "stdout_tail": result["stdout_tail"],
            "stderr_tail": result["stderr_tail"],
            "artifacts": result["artifacts"],
        }

    except Exception as e:
        logger.error(f"Run error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ============================================================================
# FICHIERS ADDITIONNELS (à créer séparément)
# ============================================================================

"""
Dockerfile:
-----------
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \\
    libxml2 libxslt1.1 tzdata \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
ENV PYTHONUNBUFFERED=1

CMD exec gunicorn --config gunicorn.conf.py src.service:app


gunicorn.conf.py:
-----------------
import multiprocessing

bind = "0.0.0.0:8080"
workers = 2
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 300
keepalive = 5
errorlog = "-"
accesslog = "-"
loglevel = "info"


requirements.txt:
-----------------
fastapi==0.104.1
uvicorn[standard]==0.24.0
gunicorn==21.2.0
pydantic==2.5.0
pydantic-settings==2.1.0
python-dotenv==1.0.0
requests==2.31.0
beautifulsoup4==4.12.2
lxml==4.9.3
google-cloud-tasks==2.14.2
google-cloud-scheduler==2.11.3
google-cloud-storage==2.10.0
python-json-logger==2.0.7
python-dateutil==2.8.2
pandas==2.1.3
openpyxl==3.1.2


.env.example:
-------------
PROJECT_ID=your-gcp-project
REGION=europe-west1
SERVICE_NAME=horse-racing-orchestrator
SERVICE_URL=https://horse-racing-orchestrator-xxxxx-ew.a.run.app
QUEUE_ID=horse-racing-queue
SCHEDULER_SA_EMAIL=scheduler@your-project.iam.gserviceaccount.com
SCHEDULER_JOB_0900=daily-plan-0900

REQUIRE_AUTH=true
OIDC_AUDIENCE=

GCS_BUCKET=your-bucket-name
LOCAL_DATA_DIR=/tmp/horse_data

TIMEZONE=Europe/Paris
DAILY_SCHEDULE_HOUR=9

REQUEST_TIMEOUT=30
MAX_RETRIES=3
RATE_LIMIT_DELAY=1.0

USER_AGENT=HorseRacingAnalyzer/5.1 (Educational; contact@example.com)

GPI_BUDGET_PER_RACE=5.0
GPI_MIN_EV_PERCENT=40.0


scripts/deploy_cloud_run.sh:
-----------------------------
#!/bin/bash
set -e

PROJECT_ID=${PROJECT_ID:-"your-project"}
REGION=${REGION:-"europe-west1"}
SERVICE_NAME=${SERVICE_NAME:-"horse-racing-orchestrator"}
SA_EMAIL=${SA_EMAIL:-"${SERVICE_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"}

echo "🚀 Building image..."
gcloud builds submit --tag gcr.io/${PROJECT_ID}/${SERVICE_NAME}

echo "🚀 Deploying to Cloud Run..."
gcloud run deploy ${SERVICE_NAME} \\
  --image gcr.io/${PROJECT_ID}/${SERVICE_NAME} \\
  --platform managed \\
  --region ${REGION} \\
  --service-account ${SA_EMAIL} \\
  --no-allow-unauthenticated \\
  --memory 2Gi \\
  --cpu 2 \\
  --timeout 300 \\
  --set-env-vars PROJECT_ID=${PROJECT_ID},REGION=${REGION}

SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --region ${REGION} --format 'value(status.url)')
echo "✅ Service deployed: ${SERVICE_URL}"

echo "🔐 Setting IAM invoker for scheduler SA..."
gcloud run services add-iam-policy-binding ${SERVICE_NAME} \\
  --region ${REGION} \\
  --member "serviceAccount:${SA_EMAIL}" \\
  --role "roles/run.invoker"

echo "✅ Deployment complete!"


scripts/create_scheduler_0900.sh:
----------------------------------
#!/bin/bash
set -e

PROJECT_ID=${PROJECT_ID:-"your-project"}
REGION=${REGION:-"europe-west1"}
SERVICE_NAME=${SERVICE_NAME:-"horse-racing-orchestrator"}
SA_EMAIL=${SA_EMAIL:-"${SERVICE_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"}
JOB_NAME=${JOB_NAME:-"daily-plan-0900"}

SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --region ${REGION} --format 'value(status.url)')

echo "Creating Cloud Scheduler job: ${JOB_NAME}"

gcloud scheduler jobs create http ${JOB_NAME} \\
  --location ${REGION} \\
  --schedule "0 9 * * *" \\
  --time-zone "Europe/Paris" \\
  --uri "${SERVICE_URL}/schedule" \\
  --http-method POST \\
  --headers "Content-Type=application/json" \\
  --message-body '{"date":"today","mode":"tasks"}' \\
  --oidc-service-account-email ${SA_EMAIL} \\
  --oidc-token-audience ${SERVICE_URL}

echo "✅ Scheduler job created: ${JOB_NAME}"
echo "   Schedule: Every day at 09:00 Europe/Paris"
echo "   Target: ${SERVICE_URL}/schedule"
"""
