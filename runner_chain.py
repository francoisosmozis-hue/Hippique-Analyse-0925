#!/usr/bin/env python3
"""Run scheduled H-30 and H-5 windows based on a planning file.

This lightweight runner loads the day's planning and for each race determines
whether the start time falls within the configured H-30 or H-5 windows.  When a
window matches, snapshot/analysis files are written under the designated
directories.  The analysis step now delegates selection and ROI computation to
``pipeline_run.run_pipeline`` so there is a single source of truth for tickets.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import re
import shutil
from pathlib import Path
import math
from collections.abc import Iterable, Sequence
from typing import Any, Dict, List, Mapping, MutableMapping

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# CORRECTION: Imports depuis scripts/ au lieu de la racine
from simulate_wrapper import PAYOUT_CALIBRATION_PATH, evaluate_combo

from scripts import online_fetch_zeturf as ofz
from scripts.gcs_utils import disabled_reason, is_gcs_enabled
from scripts import analysis_utils as _analysis_utils

import pipeline_run

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    ValidationError as PydanticValidationError,
    Field,
    field_validator,
)

import yaml

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


EXOTIC_BASE_EV = getattr(pipeline_run, "EXOTIC_BASE_EV", 0.40)
EXOTIC_BASE_PAYOUT = getattr(pipeline_run, "EXOTIC_BASE_PAYOUT", 10.0)

EXOTIC_TYPES = {"COUPLE_PLACE", "COUPLE_GAGNANT", "TRIO", "ZE4", "ZE234", "MULTI", "2SUR4"}
_SP_LABELS = {
    "SP",
    "SIMPLE_PLACE_DUTCHING",
    "DUTCHING_SP",
    "PLACE_DUTCHING",
    "SP_DUTCHING_GPIV51",
}


def should_cut_exotics(overround: float, threshold: float = 1.30) -> bool:
    """True si overround marché > seuil (marché 'gras' => on coupe exotiques)."""

    try:
        return (overround is not None) and (float(overround) > float(threshold))
    except Exception:
        return False


def enforce_budget_and_ticket_cap(tickets: list, budget: float) -> list:
    """
    Garde SP dutching + premier combiné, puis rescale au budget.
    'type' doit être renseigné correctement sur chaque ticket.
    """

    if not tickets:
        return []

    sp = [
        t
        for t in tickets
        if (t.get("label", "") or t.get("type", "")).upper() in _SP_LABELS
    ]
    exo = [
        t
        for t in tickets
        if (t.get("type", "") or "").upper() in EXOTIC_TYPES
    ]

    final = []
    if sp:
        final.append(sp[0])
    if exo:
        final.append(exo[0])
    final = final[:2]

    tot = sum(float(t.get("stake", 0.0) or 0.0) for t in final)
    if tot > float(budget) + 1e-9 and tot > 0:
        scale = float(budget) / tot
        for t in final:
            t["stake"] = round(float(t.get("stake", 0.0)) * scale, 2)
    return final


def _update_metrics_ticket_counts(metrics_path: Path, tickets: list[Mapping[str, Any]]) -> None:
    """Refresh ticket counters in metrics.json after the final lock."""

    if not metrics_path.exists():
        return

    try:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except Exception:
        return

    if not isinstance(metrics, dict):
        return

    tickets_bucket = metrics.get("tickets")
    if not isinstance(tickets_bucket, dict):
        tickets_bucket = {}
        metrics["tickets"] = tickets_bucket

    total = len(tickets)
    sp_count = sum(
        1 for t in tickets if (t.get("label", "") or t.get("type", "")).upper() in _SP_LABELS
    )
    combo_count = sum(
        1 for t in tickets if (t.get("type", "") or "").upper() in EXOTIC_TYPES
    )

    tickets_bucket["total"] = total
    tickets_bucket["sp"] = sp_count
    tickets_bucket["combo"] = combo_count

    try:
        metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        logger.warning("Unable to refresh metrics ticket counts in %s", metrics_path)


def _coerce_float(value: Any) -> float | None:
    """Return ``value`` as a finite float when possible."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _extract_leg_identifier(leg: Mapping[str, Any], index: int) -> str:
    """Return a stable identifier for a combo leg."""

    for key in ("id", "runner", "participant", "code", "num", "name"):
        value = leg.get(key)
        if value not in (None, ""):
            return str(value)
    return f"leg_{index}"


