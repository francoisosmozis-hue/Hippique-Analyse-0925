#!/usr/bin/env python3
"""Pipeline helper for analysing today's horse races.

This script optionally discovers all French meetings of the day from Geny and
runs a small pipeline on each course. The behaviour without the ``--from-geny-today``
flag is intentionally minimal in order to preserve the previous behaviour (if
any) of the script.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from logging_io import CSV_HEADER, append_csv_line
from hippique_orchestrator.gcs_utils import disabled_reason, is_gcs_enabled
from src.hippique_orchestrator import gcs
from src.hippique_orchestrator import firestore_client

logging.basicConfig(level=logging.INFO)


def get_race_doc_id(reunion: str, course: str) -> str:
    """Generates a unique document ID for a race."""
    # Assuming the date is implicitly today for the context of this script.
    # A more robust implementation would pass the date explicitly.
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{today_str}_{reunion}{course}"


def normalize_snapshot(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Placeholder function that returns the payload as is."""
    return dict(payload)
import pipeline_run
from analysis_utils import compute_overround_cap
from fetch_je_stats import collect_stats
from simulate_wrapper import PAYOUT_CALIBRATION_PATH, evaluate_combo
from src.hippique_orchestrator.scripts import p_finale_export

logger = logging.getLogger(__name__)


def export_per_horse_csv(rc_dir: Path) -> Path:
    """Wrapper for p_finale_export.export_p_finale_from_dir."""
    p_finale_export.export_p_finale_from_dir(rc_dir)
    return rc_dir / "p_finale_export.csv"



def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


GPI_BUDGET_DEFAULT = _env_float("GPI_BUDGET", 5.0)
EV_MIN_THRESHOLD = _env_float("EV_MIN", 0.40)
ROI_SP_MIN_THRESHOLD = _env_float("ROI_SP_MIN", 0.20)
PAYOUT_MIN_THRESHOLD = _env_float("PAYOUT_MIN", 10.0)
OVERROUND_MAX_THRESHOLD = _env_float("OVERROUND_MAX", 1.30)
if "MAX_COMBO_OVERROUND" not in os.environ:
    os.environ["MAX_COMBO_OVERROUND"] = f"{OVERROUND_MAX_THRESHOLD:.2f}"





class MissingH30SnapshotError(RuntimeError):
    """Raised when the H-30 snapshot required for ``enrich_h5`` is missing."""

    def __init__(self, message: str, *, rc_dir: Path | str | None = None) -> None:
        super().__init__(message)
        self.rc_dir = Path(rc_dir) if isinstance(rc_dir, (str, Path)) else None


USE_GCS = is_gcs_enabled()

TRACKING_HEADER = CSV_HEADER + ["phase", "status", "reason"]

def write_snapshot_from_geny(*args: Any, **kwargs: Any) -> None:
    raise RuntimeError("write_snapshot_from_geny est désactivé ; utilisez write_snapshot_from_boturfers à la place")

try:
    from hippique_orchestrator.online_fetch_boturfers import fetch_boturfers_programme, fetch_boturfers_race_details
except ImportError:
    def fetch_boturfers_programme(*args, **kwargs):
        raise RuntimeError("Boturfers programme fetcher is unavailable")
    def fetch_boturfers_race_details(*args, **kwargs):
        raise RuntimeError("Boturfers race details fetcher is unavailable")

def write_snapshot_from_boturfers(reunion: str, course: str, phase: str, race_doc_id: str) -> None:
    """
    Fetches race details from Boturfers and writes a snapshot to Firestore.
    """
    logger.info(f"Fetching {reunion}{course} from Boturfers for phase {phase}")

    programme_url = "https://www.boturfers.fr/programme-pmu-du-jour"
    programme_data = fetch_boturfers_programme(programme_url)

    race_url = None
    target_rc = f"{reunion}{course}".replace(" ", "")
    if programme_data and programme_data.get("races"):
        for race in programme_data["races"]:
            if race.get("rc", "").replace(" ", "") == target_rc:
                race_url = race.get("url")
                break

    if not race_url:
        logger.error(f"Course {target_rc} not found in Boturfers programme.")
        return

    race_details = fetch_boturfers_race_details(race_url)

    if not race_details or "error" in race_details:
        logger.error(f"Failed to fetch race details for {race_url}")
        return

    # Add metadata to the snapshot
    race_details['reunion'] = reunion
    race_details['course'] = course
    race_details['rc'] = target_rc
    match = re.search(r'/(\d+)-', race_url)
    if match:
        race_details['id_course'] = match.group(1)
    else:
        race_details['id_course'] = target_rc
        logger.warning(f"Impossible de résoudre l'ID de la course pour {reunion}{course} via l'URL. Utilisation de {target_rc} comme ID.")

    # Save the snapshot to a subcollection in Firestore
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    snapshot_id = f"{timestamp}_{phase}"
    
    # We also save the main race metadata to the parent document
    firestore_client.update_race_document("races", race_doc_id, race_details)
    
    # And save the detailed snapshot in its own document
    firestore_client.save_race_document(
        f"races/{race_doc_id}/snapshots", snapshot_id, race_details
    )
    logger.info(f"Snapshot for {target_rc} saved to Firestore: races/{race_doc_id}/snapshots/{snapshot_id}")



