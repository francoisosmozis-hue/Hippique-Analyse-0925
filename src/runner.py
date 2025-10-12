"""Wrapper around legacy scripts to execute a single course analysis."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

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


def _script_path(name: str) -> Path | None:
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
) -> list[str]:
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


def _extract_identifiers(course_url: str) -> dict[str, str]:
    match = COURSE_DETAILS_RE.search(course_url)
    if not match:
        raise ValueError(f"Cannot parse course URL: {course_url}")
    return {
        "date": match.group("date"),
        "r": match.group("r"),
        "c": match.group("c"),
        "rc_label": f"R{match.group('r')}C{match.group('c')}",
    }


def run_course(  # noqa: PLR0912, PLR0915
    course_url: str,
    phase: str,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    phase_norm = _normalise_phase(phase)
    try:
        ids = _extract_identifiers(course_url)
    except ValueError as exc:
        LOGGER.error("invalid_course_url", extra={"url": course_url, "error": str(exc)})
        return {
            "ok": False,
            "rc": 1,
            "stdout_tail": f"Error: {exc}",
            "artifacts": [],
            "uploaded": None,
        }

    rc_label = ids["rc_label"]
    run_dir = settings.resolved_data_dir / rc_label
    run_dir.mkdir(parents=True, exist_ok=True)
    
    env = os.environ.copy()
    env.update({
        "COURSE_URL": course_url,
        "PHASE": phase_norm,
        "RC_DIR": str(run_dir),
        "DATA_DIR": str(settings.resolved_data_dir),
        "TZ": settings.timezone,
    })
    if extra_env:
        env.update(extra_env)
        
    artifacts: list[str] = []
    stdout_lines: list[str] = []
    overall_rc = 0
    
    for script_name in SCRIPTS:
        script_path = _script_path(script_name)
        if not script_path:
            LOGGER.warning("script_not_found", extra={"script": script_name, "rc_label": rc_label})
            continue
        cmd = _build_command(script_path, course_url, phase_norm, run_dir=run_dir)
        try:
            result = subprocess.run(
                cmd, env=env, capture_output=True, text=True,
                timeout=DEFAULT_TIMEOUT, check=False
            )
            if result.stdout:
                stdout_lines.extend(result.stdout.splitlines()[-50:])
            if result.returncode != 0:
                LOGGER.error("script_failed", extra={
                    "script": script_name, "rc": result.returncode,
                    "stderr_tail": result.stderr[-500:] if result.stderr else "",
                    "rc_label": rc_label,
                })
                overall_rc = result.returncode
            else:
                LOGGER.info("script_success", extra={"script": script_name, "rc_label": rc_label})
        except subprocess.TimeoutExpired:
            LOGGER.error(
                "script_timeout",
                extra={
                    "script": script_name,
                    "timeout": DEFAULT_TIMEOUT,
                    "rc_label": rc_label,
                },
            )
            overall_rc = 124
        except Exception:
            log_exception(
                LOGGER,
                "script_exception",
                extra={"script": script_name, "rc_label": rc_label},
            )
            overall_rc = 1

    for artifact_dir in ARTIFACT_DIRECTORIES:
        abs_dir = REPO_ROOT / artifact_dir
        if not abs_dir.exists():
            continue
        for pattern in ARTIFACT_PATTERNS:
            for path in abs_dir.glob(f"**/{pattern}"):
                if rc_label in str(path):
                    artifacts.append(str(path.relative_to(REPO_ROOT)))

    uploaded = None
    if settings.gcs_bucket and storage:
        uploaded = []
        try:
            client = storage.Client()
            bucket = client.bucket(settings.gcs_bucket)
            for artifact in artifacts:
                artifact_path = REPO_ROOT / artifact
                if not artifact_path.exists():
                    LOGGER.warning("artifact_missing", extra={"path": artifact})
                    continue
                prefix = settings.gcs_prefix.strip("/") if settings.gcs_prefix else ""
                blob_name = f"{prefix}/{artifact}".strip("/")
                try:
                    bucket.blob(blob_name).upload_from_filename(str(artifact_path))
                    uploaded.append(blob_name)
                    LOGGER.info("artifact_uploaded", extra={"blob": blob_name})
                except Exception as exc:
                    LOGGER.warning(
                        "artifact_upload_failed",
                        extra={"artifact": artifact, "error": str(exc)},
                    )
            LOGGER.info(
                "gcs_upload_complete",
                extra={"rc_label": rc_label, "uploaded_count": len(uploaded)},
            )
        except Exception:
            log_exception(LOGGER, "gcs_upload_error", extra={"rc_label": rc_label})

    return {
        "ok": overall_rc == 0,
        "rc": overall_rc,
        "stdout_tail": "\n".join(stdout_lines[-20:]),
        "artifacts": artifacts,
        "uploaded": uploaded,
    }


__all__ = ["run_course"]