def estimate_sp_ev(legs: Iterable[Mapping[str, Any]]) -> tuple[float | None, bool]:
    """Estimate the average EV ratio for SP dutching legs.

    The computation ignores legs missing either the place odds or probability
    information and reports whether any such omissions were detected.  At least
    two valid legs are required to return an EV estimate; otherwise ``None`` is
    returned.
    """

    values: list[float] = []
    some_missing = False
    total = 0
    for leg in legs:
        total += 1
        leg_mapping = leg if isinstance(leg, Mapping) else {}
        odds = (
            leg_mapping.get("odds_place")
            or leg_mapping.get("place_odds")
            or leg_mapping.get("odds")
        )
        prob = leg_mapping.get("p") or leg_mapping.get("probability")

        odds_f = _coerce_float(odds)
        prob_f = _coerce_float(prob)

        identifier = _extract_leg_identifier(leg_mapping, total - 1)

        if (odds_f is None or odds_f <= 1.0) and prob_f is not None and prob_f > 0.0:
            market = leg_mapping.get("market") if isinstance(leg_mapping.get("market"), Mapping) else None
            nplace_val = None
            if isinstance(market, Mapping):
                candidate_nplace = market.get("nplace")
                if isinstance(candidate_nplace, (int, float)) and candidate_nplace > 0:
                    nplace_val = int(candidate_nplace)
                if not nplace_val:
                    n_partants = market.get("n_partants") or market.get("n_participants")
                    try:
                        n_value = int(float(n_partants)) if n_partants not in (None, "") else None
                    except (TypeError, ValueError):
                        n_value = None
                    if n_value:
                        nplace_val = 3 if n_value >= 8 else (2 if n_value >= 4 else 1)
                if not nplace_val:
                    horses = market.get("horses")
                    if isinstance(horses, Sequence):
                        count = len(horses)
                        nplace_val = 3 if count >= 8 else (2 if count >= 4 else 1)
            if not nplace_val:
                nplace_val = 3 if total >= 8 else (2 if total >= 4 else 1)

            approx = nplace_val / max(1e-6, prob_f)
            odds_f = max(1.10, min(10.0, approx))
            some_missing = True
            notes = leg_mapping.setdefault("notes", []) if isinstance(leg_mapping, dict) else None
            if isinstance(notes, list) and "odds_place_imputed" not in notes:
                notes.append("odds_place_imputed")
            logger.info(
                "[SP] Cote place imputée pour %s (nplace=%d, p=%.4f → %.2f)",
                identifier,
                nplace_val,
                prob_f,
                odds_f,
            )

        if odds_f is None or prob_f is None:
            some_missing = True
            logger.warning(
                "[SP] Cote place ou probabilité manquante pour %s", identifier
            )
            continue

        if odds_f <= 1.0 or not 0.0 < prob_f < 1.0:
            some_missing = True
            logger.warning(
                "[SP] Données place invalides pour %s (odds=%.3f, p=%.3f)",
                identifier,
                odds_f if odds_f is not None else float("nan"),
                prob_f if prob_f is not None else float("nan"),
            )
            continue

        values.append(prob_f * odds_f - 1.0)

    if len(values) < 2:
        if values:
            logger.warning(
                "[SP] Moins de deux cotes place exploitables (valides=%d, total=%d)",
                len(values),
                total,
            )
        else:
            logger.warning(
                "[SP] Aucune cote place exploitable (total=%d)",
                total,
            )
        return None, True if some_missing or values else some_missing

    average = sum(values) / len(values)
    return average, some_missing


def compute_overround_cap(
    discipline: Any,
    partants: Any,
    *,
    course_label: Any | None = None,
    context: MutableMapping[str, Any] | None = None,
    default_cap: float = 1.30,
) -> float:
    """Compatibility wrapper mirroring :mod:`scripts.analysis_utils`."""

    return _analysis_utils.compute_overround_cap(
        discipline,
        partants,
        course_label=course_label,
        context=context,
        default_cap=default_cap,
    )