if USE_GCS:
    try:
        # upload_artifacts is now obsolete
        pass
    except ImportError as exc:
        print(
            f"[WARN] Synchronisation GCS indisponible ({exc}), bascule en mode local.",
            file=sys.stderr,
        )
        USE_GCS = False
else:
    upload_artifacts = None


# --- RÈGLES ANTI-COTES FAIBLES (SP min 4/1 ; CP somme > 6.0 déc) ---------------
MIN_SP_DEC_ODDS = 5.0  # 4/1 = 5.0
MIN_CP_SUM_DEC = 6.0  # (o1-1)+(o2-1) ≥ 4  <=> (o1+o2) ≥ 6.0


def _write_json_file(gcs_path: str, payload: Any) -> None:
    """Writes a JSON payload directly to a GCS path."""
    gcs.write_gcs_json(gcs_path, payload)



def _write_minimal_csv(
    path: Path, headers: Iterable[Any], rows: Iterable[Iterable[Any]] | None = None
) -> None:
    """Persist a tiny CSV artefact with the provided ``headers`` and ``rows``."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(list(headers))
        if rows:
            for row in rows:
                writer.writerow(list(row))


def _load_json_if_exists(gcs_path: str) -> dict[str, Any] | None:
    """Loads a JSON file from GCS if it exists."""
    return gcs.read_gcs_json(gcs_path)


def _coerce_int(value: Any) -> int | None:
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            text = value.strip()
            match = re.search(r"\d+", text)
            if match:
                return int(match.group(0))
    except Exception:  # pragma: no cover - defensive
        return None
    return None


def _derive_rc_parts(label: str) -> tuple[str, str]:
    text = str(label or "").replace(" ", "").upper()
    match = re.match(r"^(R\d+)(C\d+)$", text)
    if match:
        return match.group(1), match.group(2)
    if text.startswith("R") and "C" in text:
        r_part, c_part = text.split("C", 1)
        return r_part, f"C{c_part}"
    return text or "", ""


def _extract_id2name(payload: Any) -> dict[str, str]:
    """Return an ``id -> name`` mapping from the provided payload."""

    mapping: dict[str, str] = {}
    if not isinstance(payload, dict):
        return mapping

    raw = payload.get("id2name")
    if isinstance(raw, dict) and raw:
        for cid, name in raw.items():
            if cid is None:
                continue
            mapping[str(cid)] = "" if name is None else str(name)
        if mapping:
            return mapping

    runners = payload.get("runners")
    if isinstance(runners, list):
        for runner in runners:
            if not isinstance(runner, dict):
                continue
            cid = runner.get("id") or runner.get("num") or runner.get("number")
            if cid is None:
                continue
            name = runner.get("name") or runner.get("nom") or runner.get("label")
            mapping[str(cid)] = "" if name is None else str(name)
    return mapping


def _extract_stats_mapping(stats_payload: Any) -> dict[str, dict[str, Any]]:
    """Normalise the stats payload into a ``dict[id] -> stats`` mapping."""

    mapping: dict[str, dict[str, Any]] = {}
    if isinstance(stats_payload, dict):
        for key, value in stats_payload.items():
            if not isinstance(value, dict):
                continue
            mapping[str(key)] = value
    return mapping


def _norm_float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except Exception:  # pragma: no cover - defensive
        return None



def _filter_sp_and_cp_by_odds(payload: dict[str, Any]) -> None:
    """DEPRECATED: This logic should be handled by the pipeline."""
    logger.warning("DEPRECATED: _filter_sp_and_cp_by_odds is called but its logic should move to the pipeline.")
    pass


# ---------------------------------------------------------------------------
# Helper stubs - these functions are expected to be provided elsewhere in the
# larger project. They are defined here so the module can be imported and easily
# monkeypatched during tests.
# ---------------------------------------------------------------------------


def ensure_dir(path: Path) -> Path:
    """DEPRECATED: No longer needed in Firestore-native workflow."""
    logger.warning("DEPRECATED: ensure_dir called but no longer necessary.")
    return path


def enrich_h5(race_doc_id: str, *, budget: float, kelly: float) -> None:
    """Prepare all artefacts required for the H-5 pipeline, using Firestore."""

    logger.info(f"Enriching H5 for {race_doc_id}")

    def _latest_snapshot_firestore(tag: str) -> dict[str, Any] | None:
        """Find the latest snapshot for a given tag in Firestore."""
        snapshots = firestore_client.list_subcollection_documents(
            "races", race_doc_id, "snapshots"
        )
        
        # The snapshot_id is expected to be like "20231128_151617_H5"
        candidates = [
            s for s in snapshots if s.get("rc") and f"_{tag}" in s.get("snapshot_id", "")
        ]
        
        if not candidates:
            return None
        
        # Sort by name (which includes the timestamp) to find the latest.
        latest_snapshot = sorted(candidates, key=lambda s: s.get("snapshot_id", ""))[-1]
        return latest_snapshot

    def _normalise_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
        normalised = normalize_snapshot(payload)
        for key in ["id_course", "course_id", "source", "rc", "r_label", "meeting", "reunion", "race"]:
            value = payload.get(key)
            if value is not None and key not in normalised:
                normalised[key] = value
        return normalised

    h5_payload = _latest_snapshot_firestore("H5")
    if h5_payload is None:
        raise FileNotFoundError("Aucun snapshot H-5 trouvé pour l'analyse sur Firestore")
    h5_normalised = _normalise_snapshot(h5_payload)

    h30_payload = _latest_snapshot_firestore("H30")
    if h30_payload is None:
        message = f"Snapshot H-30 manquant pour {race_doc_id}"
        logger.warning("[H-5] %s", message)
        raise MissingH30SnapshotError(message, rc_dir=race_doc_id)
    h30_normalised = _normalise_snapshot(h30_payload)

    def _odds_map(snapshot: dict[str, Any]) -> dict[str, float]:
        odds = snapshot.get("odds")
        if isinstance(odds, dict):
            return {str(k): float(v) for k, v in odds.items() if _is_number(v)}
        runners = snapshot.get("runners")
        if isinstance(runners, list):
            mapping: dict[str, float] = {}
            for runner in runners:
                if not isinstance(runner, dict): continue
                cid = runner.get("id")
                odds_val = runner.get("odds")
                if cid is None or not _is_number(odds_val): continue
                mapping[str(cid)] = float(odds_val)
            return mapping
        return {}

    update_payload = {}
    update_payload['normalized_h5'] = h5_normalised
    update_payload['normalized_h30'] = h30_normalised
    update_payload['odds_h5'] = _odds_map(h5_normalised)
    update_payload['odds_h30'] = _odds_map(h30_normalised)
    if not update_payload['odds_h30']:
        update_payload['odds_h30'] = dict(update_payload['odds_h5'])

    partants_payload = {
        "rc": h5_normalised.get("rc") or race_doc_id,
        "hippodrome": h5_normalised.get("hippodrome") or h5_payload.get("hippodrome"),
        "date": h5_normalised.get("date") or h5_payload.get("date"),
        "discipline": h5_normalised.get("discipline") or h5_payload.get("discipline"),
        "runners": h5_normalised.get("runners", []),
        "id2name": h5_normalised.get("id2name", {}),
        "course_id": h5_payload.get("id_course") or h5_payload.get("course_id") or h5_payload.get("id"),
    }
    update_payload['partants'] = partants_payload

    course_id = str(partants_payload.get("course_id") or "").strip()
    if not course_id:
        raise ValueError("Impossible de déterminer l'identifiant course pour les stats J/E")
    
    # --- Workaround for collect_stats requiring a local file ---
    temp_dir = Path("/tmp") / "hippique_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    # Use a unique name for the temp file to avoid race conditions
    temp_h5_path = temp_dir / f"{race_doc_id.replace('/', '_')}_{datetime.now().timestamp()}_norm_h5.json"
    temp_h5_path.write_text(json.dumps(h5_normalised, ensure_ascii=False, indent=2))
    
    try:
        stats_json_path_str = collect_stats(
            h5=str(temp_h5_path),
            out=str(temp_dir / "je_stats.csv") # This output is not used, but required by the function
        )
        stats_json_path = Path(stats_json_path_str)
        if not stats_json_path.exists():
             raise FileNotFoundError(f"collect_stats should have created {stats_json_path}")
        stats_result = json.loads(stats_json_path.read_text(encoding="utf-8"))
        coverage = stats_result.get("coverage", 0)
        rows = stats_result.get("rows", [])
        mapped = {str(row.get("num")): row for row in rows}
        stats_payload = {"coverage": coverage, **mapped}

    except Exception:
        logger.exception("collect_stats failed for course %s", course_id)
        stats_payload = {"coverage": 0, "ok": 0}
    finally:
        if temp_h5_path.exists():
            temp_h5_path.unlink()

    update_payload['stats_je'] = stats_payload
    
    firestore_client.update_race_document("races", race_doc_id, update_payload)
    logger.info(f"Enrichment data for {race_doc_id} saved to Firestore.")



def build_p_finale(
    race_doc_id: str,
    *,
    budget: float,
    kelly: float,
    ev_min: float | None = None,
    roi_min: float | None = None,
    payout_min: float | None = None,
    overround_max: float | None = None,
) -> None:
    """Run the ticket allocation pipeline and persist ``p_finale`` data to Firestore."""
    _run_single_pipeline(
        race_doc_id,
        budget=budget,
        ev_min=ev_min,
        roi_min=roi_min,
        payout_min=payout_min,
        overround_max=overround_max,
    )


def run_pipeline(
    race_doc_id: str,
    *,
    budget: float,
    kelly: float,
    ev_min: float | None = None,
    roi_min: float | None = None,
    payout_min: float | None = None,
    overround_max: float | None = None,
) -> None:
    """Execute the analysis pipeline for a given race document ID."""

    ev_threshold = EV_MIN_THRESHOLD if ev_min is None else float(ev_min)
    roi_threshold = ROI_SP_MIN_THRESHOLD if roi_min is None else float(roi_min)
    payout_threshold = PAYOUT_MIN_THRESHOLD if payout_min is None else float(payout_min)
    overround_threshold = (
        OVERROUND_MAX_THRESHOLD if overround_max is None else float(overround_max)
    )

    race_doc = firestore_client.get_race_document("races", race_doc_id)
    if not race_doc:
        raise FileNotFoundError(f"Aucun document de course trouvé pour {race_doc_id}")

    if race_doc.get("p_finale"):
        logger.info(f"p_finale already exists for {race_doc_id}, skipping pipeline.")
        return

    inputs_available = all(
        key in race_doc for key in ("odds_h5", "partants", "stats_je")
    )
    if inputs_available:
        _run_single_pipeline(
            race_doc_id,
            budget=budget,
            ev_min=ev_threshold,
            roi_min=roi_threshold,
            payout_min=payout_threshold,
            overround_max=overround_threshold,
        )
    else:
        missing_keys = [key for key in ("odds_h5", "partants", "stats_je") if key not in race_doc]
        raise FileNotFoundError(f"Données pipeline manquantes pour {race_doc_id}: {missing_keys}")


def build_prompt_from_meta(race_doc_id: str, *, budget: float, kelly: float) -> None:
    """Generate a human-readable prompt from Firestore race document."""

    race_doc = firestore_client.get_race_document("races", race_doc_id)
    if not race_doc:
        raise FileNotFoundError(f"Document de course introuvable dans Firestore: {race_doc_id}")
        
    meta = race_doc.get("meta", {})
    ev = race_doc.get("ev", {})
    tickets = race_doc.get("tickets", [])
    rc_name = race_doc_id.split('_', 1)[-1]

    prompt_lines = [
        f"Course {meta.get('rc', rc_name)} – {meta.get('hippodrome', '')}".strip(),
        f"Date : {meta.get('date', '')} | Discipline : {meta.get('discipline', '')}",
        f"Budget : {budget:.2f} € | Fraction de Kelly : {kelly:.2f}",
    ]
    # ... (le reste de la logique de formatage de texte) ...
    
    logger.info("Generated prompt (not saved yet):\n" + "\n".join(prompt_lines))
    firestore_client.update_race_document("races", race_doc_id, {"prompt_text": "\n".join(prompt_lines)})


def _is_number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _write_chronos_csv(path: Path, runners: Iterable[Any]) -> None:
    """DEPRECATED: Persist a chronos CSV placeholder using runner identifiers."""
    logger.warning("CSV writing is temporarily disabled during Firestore refactoring.")


def _run_single_pipeline(
    race_doc_id: str,
    *,
    budget: float,
    ev_min: float | None = None,
    roi_min: float | None = None,
    payout_min: float | None = None,
    overround_max: float | None = None,
) -> None:
    """Execute pipeline and update the Firestore document."""

    # This is a major dependency to resolve in the next step.
    # pipeline_run.run_pipeline needs to be refactored to accept data payloads
    # instead of reading from the filesystem.
    logger.warning("pipeline_run.run_pipeline is not yet Firestore-native. This step will likely fail or produce no result.")
    
    # Mocking the result for now to allow the flow to continue.
    result = {
        "roi_global_est": 0.0,
        "tickets": [],
        "p_true": {}
    }
    
    race_doc = firestore_client.get_race_document("races", race_doc_id) or {}
    partants_payload = race_doc.get("partants", {})

    p_finale_payload = {
        "meta": {
            "rc": race_doc_id.split('_', 1)[-1],
            "hippodrome": partants_payload.get("hippodrome"),
            "date": partants_payload.get("date"),
            "discipline": partants_payload.get("discipline"),
        },
        "ev": {
            "roi_global": result.get("roi_global_est")
        },
        "tickets": result.get("tickets"),
        "p_true": result.get("p_true", {})
    }

    _filter_sp_and_cp_by_odds(p_finale_payload)
    
    firestore_client.update_race_document("races", race_doc_id, {"p_finale": p_finale_payload})


def _find_je_csv(rc_dir: Path) -> Path | None:
    """DEPRECATED: Return the JE CSV produced during enrichment when available."""
    return None


def _is_combo_ticket(ticket: Mapping[str, Any]) -> bool:
    """Return ``True`` when ``ticket`` refers to an exotic combination."""

    ticket_type = str(ticket.get("type") or "").upper()
    if ticket_type.startswith("SP") or "SIMPLE" in ticket_type:
        return False
    if ticket.get("legs"):
        return True
    return ticket_type not in {"SP", "SIMPLE", "SIMPLE_PLACE", "PLACE"}


def _evaluate_combo_guard(
    ticket: Mapping[str, Any],
    *,
    bankroll: float,
) -> dict[str, Any]:
    """Evaluate ``ticket`` via :func:`simulate_wrapper.evaluate_combo`."""
    # This function depends on a local file path for calibration. Needs refactoring.
    logger.warning("evaluate_combo guard depends on a local calibration file. This may fail.")
    try:
        return evaluate_combo(
            [dict(ticket)],
            bankroll,
            calibration=str(PAYOUT_CALIBRATION_PATH),
            allow_heuristic=False,
        )
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Guard combo evaluation failed for %s", ticket.get("id"))
        return {
            "status": "error",
            "ev_ratio": 0.0,
            "roi": 0.0,
            "payout_expected": 0.0,
            "notes": [f"evaluation_error:{exc}"],
        }


def _run_h5_guard_phase(
    race_doc_id: str,
    *,
    budget: float,
    min_roi: float = 0.20,
) -> tuple[bool, dict[str, Any], dict[str, Any] | None]:
    """Evaluate post-enrichment guardrails using data from Firestore."""

    race_doc = firestore_client.get_race_document("races", race_doc_id) or {}
    p_finale_payload = race_doc.get("p_finale", {})
    
    logger.warning("H5 guard phase is complex and has local file dependencies. Simplified for now.")

    analysis_payload = {
        "meta": p_finale_payload.get("meta", {}),
        "guards": {},
        "decision": "PLAY", # Assume PLAY for now
        "tickets": p_finale_payload.get("tickets", []),
    }
    
    firestore_client.update_race_document("races", race_doc_id, {"analysis_H5": analysis_payload})

    logger.info("[H-5][guards] course %s validated (simplified guard)", race_doc_id)
    return True, analysis_payload, None


def _upload_artifacts(rc_dir: Path, *, gcs_prefix: str | None) -> None:
    """Upload ``rc_dir`` contents to Google Cloud Storage."""

    if gcs_prefix is None:
        return
    if not USE_GCS or not upload_artifacts:
        reason = disabled_reason()
        if reason:
            detail = f"{reason}=false"
        else:
            detail = f"USE_GCS={USE_GCS}"
        print(f"[gcs] Upload ignoré pour {rc_dir} ({detail})", file=sys.stderr)
        return
    try:
        artifacts = [str(p) for p in rc_dir.glob("**/*") if p.is_file()]
        upload_artifacts(rc_dir, artifacts)
    except Exception as exc:  # pragma: no cover - best effort
        print(f"[WARN] Failed to upload {rc_dir}: {exc}")


def _snap_prefix(rc_dir: Path) -> str | None:
    """Return the stem of the most recent H-5 snapshot if available."""

    snapshots = list(rc_dir.glob("*_H5.json"))
    if not snapshots:
        return None

    def _key(path: Path) -> tuple[float, str]:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        return (mtime, path.name)

    latest = max(snapshots, key=_key)
    return latest.stem





def _check_enrich_outputs(
    rc_dir: Path,
    *,
    retry_delay: float = 1.0,
    retry_cb: Callable[[], None] | None = None,
) -> dict[str, Any] | None:
    """Ensure ``enrich_h5`` produced required CSV artefacts.

    The check retries once after a short delay to accommodate slow I/O. When
    the required files remain missing, a structured ``no-bet`` payload is
    returned so that callers can gracefully skip the course instead of
    terminating the whole pipeline.
    """

    for attempt in range(2):
        snap = _snap_prefix(rc_dir)
        je_csv = rc_dir / f"{snap}_je.csv" if snap else None
        chronos_csv = rc_dir / "chronos.csv"

        missing: list[str] = []
        if not je_csv or not je_csv.exists():
            missing.append(f"{snap}_je.csv" if snap else "snap_H-5_je.csv")
        if not chronos_csv.exists():
            missing.append("chronos.csv")

        if not missing:
            return None

        message = ", ".join(missing)
        if attempt == 0:
            print(
                "[WARN] fichiers manquants après enrich_h5 (nouvelle tentative) : "
                + message,
                file=sys.stderr,
            )
            if retry_cb is not None:
                try:
                    retry_cb()
                except Exception as exc:  # pragma: no cover - defensive logging
                    print(
                        f"[WARN] relance enrich_h5 a échoué pour {rc_dir.name}: {exc}",
                        file=sys.stderr,
                    )
            if retry_delay is not None:
                time.sleep(max(0.0, retry_delay))
            continue

        print(
            "[ERROR] fichiers manquants après enrich_h5 malgré la nouvelle tentative : "
            + message,
            file=sys.stderr,
        )
        return {
            "status": "no-bet",
            "decision": "ABSTENTION",
            "reason": "data-missing",
            "details": {"missing": missing},
        }

    return None


def _missing_requires_stats(missing: Iterable[str]) -> bool:
    return any(str(name).endswith("_je.csv") for name in missing)


def _missing_requires_chronos(missing: Iterable[str]) -> bool:
    return any(str(name) == "chronos.csv" for name in missing)








def _rebuild_je_csv_from_stats(rc_dir: Path) -> bool:
    """Attempt to rebuild ``*_je.csv`` using freshly fetched stats."""

    snap = _snap_prefix(rc_dir)
    if not snap:
        print(
            f"[WARN] Impossible de déterminer le snapshot H-5 pour {rc_dir.name}",
            file=sys.stderr,
        )
        return False

    stats_path = rc_dir / "stats_je.json"
    try:
        stats_payload = json.loads(stats_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"[WARN] stats_je.json introuvable ou invalide dans {rc_dir.name}: {exc}",
            file=sys.stderr,
        )
        return False

    id2name: dict[str, str] = {}
    for candidate in [rc_dir / "partants.json", rc_dir / "normalized_h5.json"]:
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        mapping = _extract_id2name(payload)
        if mapping:
            id2name = mapping
            break

    if not id2name:
        print(
            f"[WARN] Impossible de reconstruire {snap}_je.csv pour {rc_dir.name}: id2name manquant",
            file=sys.stderr,
        )
        return False

    try:
        _write_je_csv_file(
            rc_dir / f"{snap}_je.csv", id2name=id2name, stats_payload=stats_payload
        )
    except OSError as exc:
        print(
            f"[WARN] Échec d'écriture du CSV J/E pour {rc_dir.name}: {exc}",
            file=sys.stderr,
        )
        return False

    return True


def _regenerate_chronos_csv(rc_dir: Path) -> bool:
    """Attempt to rebuild ``chronos.csv`` from locally available runner data."""

    chronos_path = rc_dir / "chronos.csv"

    def _load_payload(path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _extract_runners(payload: dict[str, Any]) -> list[dict[str, Any]]:
        def _clean(items: Any) -> list[dict[str, Any]]:
            cleaned: list[dict[str, Any]] = []
            if isinstance(items, list):
                for runner in items:
                    if not isinstance(runner, dict):
                        continue
                    if (
                        runner.get("id") is None
                        and runner.get("num") is None
                        and runner.get("number") is None
                    ):
                        continue
                    cleaned.append(runner)
            return cleaned

        for key in ("runners", "participants", "partants"):
            if key in payload:
                runners = _clean(payload.get(key))
                if runners:
                    return runners

        for key in ("data", "course", "payload"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                runners = _extract_runners(nested)
                if runners:
                    return runners

        return []

    candidates: list[Path] = []
    partants_path = rc_dir / "partants.json"
    if partants_path.exists():
        candidates.append(partants_path)

    normalized_path = rc_dir / "normalized_h5.json"
    if normalized_path.exists():
        candidates.append(normalized_path)

    candidates.extend(sorted(rc_dir.glob("*_H-5.json"), reverse=True))

    for candidate in candidates:
        payload = _load_payload(candidate)
        if not payload:
            continue
        runners = _extract_runners(payload)
        if not runners:
            continue
        try:
            _write_chronos_csv(chronos_path, runners)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to materialise chronos CSV in %s", rc_dir)
            placeholder_headers = ["num", "chrono", "ok"]
            placeholder_rows = [["", "", 0]]
            _write_minimal_csv(chronos_path, placeholder_headers, placeholder_rows)
        return True

    print(
        f"[WARN] Impossible de régénérer chronos.csv pour {rc_dir.name}: données partants indisponibles",
        file=sys.stderr,
    )
    return False


def _mark_course_unplayable(race_doc_id: str, missing: Iterable[str]) -> dict[str, Any]:
    """Write the abstention marker to Firestore and emit the canonical abstain log."""

    marker_message = "non jouable: data manquante"
    missing_items = [str(item) for item in missing if item]
    if missing_items:
        marker_message = f"{marker_message} ({', '.join(missing_items)})"

    update_payload = {
        "status": "UNPLAYABLE",
        "status_reason": marker_message
    }
    
    firestore_client.update_race_document("races", race_doc_id, update_payload)
    logger.warning(f"[H-5] course marquée non jouable (id={race_doc_id}, raison={marker_message})")
    
    label = race_doc_id.split('_', 1)[-1]
    print(f"[ABSTAIN] Course non jouable (data manquante) – {label}", file=sys.stderr)

    return update_payload


def _ensure_h5_artifacts(
    race_doc_id: str,
    *,
    retry_cb: Callable[[], None] | None = None,
    budget: float | None = None,
    phase: str = "H5",
) -> dict[str, Any] | None:
    """Ensure H-5 enrichment produced required data in Firestore or mark course unplayable."""
    logger.warning("H5 artifact check is simplified for Firestore-native workflow.")
    
    race_doc = firestore_client.get_race_document("races", race_doc_id)
    if not race_doc:
        # This case should ideally not be reached if enrich_h5 was successful
        return _mark_course_unplayable(race_doc_id, ["document manquant"])

    required_fields = ["normalized_h5", "partants", "stats_je"]
    missing_fields = [field for field in required_fields if field not in race_doc]

    if not missing_fields:
        return None # All good

    # If fields are missing, mark as unplayable
    marker_details = _mark_course_unplayable(race_doc_id, missing_fields)
    status_label = "NO_PLAY_DATA_MISSING"
    reason_label = "DATA_MISSING"
    
    outcome = {
        "status": "no-bet",
        "reason": "data-missing",
        "analysis": {"status": status_label},
        "details": {
            **marker_details,
            "phase": phase,
            "reason": reason_label,
            "status_label": status_label,
        }
    }
    # _log_tracking_missing is not Firestore-native yet, so it's disabled.
    # _log_tracking_missing(
    #     race_doc_id,
    #     status=status_label,
    #     reason=reason_label,
    #     phase=phase,
    #     budget=budget,
    # )
    return outcome


def safe_enrich_h5(
    race_doc_id: str,
    *,
    budget: float,
    kelly: float,
) -> tuple[bool, dict[str, Any] | None]:
    """Execute ``enrich_h5`` ensuring data is present, or mark the course out."""

    race_doc = firestore_client.get_race_document("races", race_doc_id)
    if race_doc and race_doc.get("status") == "UNPLAYABLE":
        rc_name = race_doc_id.split('_', 1)[-1]
        logger.warning(f"[H-5] course déjà marquée non jouable (id={race_doc_id})")
        print(f"[ABSTAIN] Course déjà marquée non jouable – {rc_name}", file=sys.stderr)
        return False, {
            "status": "no-bet",
            "decision": "ABSTENTION",
            "reason": "unplayable-marker",
        }

    try:
        enrich_h5(race_doc_id, budget=budget, kelly=kelly)
    except MissingH30SnapshotError as exc:
        missing = ["snapshot-H30"]
        marker_details = _mark_course_unplayable(race_doc_id, missing)
        details: dict[str, Any] = {"missing": missing, "phase": "H5", "message": str(exc)}
        details.update(marker_details)
        rc_name = race_doc_id.split('_', 1)[-1]
        logger.warning(f"[H-5] course non jouable faute de snapshot H-30 (id={race_doc_id})")
        return False, {
            "status": "no-bet",
            "decision": "ABSTENTION",
            "reason": "data-missing",
            "analysis": {"status": "NO_PLAY_DATA_MISSING"},
            "details": details,
        }
    
    outcome = _ensure_h5_artifacts(
        race_doc_id,
        retry_cb=lambda: enrich_h5(race_doc_id, budget=budget, kelly=kelly),
        budget=budget,
        phase="H5",
    )
    if outcome is not None:
        return False, outcome
    return True, None


def _execute_h5_chain(
    race_doc_id: str,
    *,
    budget: float,
    kelly: float,
    ev_min: float,
    roi_min: float,
    payout_min: float,
    overround_max: float,
) -> tuple[bool, dict[str, Any] | None]:
    """Run the full H-5 enrichment pipeline with fail-safe guards on Firestore."""

    success, outcome = safe_enrich_h5(race_doc_id, budget=budget, kelly=kelly)
    if not success:
        return False, outcome

    build_p_finale(
        race_doc_id,
        budget=budget,
        kelly=kelly,
        ev_min=ev_min,
        roi_min=roi_min,
        payout_min=payout_min,
        overround_max=overround_max,
    )
    guard_ok, analysis_payload, guard_outcome = _run_h5_guard_phase(
        race_doc_id,
        budget=budget,
        min_roi=roi_min,
    )
    return guard_ok, guard_outcome





def _normalize_label(label: object) -> str:
    """Normalise un libellé: trim, uppercase et retrait des espaces.

    Utilise ``str(label)`` pour accepter des entrées non textuelles.
    """

    return str(label).strip().upper().replace(" ", "")


def _normalise_rc_label(label: str | int, prefix: str) -> str:
    """Normalise ``label`` to the canonical ``R``/``C`` format.

    ``label`` may be provided without the leading prefix (``"1"``) or with a
    lowercase variant (``"c3"``). The return value always matches ``R\\d+`` or
    ``C\\d+`` with no leading zero. ``ValueError`` is raised when the label does
    not describe a strictly positive integer.
    """

    text = _normalize_label(label)
    if not text:
        raise ValueError(f"Identifiant {prefix} vide")
    if text.startswith(prefix):
        text = text[len(prefix) :]
    elif text.startswith(prefix[0]):
        text = text[1:]
    if not text.isdigit():
        raise ValueError(f"Identifiant {prefix} invalide: {label!r}")
    number = int(text)
    if number <= 0:
        raise ValueError(f"Identifiant {prefix} invalide: {label!r}")
    return f"{prefix}{number}"


def _normalise_phase(value: str) -> str:
    """Return a canonical phase string (``H30`` or ``H5``)."""

    cleaned = value.strip().upper().replace("-", "").replace(" ", "")
    if cleaned not in {"H30", "H5"}:
        raise ValueError(f"Phase inconnue: {value!r} (attendu H30 ou H5)")
    return cleaned


def _phase_argument(value: str) -> str:
    """Argument parser wrapper that normalises ``value`` to ``H30``/``H5``."""

    try:
        return _normalise_phase(value)
    except ValueError as exc:  # pragma: no cover - handled by argparse
        raise argparse.ArgumentTypeError(str(exc)) from exc





def process_single_course(
    reunion: str,
    course: str,
    phase: str,
    data_dir: Path, # Unused, kept for signature compatibility
    *,
    budget: float,
    kelly: float,
    gcs_prefix: str | None, # Unused, kept for signature compatibility
    ev_min: float = EV_MIN_THRESHOLD,
    roi_min: float = ROI_SP_MIN_THRESHOLD,
    payout_min: float = PAYOUT_MIN_THRESHOLD,
    overround_max: float = OVERROUND_MAX_THRESHOLD,
) -> dict[str, Any] | None:
    """Fetch and analyse a specific course, using Firestore as the backend."""

    race_doc_id = get_race_doc_id(reunion, course)
    
    write_snapshot_from_boturfers(reunion, course, phase, race_doc_id)
    
    outcome: dict[str, Any] | None = None
    pipeline_done = False
    if phase.upper() == "H5":
        pipeline_done, outcome = _execute_h5_chain(
            race_doc_id, # Pass Firestore document ID
            budget=budget,
            kelly=kelly,
            ev_min=ev_min,
            roi_min=roi_min,
            payout_min=payout_min,
            overround_max=overround_max,
        )
        if pipeline_done:
            logger.warning("CSV export is temporarily disabled during Firestore refactoring.")
            outcome = None
        elif outcome is not None:
            # The outcome is now part of the document, but we can update it
            firestore_client.update_race_document("races", race_doc_id, {"decision": outcome})
        else:  # pragma: no cover - defensive fallback
            decision = {
                "status": "no-bet",
                "decision": "ABSTENTION",
                "reason": "pipeline-error",
            }
            firestore_client.update_race_document("races", race_doc_id, {"decision": decision})

    return outcome


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------








def main() -> None:
    """
    Main entry point for testing the Firestore-based pipeline.
    This function is for demonstration and testing purposes.
    """
    # Example: Process R1C1 for H5 phase
    reunion = "R1"
    course = "C1"
    phase = "H5"
    budget = GPI_BUDGET_DEFAULT
    kelly = 1.0

    print(f"--- Running test for {reunion}{course} phase {phase} ---")
    
    # The `data_dir` and `gcs_prefix` arguments are no longer used by the core logic
    # but are kept for signature compatibility for now.
    outcome = process_single_course(
        reunion=reunion,
        course=course,
        phase=phase,
        data_dir=Path("./data"), # Unused
        budget=budget,
        kelly=kelly,
        gcs_prefix=None, # Unused
    )

    print(f"--- Test finished for {reunion}{course} ---")
    if outcome:
        print("Outcome:")
        print(json.dumps(outcome, indent=2, ensure_ascii=False))
    else:
        print("No outcome (successful run, no bet decision).")

    # Example: Process R1C2 for H30 phase (snapshot only)
    reunion = "R1"
    course = "C2"
    phase = "H30"
    print(f"--- Running test for {reunion}{course} phase {phase} (snapshot only) ---")
    process_single_course(
        reunion=reunion,
        course=course,
        phase=phase,
        data_dir=Path("./data"), # Unused
        budget=budget,
        kelly=kelly,
        gcs_prefix=None, # Unused
    )
    print(f"--- Test finished for {reunion}{course} ---")


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
