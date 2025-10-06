#!/usr/bin/env python3
"""Run scheduled H-30 and H-5 windows based on a planning file.

This lightweight runner loads the day's planning and for each race determines
whether the start time falls within the configured H-30 or H-5 windows.  When a
window matches, snapshot/analysis files are written under the designated
directories.  The analysis step now leverages :func:`simulate_ev_batch` and
``validate_ev`` to compute and validate EV/ROI metrics.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError
from pydantic import field_validator

from scripts import online_fetch_zeturf as ofz
from scripts.gcs_utils import disabled_reason, is_gcs_enabled
from simulate_ev import simulate_ev_batch
from simulate_wrapper import PAYOUT_CALIBRATION_PATH
from validator_ev import ValidationError, validate_ev

logger = logging.getLogger(__name__)

USE_GCS = is_gcs_enabled()
if USE_GCS:
    try:
        from scripts.drive_sync import upload_file
    except Exception as exc:  # pragma: no cover - optional dependency guards
        logger.warning("Cloud storage sync unavailable, disabling uploads: %s", exc)
        upload_file = None  # type: ignore[assignment]
        USE_GCS = False
else:  # pragma: no cover - simple fallback when Drive is disabled
    upload_file = None  # type: ignore[assignment]


class PayloadValidationError(RuntimeError):
    """Raised when the runner payload fails validation."""


_VALID_PHASES = {"H30", "H5", "RESULT"}


class RunnerPayload(BaseModel):
    """Schema validating runner invocations coming from CLI or planning."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id_course: str = Field(validation_alias=AliasChoices("id_course", "course_id"))
    reunion: str = Field(validation_alias=AliasChoices("reunion", "meeting", "R"))
    course: str = Field(validation_alias=AliasChoices("course", "race", "C"))
    phase: str = Field(validation_alias=AliasChoices("phase", "when"))
    start_time: dt.datetime = Field(
        validation_alias=AliasChoices("start_time", "time", "start")
    )
    budget: float = Field(
        validation_alias=AliasChoices("budget", "budget_total", "bankroll"),
        ge=1.0,
        le=10.0,
    )

    @field_validator("id_course")
    @classmethod
    def _validate_course_id(cls, value: str) -> str:
        text = str(value).strip()
        if not text or not text.isdigit() or len(text) < 6:
            raise ValueError(
                "id_course must be a numeric string with at least 6 digits"
            )
        return text

    @field_validator("reunion")
    @classmethod
    def _validate_reunion(cls, value: str) -> str:
        text = str(value).strip().upper()
        if not text:
            raise ValueError("reunion is required")
        if not text.startswith("R"):
            text = f"R{text}"
        if not text[1:].isdigit():
            raise ValueError("reunion must match pattern R\\d+")
        return text

    @field_validator("course")
    @classmethod
    def _validate_course(cls, value: str) -> str:
        text = str(value).strip().upper()
        if not text:
            raise ValueError("course is required")
        if not text.startswith("C"):
            text = f"C{text}"
        if not text[1:].isdigit():
            raise ValueError("course must match pattern C\\d+")
        return text

    @field_validator("phase")
    @classmethod
    def _validate_phase(cls, value: str) -> str:
        text = str(value).strip().upper().replace("-", "")
        if text not in _VALID_PHASES:
            raise ValueError(f"phase must be one of {sorted(_VALID_PHASES)}")
        return text

    @property
    def race_id(self) -> str:
        return f"{self.reunion}{self.course}"


def _coerce_payload(data: Mapping[str, Any], *, context: str) -> RunnerPayload:
    """Validate ``data`` against :class:`RunnerPayload` and normalise fields."""

    try:
        return RunnerPayload.model_validate(data)
    except PydanticValidationError as exc:
        formatted = "; ".join(
            f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        )
        raise PayloadValidationError(f"{context}: {formatted}") from exc


def _load_planning(path: Path) -> List[Dict[str, Any]]:
    """Return planning entries from ``path``.

    The planning file is expected to be a JSON array of objects containing at
    least ``id`` and ``start`` (ISO timestamp) fields.  Entries missing these
    fields are ignored.
    """
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh) or []
    if not isinstance(data, list):
        raise ValueError("Planning file must contain a list")
    return [d for d in data if isinstance(d, dict)]


def _load_sources_config() -> Dict[str, Any]:
    """Load snapshot source configuration from disk."""

    default_path = os.getenv("RUNNER_SOURCES_FILE") or os.getenv("SOURCES_FILE")
    path = Path(default_path) if default_path else Path("config/sources.yml")
    if not path.is_file():
        return {}

    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if isinstance(data, dict):
        return data
    return {}