def filter_exotics_by_overround(
    tickets: Sequence[Sequence[Mapping[str, Any]]],
    *,
    overround: float | None,
    overround_max: float,
    discipline: Any,
    partants: Any,
    course_label: Any | None = None,
    context: MutableMapping[str, Any] | None = None,
) -> list[Sequence[Mapping[str, Any]]]:
    """Filter exotic tickets if overround exceeds the computed cap."""

    if overround is None:
        return list(tickets)

    cap_context: MutableMapping[str, Any] | None = context
    if cap_context is None:
        cap_context = {}

    effective_cap = compute_overround_cap(
        discipline,
        partants,
        course_label=course_label,
        context=cap_context,
        default_cap=overround_max,
    )

    if overround > effective_cap:
        logger.info(
            "[combo] overround %.3f above cap %.3f → combos rejected",
            overround,
            effective_cap,
        )
        return []

    return list(tickets)


def validate_exotics_with_simwrapper(
    exotics: Sequence[Sequence[Mapping[str, Any]]],
    bankroll: float,
    *,
    payout_min: float | None = None,
    ev_min: float | None = None,
    sharpe_min: float = 0.0,
    calibration: str | os.PathLike[str] | None = None,
    allow_heuristic: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Evaluate combo candidates using :func:`simulate_wrapper.evaluate_combo`.

    The guards mirror the stricter pipeline requirements: a valid payout
    calibration is mandatory, combinations must reach the EV/payout thresholds
    and unreliable probability sources are rejected.  At most the best combo is
    returned in order to align with the two-ticket policy (SP + one combo).
    """

    if allow_heuristic:
        logger.warning(
            "[COMBO] allow_heuristic override ignored; payout calibration is mandatory."
        )

    ev_threshold = max(EXOTIC_BASE_EV, ev_min if ev_min is not None else EXOTIC_BASE_EV)
    payout_threshold = max(
        EXOTIC_BASE_PAYOUT,
        payout_min if payout_min is not None else EXOTIC_BASE_PAYOUT,
    )

    info: dict[str, Any] = {
        "thresholds": {
            "ev_min": ev_threshold,
            "payout_min": payout_threshold,
            "sharpe_min": sharpe_min,
        },
        "notes": [],
        "flags": {
            "combo": False,
            "ALERTE_VALUE": False,
            "reasons": {"combo": []},
        },
    }

    calib_candidate = (
        str(calibration)
        if calibration
        else os.environ.get("GPI_PAYOUT_CALIBRATION", str(PAYOUT_CALIBRATION_PATH))
    )
    try:
        ok_calib = (
            bool(calib_candidate)
            and os.path.exists(calib_candidate)
            and os.path.getsize(calib_candidate) > 0
        )
    except Exception:
        ok_calib = False

    if not ok_calib:
        base_note = "calibration_missing"
        custom_note = "no_calibration_yaml → exotiques désactivés"
        if base_note not in info["notes"]:
            info["notes"].append(base_note)
        if custom_note not in info["notes"]:
            info["notes"].append(custom_note)
        flags_combo = info["flags"].setdefault("reasons", {}).setdefault("combo", [])
        if "calibration_missing" not in flags_combo:
            flags_combo.append("calibration_missing")
        info["flags"]["combo"] = False
        info["flags"]["ALERTE_VALUE"] = False
        info["decision"] = "reject:calibration_missing"
        info["status"] = "insufficient_data"
        return [], info
    calibration_path = Path(calibration) if calibration else PAYOUT_CALIBRATION_PATH

    kept: list[dict[str, Any]] = []
    reasons_accum: list[str] = []
    notes_seen: set[str] = set()

    for index, template in enumerate(exotics):
        if not isinstance(template, Sequence) or not template:
            continue

        legs: list[dict[str, Any]] = []
        leg_ids: list[str] = []
        stake_sum = 0.0
        for leg_index, raw_leg in enumerate(template):
            if not isinstance(raw_leg, Mapping):
                continue
            leg_copy = dict(raw_leg)
            legs.append(leg_copy)
            leg_id = _extract_leg_identifier(leg_copy, leg_index)
            leg_ids.append(leg_id)
            stake = _coerce_float(leg_copy.get("stake"))
            if stake is not None and stake > 0:
                stake_sum += stake

        if not legs:
            continue

        ticket_id = "|".join(leg_ids) if leg_ids else f"combo_{index}"
        ticket_payload = {
            "id": ticket_id,
            "type": legs[0].get("type", "combo"),
            "stake": stake_sum if stake_sum > 0 else float(len(legs)),
            "legs": legs,
        }

        try:
            result = evaluate_combo(
                [ticket_payload],
                bankroll,
                calibration=str(calibration_path),
                allow_heuristic=False,
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning("[COMBO] Simulation error for %s: %s", ticket_id, exc)
            reasons_accum.append("evaluation_error")
            continue

        result_map: dict[str, Any]
        if isinstance(result, Mapping):
            result_map = {str(k): v for k, v in result.items()}
        else:
            result_map = {}

        status = str(result_map.get("status") or "").lower() or "ok"
        ev_ratio = _coerce_float(result_map.get("ev_ratio"))
        payout_expected = _coerce_float(result_map.get("payout_expected"))
        roi_val = _coerce_float(result_map.get("roi"))
        sharpe_val = _coerce_float(result_map.get("sharpe"))

        raw_notes = result_map.get("notes")
        notes: list[str] = []
        if isinstance(raw_notes, (list, tuple, set)):
            notes = [str(item) for item in raw_notes if item not in (None, "")]
        elif raw_notes not in (None, ""):
            notes = [str(raw_notes)]

        for note in notes:
            if note not in notes_seen:
                info["notes"].append(note)
                notes_seen.add(note)

        keep = True
        reasons: list[str] = []

        if status != "ok":
            reason = f"status_{status or 'unknown'}"
            reasons.append(reason)
            logger.warning(
                "[COMBO] rejet statut=%s pour %s", status or "unknown", ticket_id
            )
            keep = False

        if ev_ratio is None or ev_ratio < EXOTIC_BASE_EV:
            reasons.append("ev_ratio_below_accept_threshold")
            keep = False
        if payout_expected is None or payout_expected < EXOTIC_BASE_PAYOUT:
            reasons.append("payout_expected_below_accept_threshold")
            keep = False
        if ev_ratio is not None and ev_ratio < ev_threshold:
            reasons.append("ev_ratio_below_pipeline_threshold")
            keep = False
        if payout_expected is not None and payout_expected < payout_threshold:
            reasons.append("payout_below_pipeline_threshold")
            keep = False
        if sharpe_val is None or sharpe_val < sharpe_min:
            reasons.append("sharpe_below_threshold")
            keep = False
        if "combo_probabilities_unreliable" in notes:
            reasons.append("probabilities_unreliable")
            keep = False

        if keep:
            kept.append(
                {
                    "id": ticket_id,
                    "legs": leg_ids,
                    "stake": stake_sum if stake_sum > 0 else None,
                    "ev_ratio": ev_ratio,
                    "roi": roi_val,
                    "payout_expected": payout_expected,
                    "sharpe": sharpe_val,
                    "flags": ["ALERTE_VALUE"],
                }
            )
        else:
            for reason in reasons:
                if reason not in reasons_accum:
                    reasons_accum.append(reason)

        flags = info["flags"]["reasons"]["combo"]
        for reason in reasons:
            if reason not in flags:
                flags.append(reason)

    if kept:
        kept.sort(
            key=lambda ticket: (
                (
                    ticket.get("ev_ratio")
                    if ticket.get("ev_ratio") is not None
                    else float("-inf")
                ),
                (
                    ticket.get("payout_expected")
                    if ticket.get("payout_expected") is not None
                    else float("-inf")
                ),
            ),
            reverse=True,
        )
        kept = kept[:1]
        info["flags"]["combo"] = True
        info["flags"]["ALERTE_VALUE"] = True
        info["decision"] = "accept"
    else:
        info["flags"]["combo"] = False
        info["flags"]["ALERTE_VALUE"] = False
        if reasons_accum:
            info["decision"] = f"reject:{reasons_accum[0]}"
        else:
            info["decision"] = "reject:no_candidate"

    info.setdefault("metrics", {})
    info["metrics"].update(
        {
            "payout_min": payout_threshold,
            "ev_min": ev_threshold,
            "sharpe_min": sharpe_min,
        }
    )

    return kept, info


def _format_csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def export_tracking_csv_line(
    path: str | os.PathLike[str],
    meta: Mapping[str, Any],
    tickets: Sequence[Mapping[str, Any]],
    stats: Mapping[str, Any],
    *,
    alerte: bool = False,
) -> None:
    """Append a tracking CSV line capturing EV/ROI metrics for a race."""

    header = [
        "reunion",
        "course",
        "hippodrome",
        "date",
        "discipline",
        "partants",
        "tickets_count",
        "nb_tickets",
        "stake_total",
        "stake_average",
        "expected_gross_return_eur",
        "ev_simulee_post_arrondi",
        "ev_sp",
        "ev_global",
        "roi_simule",
        "roi_sp",
        "roi_global",
        "roi_reel",
        "prob_implicite_panier",
        "risk_of_ruin",
        "sharpe",
        "drift_sign",
        "model",
        "ALERTE_VALUE",
    ]

    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)

    # Compute aggregate metrics for the CSV line.
    stake_values: list[float] = []
    for ticket in tickets:
        if not isinstance(ticket, Mapping):
            continue
        stake_val = _coerce_float(ticket.get("stake"))
        if stake_val is not None and stake_val > 0:
            stake_values.append(stake_val)

    stake_total = sum(stake_values)
    stake_average = stake_total / len(stake_values) if stake_values else 0.0

    payload: dict[str, Any] = {}
    payload.update({str(k): v for k, v in meta.items()})
    payload.update({str(k): v for k, v in stats.items()})
    payload.setdefault("ev_simulee_post_arrondi", payload.get("ev_global"))
    payload.setdefault("roi_simule", payload.get("roi_global"))
    ticket_count = len(stake_values)
    payload["tickets_count"] = ticket_count
    payload.setdefault("nb_tickets", ticket_count)
    payload["stake_total"] = stake_total
    payload["stake_average"] = stake_average
    gross_return = payload.get("expected_gross_return_eur")
    if gross_return is None:
        gross_return = payload.get("combined_expected_payout")
    if gross_return is None and isinstance(payload.get("ev_global"), (int, float)):
        gross_return = stake_total + float(payload.get("ev_global", 0.0))
    payload["expected_gross_return_eur"] = gross_return
    payload["ALERTE_VALUE"] = "ALERTE_VALUE" if alerte else ""

    mode = "a" if path_obj.exists() else "w"
    with path_obj.open(mode, encoding="utf-8") as fh:
        if mode == "w":
            fh.write(";".join(header) + "\n")
        row = ";".join(_format_csv_value(payload.get(column)) for column in header)
        fh.write(row + "\n")


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


def _normalize_snapshot_payload(
    snapshot: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[Any]]:
    """Return a mutable snapshot payload ensuring a 'runners' list is available."""

    if isinstance(snapshot, dict):
        normalized = snapshot
    elif isinstance(snapshot, Mapping):
        try:
            normalized = dict(snapshot)
        except TypeError:
            return {}, []
    else:
        return {}, []
    runners = normalized.get("runners")
    if isinstance(runners, list) and runners:
        return normalized, runners
    fallback = normalized.get("partants")
    if isinstance(fallback, list) and fallback:
        normalized["runners"] = fallback
        return normalized, fallback
    return normalized, runners if isinstance(runners, list) else []


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
        normalized_snapshot, normalized_runners = _normalize_snapshot_payload(snapshot)
        if course_url and isinstance(normalized_snapshot, dict):
            normalized_snapshot.setdefault("source_url", course_url)
        if not normalized_runners:
            logger.warning(
                "[runner] Snapshot %s (%s) missing runners payload", race_id, window
            )
        payload_out = {
            "status": "ok",
            "rc": race_id,
            "phase": window,
            "fetched_at": now,
            "payload": normalized_snapshot,
        }
        logger.info("[runner] Snapshot %s (%s) fetched", race_id, window)

    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload_out, fh, ensure_ascii=False, indent=2)
    alias_name = None
    if window.upper() == "H30":
        alias_name = "h30.json"
    elif window.upper() == "H5":
        alias_name = "h5.json"
    if alias_name:
        alias_path = dest / alias_name
        with alias_path.open("w", encoding="utf-8") as fh:
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
    payload: RunnerPayload,
    snap_dir: Path,
    analysis_dir: Path,
    *,
    budget: float,
    ev_min: float,
    roi_min: float,
    mode: str,
    calibration: Path,
) -> None:
    """Execute the pipeline for ``payload`` and persist artefacts."""

    race_id = payload.race_id
    race_dir = analysis_dir / race_id
    race_dir.mkdir(parents=True, exist_ok=True)
    outdir = race_dir / "out"
    outdir.mkdir(parents=True, exist_ok=True)
    logger.info("[runner] Analyse pipeline pour %s → %s", race_id, outdir)

    def _discover(name: str) -> Path | None:
        for root in (race_dir, snap_dir / race_id, snap_dir):
            candidate = root / name
            if candidate.exists():
                return candidate
        return None

    required = {
        "h30": _discover("h30.json"),
        "h5": _discover("h5.json"),
        "stats": _discover("stats_je.json"),
        "partants": _discover("partants.json"),
    }
    missing = [key for key, path in required.items() if path is None]
    analysis_summary: dict[str, Any] = {
        "race_id": race_id,
        "status": "pending",
        "mode": mode,
        "budget": budget,
        "inputs": {k: str(v) if v else None for k, v in required.items()},
    }

    if missing:
        reason = f"missing_inputs:{','.join(sorted(missing))}"
        logger.error("[runner] Pipeline bloqué pour %s: %s", race_id, reason)
        analysis_summary.update({"status": "no-data", "reason": reason})
        _write_json_file(race_dir / "analysis.json", analysis_summary)
        return

    gpi_candidates = [
        race_dir / "gpi.yml",
        race_dir / "gpi.yaml",
        Path("config/gpi.yml"),
        Path("config/gpi.yaml"),
    ]
    gpi_path = next((path for path in gpi_candidates if path.exists()), None)
    if gpi_path is None:
        logger.error("[runner] Configuration GPI introuvable pour %s", race_id)
        analysis_summary.update({"status": "no-config", "reason": "gpi_missing"})
        _write_json_file(race_dir / "analysis.json", analysis_summary)
        return

    allow_je_na = False
    try:
        stats_payload = json.loads(required["stats"].read_text(encoding="utf-8"))
    except Exception:  # pragma: no cover - resilience
        stats_payload = {}
    if isinstance(stats_payload, dict):
        coverage = stats_payload.get("coverage")
        allow_je_na = isinstance(coverage, (int, float)) and float(coverage) < 100.0

    calibration_path = calibration if calibration else PAYOUT_CALIBRATION_PATH

    try:
        result = pipeline_run.run_pipeline(
            h30=str(required["h30"]),
            h5=str(required["h5"]),
            stats_je=str(required["stats"]),
            partants=str(required["partants"]),
            gpi=str(gpi_path),
            outdir=str(outdir),
            budget=float(budget),
            ev_global=ev_min,
            roi_global=roi_min,
            allow_je_na=allow_je_na,
            calibration=str(calibration_path),
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("[runner] Echec pipeline pour %s: %s", race_id, exc)
        analysis_summary.update({"status": "error", "reason": str(exc)})
        _write_json_file(race_dir / "analysis.json", analysis_summary)
        return
        
    outdir_path = Path(result.get("outdir") or "")
    budget_value = float(budget) if budget and float(budget) > 0 else 5.0
    enforced_tickets: list[Mapping[str, Any]] | None = None
    if outdir_path.is_dir():
        p_finale_path = outdir_path / "p_finale.json"
        if p_finale_path.exists():
            try:
                p_payload = json.loads(p_finale_path.read_text(encoding="utf-8"))
            except Exception:
                p_payload = None
            if isinstance(p_payload, dict):
                meta_block = p_payload.get("meta")
                market_meta = meta_block.get("market") if isinstance(meta_block, Mapping) else {}
                overround_value = None
                if isinstance(market_meta, Mapping):
                    overround_value = market_meta.get("overround")
                tickets_payload = p_payload.get("tickets")
                if isinstance(tickets_payload, list):
                    sanitized = [dict(t) for t in tickets_payload if isinstance(t, Mapping)]
                    if should_cut_exotics(overround_value):
                        sanitized = [
                            t
                            for t in sanitized
                            if (t.get("label", "") or t.get("type", "")).upper() in _SP_LABELS
                        ]
                    enforced = enforce_budget_and_ticket_cap(sanitized, budget_value)
                    p_payload["tickets"] = enforced
                    enforced_tickets = enforced
                    try:
                        p_finale_path.write_text(
                            json.dumps(p_payload, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8",
                        )
                    except OSError as exc:  # pragma: no cover - resilience
                        logger.warning("[runner] Unable to persist guarded tickets: %s", exc)
                    else:
                        _update_metrics_ticket_counts(outdir_path / "metrics.json", enforced)
    metrics = result.get("metrics") if isinstance(result, Mapping) else {}
    if enforced_tickets and isinstance(metrics, dict):
        tickets_bucket = metrics.get("tickets")
        if isinstance(tickets_bucket, dict):
            tickets_bucket["total"] = len(enforced_tickets)
            tickets_bucket["sp"] = sum(
                1
                for t in enforced_tickets
                if (t.get("label", "") or t.get("type", "")).upper() in _SP_LABELS
            )
            tickets_bucket["combo"] = sum(
                1
                for t in enforced_tickets
                if (t.get("type", "") or "").upper() in EXOTIC_TYPES
            )

    status = (
        str(metrics.get("status") or "unknown")
        if isinstance(metrics, Mapping)
        else "unknown"
    )
    analysis_summary.update(
        {
            "status": status,
            "outdir": result.get("outdir"),
            "metrics": metrics,
        }
    )
    _write_json_file(race_dir / "analysis.json", analysis_summary)

    artefacts_to_copy = [
        "metrics.json",
        "metrics.csv",
        "p_finale.json",
        "diff_drift.json",
        "cmd_update_excel.txt",
    ]
    for name in artefacts_to_copy:
        src_dir = result.get("outdir")
        src = Path(src_dir) / name if src_dir else None
        if src and src.exists():
            shutil.copy2(src, race_dir / name)

    cmd_path = Path(result.get("outdir", "")) / "cmd_update_excel.txt"
    if cmd_path.exists():
        try:
            command_text = cmd_path.read_text(encoding="utf-8").strip()
        except OSError:  # pragma: no cover - best effort
            command_text = ""
        if command_text:
            print(command_text)
            logger.info("[runner] Commande Excel: %s", command_text)

    if USE_GCS and upload_file:
        for name in ("analysis.json", "metrics.json", "metrics.csv"):
            try:
                upload_file(race_dir / name)
            except EnvironmentError as exc:
                logger.warning("Skipping cloud upload for %s: %s", race_dir / name, exc)
    else:
        reason = disabled_reason()
        detail = f"{reason}=false" if reason else "USE_GCS disabled"
        logger.info(
            "[gcs] Skipping upload for %s (%s)", race_dir / "analysis.json", detail
        )


def _trigger_phase(
    payload: RunnerPayload,
    *,
    snap_dir: Path,
    analysis_dir: Path,
    ev_min: float,
    roi_min: float,
    mode: str,
    calibration: Path,
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
            payload,
            snap_dir,
            analysis_dir,
            budget=budget,
            ev_min=ev_min,
            roi_min=roi_min,
            mode=mode,
            calibration=calibration,
        )
        return
    if phase_norm == "RESULT":
        race_dir = analysis_dir / race_id
        arrivee_path = race_dir / "arrivee_officielle.json"
        race_dir.mkdir(parents=True, exist_ok=True)
        if not arrivee_path.exists():
            # CORRECTION: Encodage UTF-8 corrigé
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
            course_url=args.course_url,
        )
    except PayloadValidationError as exc:
        logger.error("[runner] %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
