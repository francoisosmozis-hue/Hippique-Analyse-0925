"""Wrapper around legacy scripts to execute a single course analysis."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:  # pragma: no cover - imported lazily in tests
    from google.cloud import storage  # type: ignore
except Exception:  # pragma: no cover - optional dependency in unit tests
    storage = None  # type: ignore

from .config import get_settings
from .logging_utils import get_logger, log_exception

LOGGER = get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = [
    "analyse_courses_du_jour_enrichie.py",
    "online_fetch_zeturf.py",
    "fetch_je_stats.py",
    "fetch_je_chrono.py",
    "p_finale_export.py",
    "simulate_ev.py",
    "pipeline_run.py",
]
POST_SCRIPTS = [
    "get_arrivee_geny.py",
    "update_excel_with_results.py",
]
COURSE_DETAILS_RE = re.compile(
    r"/course/(?P<date>\d{4}-\d{2}-\d{2})/R(?P<r>\d+)C(?P<c>\d+)",
    re.IGNORECASE,
)
ARTIFACT_PATTERNS = ("*.json", "*.csv", "*.xlsx")
ARTIFACT_DIRECTORIES = (Path("data"), Path("exports"), Path("output"))
DEFAULT_TIMEOUT = int(os.getenv("RUNNER_TIMEOUT", "1800"))


def _normalise_phase(phase: str) -> str:
    value = phase.replace("-", "").upper()
    if value not in {"H30", "H5"}:
        raise ValueError(f"Unsupported phase: {phase}")
    return value


def _script_path(name: str) -> Optional[Path]:
    candidate = REPO_ROOT / name
    if candidate.exists():
        return candidate
    return None


def _build_command(
    script: Path,
    course_url: str,
    phase: str,
    *,
    run_dir: Path,
) -> List[str]:
    base = [sys.executable, str(script)]
    phase_flag = phase.replace("H", "h")
    if script.name == "analyse_courses_du_jour_enrichie.py":
        return base + ["--course-url", course_url, "--phase", phase]
    if script.name == "online_fetch_zeturf.py":
        out_path = run_dir / f"snapshot_{phase}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        return base + [
            "--mode",
            phase_flag,
            "--reunion-url",
            course_url,
            "--out",
            str(out_path),
        ]
    if script.name in {"fetch_je_stats.py", "fetch_je_chrono.py"}:
        snapshot = run_dir / f"snapshot_{phase}.json"
        return base + ["--snapshot", str(snapshot)]
    if script.name in {"p_finale_export.py", "simulate_ev.py"}:
        return base + ["--phase", phase]
    if script.name == "pipeline_run.py":
        return base + ["--phase", phase, "--course-url", course_url]
    return base


def _extract_identifiers(course_url: str) -> Dict[str, str]:
    match = COURSE_DETAILS_RE.search(course_url)
    if not match:
        raise ValueError(f"Unable to parse race identifiers from URL: {course_url}")
    return {
        "date": match.group("date"),
        "r": str(int(match.group("r"))),
        "c": str(int(match.group("c"))),
    }


def _collect_artifacts() -> List[Path]:
    found: List[Path] = []
    for directory in ARTIFACT_DIRECTORIES:
        if not directory.exists():
            continue
        for pattern in ARTIFACT_PATTERNS:
            found.extend(directory.rglob(pattern))
    return found


def _upload_artifacts(paths: List[Path], *, prefix: str, bucket_name: str) -> List[str]:
    if storage is None:  # pragma: no cover - optional during tests
        raise RuntimeError("google-cloud-storage is not available")
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    uploaded: List[str] = []
    for path in paths:
        if not path.is_file():
            continue
        blob_name = f"{prefix}/{path.name}" if prefix else path.name
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(path)
        uploaded.append(blob.public_url or blob.name)
    return uploaded


def run_course(
    course_url: str,
    phase: str,
    extra_env: Optional[Dict[str, str]] = None,
) -> Dict[str, object]:
    """Execute the legacy analysis chain for a single course."""

    settings = get_settings()
    phase = _normalise_phase(phase)
    identifiers = _extract_identifiers(course_url)
    run_dir = settings.resolved_data_dir / f"{identifiers['date']}_r{identifiers['r']}c{identifiers['c']}"
    run_dir.mkdir(parents=True, exist_ok=True)
    
    env = os.environ.copy()
    env.setdefault("COURSE_URL", course_url)
    env.setdefault("PHASE", phase)
    env.setdefault("COURSE_DATE", identifiers["date"])
    env.setdefault("RUN_DATE", identifiers["date"])
    env.setdefault("PLAN_DATE", identifiers["date"])
    env.setdefault("TZ", settings.timezone)
    if extra_env:
        env.update(extra_env)
        
    logs: List[str] = []
    LOGGER.info(
        "run_started",
        extra={
            "course_url": course_url,
            "phase": phase,
            "correlation": f"r{identifiers['r']}c{identifiers['c']}",
        },
    )
    
    for script_name in SCRIPTS:
        script = _script_path(script_name)
        if not script:
            LOGGER.info("script_missing", extra={"script": script_name})
            continue
        cmd = _build_command(script, course_url, phase, run_dir=run_dir)
        LOGGER.info("running_script", extra={"script": script_name, "cmd": cmd})
        try:
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=DEFAULT_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            LOGGER.error(
                "script_timeout",
                extra={"script": script_name, "timeout": DEFAULT_TIMEOUT},
            )
            logs.append(f"[{script_name}] timeout after {DEFAULT_TIMEOUT}s")
            return {
                "ok": False,
                "rc": 124,
                "stdout_tail": "\n".join(logs)[-4000:],
                "artifacts": [],
            }
        logs.append(_format_command_output(script_name, result.stdout, result.stderr, result.returncode))
        if result.returncode != 0:
            LOGGER.error(
                "script_failed",
                extra={"script": script_name, "returncode": result.returncode},
            )
            return {
                "ok": False,
                "rc": result.returncode,
                "stdout_tail": "\n".join(logs)[-4000:],
                "artifacts": [],
            }

    artifacts = _collect_artifacts()

    if extra_env and extra_env.get("POST_RESULTS") == "1":
        for script_name in POST_SCRIPTS:
            script = _script_path(script_name)
            if not script:
                continue
            cmd = [sys.executable, str(script)]
            LOGGER.info("post_script", extra={"script": script_name})
            try:
                subprocess.run(cmd, env=env, check=False)
            except Exception as exc:  # pragma: no cover - defensive
                log_exception(LOGGER, "post_script_failed", extra={"script": script_name, "error": str(exc)})

    artifact_paths = [str(path) for path in artifacts]
    uploaded_refs: List[str] = []
    if settings.gcs_bucket:
        prefix = settings.gcs_prefix.strip("/") if settings.gcs_prefix else ""
        slug = f"runs/{identifiers['date']}/r{identifiers['r']}c{identifiers['c']}/{phase.lower()}"
        prefix = f"{prefix}/{slug}" if prefix else slug
        try:
            uploaded_refs = _upload_artifacts(artifacts, prefix=prefix, bucket_name=settings.gcs_bucket)
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.warning("artifact_upload_failed", extra={"error": str(exc)})

    LOGGER.info(
        "run_completed",
        extra={
            "course_url": course_url,
            "phase": phase,
            "artifacts": len(artifact_paths),
        },
    )
    
    return {
        "ok": True,
        "rc": 0,
        "stdout_tail": "\n".join(logs)[-4000:],
        "artifacts": artifact_paths,
        "uploaded": uploaded_refs,
    }


def _format_command_output(script: str, stdout: str, stderr: str, rc: int) -> str:
    output = [f"[{script}] rc={rc}"]
    if stdout:
        output.append(stdout.strip())
    if stderr:
        output.append(f"STDERR:\n{stderr.strip()}")
    return "\n".join(output)


__all__ = ["run_course"]