def _write_json_file(path: Path, payload: Mapping[str, Any]) -> None:
    """Write ``payload`` as JSON to ``path`` creating parents if needed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text_file(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` creating parents if needed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_excel_update_command(
    race_dir: Path,
    *,
    arrivee_path: Path,
    tickets_path: Path | None = None,
    excel_path: str | None = None,
) -> None:
    """Persist the Excel update command mirroring :mod:`post_course` output."""

    if tickets_path is None:
        for candidate in ("tickets.json", "p_finale.json", "analysis.json"):
            maybe = race_dir / candidate
            if maybe.exists():
                tickets_path = maybe
                break
    if tickets_path is None:
        logger.warning(
            "[runner] No tickets file found in %s, skipping Excel command", race_dir
        )
        return

    excel = (
        excel_path
        or os.getenv("EXCEL_RESULTS_PATH")
        or "modele_suivi_courses_hippiques.xlsx"
    )
    cmd = (
        f"python update_excel_with_results.py "
        f'--excel "{excel}" '
        f'--arrivee "{arrivee_path}" '
        f'--tickets "{tickets_path}"\n'
    )
    _write_text_file(race_dir / "cmd_update_excel.txt", cmd)


def _write_snapshot(
    payload: RunnerPayload,
    window: str,
    base: Path,
    *,
    course_url: str | None = None,
) -> None:
    """Write a snapshot file for ``race_id`` under ``base``.

    Parameters
    ----------
    payload:
        Runner payload carrying race metadata.
    window:
        Window label (``"H30"`` or ``"H5"``).
    base:
        Base directory where snapshot files are written.
    """
    race_id = payload.race_id
    dest = base / race_id
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"snapshot_{window}.json"

    now = dt.datetime.now().isoformat()
    try:
        snapshot = ofz.fetch_race_snapshot(
            payload.reunion,
            payload.course,
            window,
        )
    except Exception as exc:
        reason = str(exc)
        logger.error(
            "[runner] Snapshot fetch failed for %s (%s): %s", race_id, window, reason
        )
        payload_out = {
            "status": "no-data",
            "rc": race_id,
            "phase": window,
            "fetched_at": now,
            "reason": reason,
        }
    else:
        payload_out = {
            "status": "ok",
            "rc": race_id,
            "phase": window,
            "fetched_at": now,
            "payload": snapshot,
        }
        logger.info("[runner] Snapshot %s (%s) fetched", race_id, window)

    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload_out, fh, ensure_ascii=False, indent=2)
    if USE_GCS and upload_file:
        try:
            upload_file(path)
        except EnvironmentError as exc:
            logger.warning("Skipping cloud upload for %s: %s", path, exc)
    else:
        reason = disabled_reason()
        detail = f"{reason}=false" if reason else "USE_GCS disabled"
        logger.info("[gcs] Skipping upload for %s (%s)", path, detail)


def _write_analysis(
    race_id: str,
    base: Path,
    *,
    budget: float,
    ev_min: float,
    roi_min: float,
    mode: str,
    calibration: Path,
    calibration_available: bool,
) -> None:
    """Compute a dummy EV/ROI analysis and write it to disk.

    When the payout calibration file is missing the combo generation is skipped
    and an ``insufficient_data`` payload mirroring the behaviour of the main
    pipeline is written instead of running the EV simulation.
    """
    dest = base / race_id
    dest.mkdir(parents=True, exist_ok=True)
    print(f"[runner] Mode={mode} RC={race_id} → {dest}")

    path = dest / "analysis.json"
    if not calibration_available:
        calibration_available = calibration.exists()
    if not calibration_available:
        logger.warning(
            "[runner] Payout calibration missing (%s); combos disabled for %s",
            calibration,
            race_id,
        )
        payload = {
            "race_id": race_id,
            "status": "insufficient_data",
            "notes": ["calibration_missing"],
            "calibration": str(calibration),
        }
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        if USE_GCS and upload_file:
            try:
                upload_file(path)
            except EnvironmentError as exc:
                logger.warning("Skipping cloud upload for %s: %s", path, exc)
        else:
            reason = disabled_reason()
            detail = f"{reason}=false" if reason else "USE_GCS disabled"
            logger.info("[gcs] Skipping upload for %s (%s)", path, detail)
        return

    tickets = [{"p": 0.5, "odds": 2.0, "stake": 1.0}]
    stats = simulate_ev_batch(tickets, bankroll=budget)
    try:
        validate_ev(float(stats.get("ev", 0.0)), None, need_combo=False)
    except ValidationError:
        return
    payload = {
        "race_id": race_id,
        "status": "ok",
        "ev": stats.get("ev"),
        "roi": stats.get("roi"),
        "green": stats.get("green"),
        "calibration": str(calibration),
    }
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    if USE_GCS and upload_file:
        try:
            upload_file(path)
        except EnvironmentError as exc:
            logger.warning("Skipping cloud upload for %s: %s", path, exc)
    else:
        reason = disabled_reason()
        detail = f"{reason}=false" if reason else "USE_GCS disabled"
        logger.info("[gcs] Skipping upload for %s (%s)", path, detail)


def _trigger_phase(
    payload: RunnerPayload,
    *,
    snap_dir: Path,
    analysis_dir: Path,
    ev_min: float,
    roi_min: float,
    mode: str,
    calibration: Path,
    calibration_available: bool,
    course_url: str | None = None,
) -> None:
    """Run snapshot and/or analysis tasks for ``phase``."""

    phase_norm = payload.phase
    race_id = payload.race_id
    budget = float(payload.budget)
    if phase_norm == "H30":
        _write_snapshot(payload, "H30", snap_dir, course_url=course_url)
        return
    if phase_norm == "H5":
        _write_snapshot(payload, "H5", snap_dir, course_url=course_url)
        _write_analysis(
            race_id,
            analysis_dir,
            budget=budget,
            ev_min=ev_min,
            roi_min=roi_min,
            mode=mode,
            calibration=calibration,
            calibration_available=calibration_available,
        )
        return
    if phase_norm == "RESULT":
        race_dir = analysis_dir / race_id
        arrivee_path = race_dir / "arrivee_officielle.json"
        race_dir.mkdir(parents=True, exist_ok=True)
        if not arrivee_path.exists():
            logger.error(
                "[KO] Arrivée absente… %s (recherché: %s)", race_id, arrivee_path
            )
            arrivee_missing = {
                "status": "missing",
                "R": payload.reunion,
                "C": payload.course,
                "date": payload.start_time.date().isoformat(),
            }
            _write_json_file(race_dir / "arrivee.json", arrivee_missing)
            header = "status;R;C;date\n"
            line = (
                f"{arrivee_missing['status']};{arrivee_missing['R']};"
                f"{arrivee_missing['C']};{arrivee_missing['date']}\n"
            )
            _write_text_file(race_dir / "arrivee_missing.csv", header + line)
            return
        _write_excel_update_command(
            race_dir,
            arrivee_path=arrivee_path,
        )
        return

    logger.info("No handler registered for phase %s (race %s)", phase_norm, race_id)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run H-30 and H-5 windows from planning information"
    )
    parser.add_argument("--planning", help="Path to planning JSON file")
    parser.add_argument("--course-id", help="Numeric course identifier (>= 6 digits)")
    parser.add_argument("--reunion", help="Reunion identifier (e.g. R1)")
    parser.add_argument("--course", help="Course identifier (e.g. C3)")
    parser.add_argument("--phase", help="Phase to execute (H30, H5 or RESULT)")
    parser.add_argument("--start-time", help="Race start time (ISO 8601)")
    parser.add_argument(
        "--course-url",
        "--reunion-url",
        dest="course_url",
        help="Direct ZEturf course URL overriding rc_map lookups",
    )
    parser.add_argument("--h30-window-min", type=int, default=27)
    parser.add_argument("--h30-window-max", type=int, default=33)
    parser.add_argument("--h5-window-min", type=int, default=3)
    parser.add_argument("--h5-window-max", type=int, default=7)
    parser.add_argument("--snap-dir", default="data/snapshots")
    parser.add_argument("--analysis-dir", default="data/analyses")
    parser.add_argument("--budget", type=float, default=5.0)
    parser.add_argument("--ev-min", type=float, default=0.35)
    parser.add_argument("--roi-min", type=float, default=0.25)
    parser.add_argument("--pastille-rule", default="", help="Unused placeholder")
    parser.add_argument("--gpi-config", default="", help="Path to GPI config (unused)")
    parser.add_argument(
        "--calibration",
        default=str(PAYOUT_CALIBRATION_PATH),
        help="Path to payout_calibration.yaml used for combo validation.",
    )
    parser.add_argument(
        "--mode", default="hminus5", help="Mode de traitement (log only)"
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Répertoire de sortie prioritaire (fallback vers $OUTPUT_DIR puis --analysis-dir)",
    )
    args = parser.parse_args()

    snap_dir = Path(args.snap_dir)
    analysis_root = args.output or os.getenv("OUTPUT_DIR") or args.analysis_dir
    analysis_dir = Path(analysis_root)
    calibration_path = Path(args.calibration).expanduser()
    calibration_exists = calibration_path.exists()

    if args.planning:
        for name in (
            "course_id",
            "reunion",
            "course",
            "phase",
            "start_time",
            "course_url",
        ):
            if getattr(args, name):
                parser.error("--planning cannot be combined with single-race options")

        planning_path = Path(args.planning)
        if not planning_path.is_file():
            parser.error(
                "Planning file "
                f"{planning_path} not found. "
                "Generate it with: python scripts/online_fetch_zeturf.py --mode planning --out "
                "data/planning/<date>.json"
            )

        planning = _load_planning(planning_path)
        now = dt.datetime.now()

        try:
            for entry in planning:
                context_id = (
                    entry.get("id_course")
                    or entry.get("course_id")
                    or entry.get("idcourse")
                    or entry.get("courseId")
                    or entry.get("id")
                )
                rc_label = str(entry.get("id") or entry.get("rc") or "").strip().upper()
                reunion = entry.get("reunion") or entry.get("meeting")
                course = entry.get("course") or entry.get("race")
                if not reunion or not course:
                    if rc_label:
                        match = re.match(r"^(R\d+)(C\d+)$", rc_label)
                        if match:
                            reunion = reunion or match.group(1)
                            course = course or match.group(2)
                start = (
                    entry.get("start") or entry.get("time") or entry.get("start_time")
                )
                if not (reunion and course and start and context_id):
                    logger.error(
                        "[runner] Invalid planning entry skipped: missing labels/id_course (%s)",
                        entry,
                    )
                    raise SystemExit(1)
                try:
                    start_time = dt.datetime.fromisoformat(start)
                except ValueError:
                    logger.error(
                        "[runner] Invalid ISO timestamp for planning entry %s", entry
                    )
                    raise SystemExit(1)
                delta = (start_time - now).total_seconds() / 60
                if args.h30_window_min <= delta <= args.h30_window_max:
                    payload_dict = {
                        "id_course": context_id,
                        "reunion": reunion,
                        "course": course,
                        "phase": "H30",
                        "start": start,
                        "budget": entry.get("budget", args.budget),
                    }
                    payload = _coerce_payload(
                        payload_dict, context=f"planning:{context_id}:H30"
                    )
                    _trigger_phase(
                        payload,
                        snap_dir=snap_dir,
                        analysis_dir=analysis_dir,
                        ev_min=args.ev_min,
                        roi_min=args.roi_min,
                        mode=args.mode,
                        calibration=calibration_path,
                        calibration_available=calibration_exists,
                    )
                if args.h5_window_min <= delta <= args.h5_window_max:
                    payload_dict = {
                        "id_course": context_id,
                        "reunion": reunion,
                        "course": course,
                        "phase": "H5",
                        "start": start,
                        "budget": entry.get("budget", args.budget),
                    }
                    payload = _coerce_payload(
                        payload_dict, context=f"planning:{context_id}:H5"
                    )
                    _trigger_phase(
                        payload,
                        snap_dir=snap_dir,
                        analysis_dir=analysis_dir,
                        ev_min=args.ev_min,
                        roi_min=args.roi_min,
                        mode=args.mode,
                        calibration=calibration_path,
                        calibration_available=calibration_exists,
                    )
        except PayloadValidationError as exc:
            logger.error("[runner] %s", exc)
            raise SystemExit(1) from exc
        return

    missing = [
        name
        for name in ("course_id", "reunion", "course", "phase", "start_time")
        if not getattr(args, name)
    ]
    if missing:
        parser.error(
            "Missing required options for single-race mode: "
            + ", ".join(f"--{m}" for m in missing)
        )

    payload_dict = {
        "id_course": args.course_id,
        "reunion": args.reunion,
        "course": args.course,
        "phase": args.phase,
        "start_time": args.start_time,
        "budget": args.budget,
    }
    try:
        payload = _coerce_payload(payload_dict, context="cli")
    except PayloadValidationError as exc:
        logger.error("[runner] %s", exc)
        raise SystemExit(1) from exc

    try:
        _trigger_phase(
            payload,
            snap_dir=snap_dir,
            analysis_dir=analysis_dir,
            ev_min=args.ev_min,
            roi_min=args.roi_min,
            mode=args.mode,
            calibration=calibration_path,
            calibration_available=calibration_exists,
            course_url=args.course_url,
        )
    except PayloadValidationError as exc:
        logger.error("[runner] %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
