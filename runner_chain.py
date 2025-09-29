"""Utilities for validating exotic tickets and exporting tracking lines.

This module exposes two helper functions used by the pipeline:

``validate_exotics_with_simwrapper`` evaluates combiné tickets via
:func:`simulate_wrapper.evaluate_combo` and retains only the most attractive
candidate based on EV ratio and expected payout. When the combination offers
both a high EV and a large expected payout an ``ALERTE_VALUE`` flag is attached.

``export_tracking_csv_line`` appends a line to the tracking CSV and supports an
optional ``ALERTE_VALUE`` column when the alert flag is present.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from pathlib import Path


from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from simulate_wrapper import evaluate_combo
from logging_io import append_csv_line, CSV_HEADER


logger = logging.getLogger(__name__)

try:
    MAX_COMBO_OVERROUND = float(os.getenv("MAX_COMBO_OVERROUND", "1.25"))
except (TypeError, ValueError):  # pragma: no cover - defensive fallback
    MAX_COMBO_OVERROUND = 1.25

CALIB_PATH = os.getenv("CALIB_PATH", "config/payout_calibration.yaml")


def _resolve_calibration_path() -> tuple[Path, bool]:
    """Return the payout calibration path and whether it exists."""

    candidates: list[Path] = []
    if CALIB_PATH:
        try:
            candidates.append(Path(CALIB_PATH))
        except TypeError:  # pragma: no cover - defensive guard
            pass
    candidates.append(Path("config/payout_calibration.yaml"))
    candidates.append(Path("calibration/payout_calibration.yaml"))

    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate, True
        except OSError:  # pragma: no cover - filesystem issues
            continue

    return candidates[0], False

def compute_overround_cap(
    discipline: str | None,
    partants: Any,
    *,
    default_cap: float = 1.25,
    course_label: str | None = None,
    context: Dict[str, Any] | None = None,
) -> float:
    """Return the overround ceiling adjusted for flat-handicap races.

    When ``context`` is provided it is populated with diagnostic information
    describing the evaluation (normalised discipline/course labels, partants
    count, default cap and whether the stricter threshold was triggered).
    """
    
    try:
        cap = float(default_cap)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        cap = 1.30
    if cap <= 0:
        cap = 1.30
    default_cap_value = cap

    def _coerce_partants(value: Any) -> int | None:
        if isinstance(value, (int, float)):
            try:
                return int(value)
            except (TypeError, ValueError):  # pragma: no cover - defensive
                return None
        if isinstance(value, str):
            match = re.search(r"\d+", value)
            if match:
                try:
                    return int(match.group())
                except ValueError:  # pragma: no cover - defensive
                    return None
        return None

    partants_int = _coerce_partants(partants)

    def _normalise_text(value: str | None) -> str:
        if not value:
            return ""
        normalised = unicodedata.normalize("NFKD", value)
        ascii_only = normalised.encode("ascii", "ignore").decode("ascii")
        return ascii_only.lower()

    discipline_text = _normalise_text(discipline)
    course_text = _normalise_text(course_label)
    combined_text = " ".join(token for token in (discipline_text, course_text) if token)

    flat_tokens = ("plat", "galop", "galopeur")
    handicap_tokens = ("handicap", "hand.", "hcap", "handi")
    obstacle_tokens = ("haies", "steeple", "obstacle", "cross")
    trot_tokens = ("trot", "attel", "mont", "sulky")

    flat_hint = any(token in combined_text for token in flat_tokens)
    is_handicap = any(token in combined_text for token in handicap_tokens)
    is_obstacle = any(token in combined_text for token in obstacle_tokens)
    is_trot = any(token in combined_text for token in trot_tokens)

    is_flat = flat_hint or (is_handicap and not is_obstacle and not is_trot)

    triggered = False
    reason: str | None = None
    adjusted = cap

    def _mark_adjustment(candidate: float, reason_label: str) -> None:
        nonlocal adjusted, triggered, reason
        if candidate < adjusted:
            adjusted = candidate
            triggered = True
            reason = reason_label
        elif candidate == adjusted:
            triggered = True
            if not reason:
                reason = reason_label

    if is_flat:
        if is_handicap:
            candidate = min(adjusted, 1.25)
            _mark_adjustment(candidate, "flat_handicap")
        elif partants_int is not None and partants_int >= 14:
            candidate = min(adjusted, 1.25)
            _mark_adjustment(candidate, "flat_large_field")

    if context is not None:
        context["default_cap"] = default_cap_value
        context["cap"] = adjusted
        if discipline_text:
            context["discipline"] = discipline_text
        if course_text:
            context["course_label"] = course_text
        if partants_int is not None:
            context["partants"] = partants_int
        context["triggered"] = triggered
        if reason:
            context["reason"] = reason

    if triggered and reason:
        logger.debug(
            "Overround cap auto-adjusted to %.2f (reason=%s, discipline=%s, partants=%s, course=%s)",
            adjusted,
            reason,
            discipline_text or "?",
            partants_int if partants_int is not None else "?",
            course_text or "?",
        )

    return adjusted


def filter_exotics_by_overround(
    exotics: Iterable[List[Dict[str, Any]]],
    *,
    overround: float | None,
    overround_max: float | None = None,
    discipline: str | None = None,
    partants: Any = None,
    course_label: str | None = None,
) -> List[List[Dict[str, Any]]]:
    """Filter exotic tickets when the market overround exceeds the cap."""

    context: Dict[str, Any] = {}
    try:
        default_cap = float(overround_max) if overround_max is not None else MAX_COMBO_OVERROUND
    except (TypeError, ValueError):  # pragma: no cover - defensive fallback
        default_cap = MAX_COMBO_OVERROUND

    cap = compute_overround_cap(
        discipline,
        partants,
        default_cap=default_cap,
        course_label=course_label,
        context=context,        
    )
    
    try:
        overround_value = float(overround) if overround is not None else None
    except (TypeError, ValueError):  # pragma: no cover - defensive fallback
        logger.debug(
            "Overround value %r could not be coerced to float; ignoring cap", overround
        )
        overround_value = None

    if overround_value is None or overround_value <= cap:
        return [list(ticket) for ticket in exotics]
        
    reason = context.get("reason") if context.get("triggered") else None
    logger.info(
        "[OVERROUND] combinés filtrés (overround=%.3f, cap=%.2f, discipline=%s, partants=%s, course=%s, reason=%s)",
        overround_value,
        cap,
        context.get("discipline") or (discipline or "?"),
        context.get("partants") or partants or "?",
        context.get("course_label") or course_label or "?",
        reason or "default_cap",
    )
    return []

def validate_exotics_with_simwrapper(
    exotics: Iterable[List[Dict[str, Any]]],
    bankroll: float,
    *,
    ev_min: float = 0.0,
    roi_min: float = 0.0,
    payout_min: float = 0.0,
    sharpe_min: float = 0.0,
    allow_heuristic: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Validate exotic ticket candidates using :func:`evaluate_combo`.

    Parameters
    ----------
    exotics:
        Iterable of candidate combinations. Each candidate is expressed as a
        list of leg tickets compatible with ``compute_ev_roi``.
    bankroll:
        Bankroll used for EV ratio computation.
    ev_min:
        Minimum EV ratio required for a candidate to be retained.
    roi_min:
        Minimum ROI required for a candidate to be retained.
    payout_min:
        Minimum expected payout required for a candidate to be retained.
    allow_heuristic:
    sharpe_min:
        Minimum Sharpe ratio (EV/σ) required for a candidate.
        Passed through to :func:`evaluate_combo` to allow evaluation without
        calibration data.

    Returns
    -------
    tuple
        ``(tickets, info)`` where ``tickets`` contains at most one validated
        exotic ticket and ``info`` exposes ``notes`` and ``flags`` gathered
        during validation.
    """
    validated: List[Dict[str, Any]] = []
    notes: List[str] = []
    notes_seen: set[str] = set()
    reasons: List[str] = []
    alerte = False

    calib_path, has_calib = _resolve_calibration_path()
    if not has_calib:
        logger.warning(
            "[COMBO] Calibration payout introuvable (%s) → combinés désactivés.",
            calib_path,
        )
        reason = "calibration_missing"
        info = {
            "notes": [reason],
            "flags": {"combo": False, "reasons": {"combo": [reason]}},
            "decision": f"reject:{reason}",
            "status": "insufficient_data",
        }
        return [], info

    def add_note(label: str) -> None:
        if label not in notes_seen:
            notes.append(label)
            notes_seen.add(label)
            
    for candidate in exotics:
        if not candidate:
            continue
        
        base_meta: Mapping[str, Any] = {}
        candidate_ids: List[str] = []
        for entry in candidate:
            if isinstance(entry, Mapping):
                if not base_meta:
                    base_meta = entry
                entry_id = entry.get("id")
                if entry_id not in (None, ""):
                    candidate_ids.append(str(entry_id))

        stats = evaluate_combo(candidate, bankroll, allow_heuristic=allow_heuristic)
        status = str(stats.get("status") or "ok").lower()
        ev_ratio = float(stats.get("ev_ratio", 0.0))
        roi = float(stats.get("roi", 0.0))
        payout = float(stats.get("payout_expected", 0.0))
        sharpe = float(stats.get("sharpe", 0.0))
        stats_notes = [str(n) for n in stats.get("notes", [])]
        for note in stats_notes:
            add_note(note)
        if status != "ok":
            ticket_label = "?"
            if isinstance(base_meta, Mapping):
                raw_ticket_id = base_meta.get("id")
                if raw_ticket_id not in (None, ""):
                    ticket_label = str(raw_ticket_id)
            if ticket_label == "?" and candidate_ids:
                ticket_label = ", ".join(candidate_ids)

            legs_for_log = "?"
            legs_meta = None
            if isinstance(base_meta, Mapping):
                legs_meta = base_meta.get("legs")
            if isinstance(legs_meta, Sequence) and not isinstance(
                legs_meta, (str, bytes, bytearray)
            ):
                legs_for_log = ", ".join(str(val) for val in legs_meta)
            elif legs_meta not in (None, ""):
                legs_for_log = str(legs_meta)
            elif candidate_ids:
                legs_for_log = ", ".join(candidate_ids)

            logger.warning(
                "[COMBO] Simwrapper rejected candidate (status=%s, ticket=%s, legs=%s)",
                status,
                ticket_label,
                legs_for_log,
            )
            
            reasons.append(f"status_{status or 'unknown'}")
            continue
        if ev_ratio < 0.40:
            reasons.append("ev_ratio_below_accept_threshold")
            continue
        if payout < 10.0:
            reasons.append("payout_expected_below_accept_threshold")
            continue
        if "combo_probabilities_unreliable" in stats_notes:
            reasons.append("probabilities_unreliable")
            continue
        if ev_ratio < ev_min:
            reasons.append("ev_ratio_below_threshold")
            continue
        if roi < roi_min:
            reasons.append("roi_below_threshold")
            continue
        if payout < payout_min:
            reasons.append("payout_below_threshold")
            continue
        if sharpe < sharpe_min:
            reasons.append("sharpe_below_threshold")
            continue
        combo_type = str(base_meta.get("type", "CP")).upper()

        legs_raw = base_meta.get("legs")
        legs: List[str] = []
        if isinstance(legs_raw, Sequence) and not isinstance(legs_raw, (bytes, bytearray, str)):
            legs = [str(val) for val in legs_raw]
        elif isinstance(legs_raw, Mapping):
            legs = [str(val) for val in legs_raw.values()]

        if not legs:
            for entry in candidate:
                if isinstance(entry, Mapping) and entry.get("id") not in (None, ""):
                    legs.append(str(entry["id"]))

        legs_details_raw = base_meta.get("legs_details")
        legs_details: List[Dict[str, Any]] | None = None
        if isinstance(legs_details_raw, Sequence) and not isinstance(
            legs_details_raw, (bytes, bytearray, str)
        ):
            legs_details = []
            for leg in legs_details_raw:
                if isinstance(leg, Mapping):
                    legs_details.append({str(k): v for k, v in leg.items()})
                else:
                    legs_details.append({"id": str(leg)})

        ticket_id = base_meta.get("id") or f"{combo_type}{len(validated) + 1}"
        try:
            stake_val = float(base_meta.get("stake", 0.0))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            stake_val = 0.0

        ticket: Dict[str, Any] = {
            "id": str(ticket_id),
            "type": combo_type,
            "legs": legs,
            "ev_check": {
                "ev_ratio": ev_ratio,
                "roi": roi,
                "payout_expected": payout,
                "sharpe": sharpe,
            },
        }
        if legs_details:
            ticket["legs_details"] = legs_details
        if stake_val > 0:
            ticket["stake"] = stake_val
        if payout > 20 and ev_ratio > 0.5:
            ticket.setdefault("flags", []).append("ALERTE_VALUE")
            add_note("ALERTE_VALUE")
            alerte = True
        validated.append(ticket)

    # Restrict to at most one exotic ticket with best EV ratio
    validated.sort(
        key=lambda t: (
            float(t["ev_check"].get("sharpe", 0.0)),
            float(t["ev_check"].get("ev_ratio", 0.0)),
        ),
        reverse=True,
    )
    validated = validated[:1]

    reasons_unique = list(dict.fromkeys(reasons))
    flags = {"combo": bool(validated), "reasons": {"combo": reasons_unique}}
    if alerte:
        flags["ALERTE_VALUE"] = True

    if validated:
        decision = "accept"
    else:
        decision_reason = "no_candidate"
        if reasons_unique:
            decision_reason = ",".join(reasons_unique)
        decision = f"reject:{decision_reason}"

    return validated, {"notes": notes, "flags": flags, "decision": decision}


def export_tracking_csv_line(
    path: str,
    meta: Mapping[str, Any],
    tickets: Iterable[Mapping[str, Any]],
    stats: Mapping[str, Any],
    *,
    alerte: bool = False,
) -> None:
    """Append a line to the tracking CSV with optional ``ALERTE_VALUE`` column.

    Parameters
    ----------
    path:
        Destination CSV file.
    meta:
        Mapping containing course metadata (``reunion``, ``course`` …).
    tickets:
        Iterable of ticket definitions used to compute counts and stakes.
    stats:
        Mapping providing EV/ROI metrics and other tracking values.
    alerte:
        When ``True`` an ``ALERTE_VALUE`` column is added with the same label.
    """
    tickets_list = list(tickets)

    def _coerce_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    tickets_list = list(tickets)

    prob_panier = stats.get("prob_implicite_panier")
    if prob_panier is None:
        prob_panier = stats.get("prob_panier") or stats.get("probability_panier")
    prob_value = _coerce_float(prob_panier, default=0.0)
    if not prob_value and tickets_list:
        remaining = 1.0
        for ticket in tickets_list:
            p_val = _coerce_float(ticket.get("p"), default=0.0)
            p_val = max(0.0, min(1.0, p_val))
            remaining *= 1.0 - p_val
        prob_value = 1.0 - remaining
        
    data: Dict[str, Any] = {
        "reunion": meta.get("reunion", ""),
        "course": meta.get("course", ""),
        "hippodrome": meta.get("hippodrome", ""),
        "date": meta.get("date", ""),
        "discipline": meta.get("discipline", ""),
        "partants": meta.get("partants", ""),
        "nb_tickets": len(tickets_list),
        "total_stake": sum(_coerce_float(t.get("stake", 0.0)) for t in tickets_list),
        "ev_sp": stats.get("ev_sp", 0.0),
        "ev_global": stats.get("ev_global", 0.0),
        "roi_sp": stats.get("roi_sp", 0.0),
        "roi_global": stats.get("roi_global", 0.0),
        "risk_of_ruin": stats.get("risk_of_ruin", 0.0),
        "clv_moyen": stats.get("clv_moyen", 0.0),
        "model": stats.get("model", ""),
        "prob_implicite_panier": prob_value,
        "ev_simulee_post_arrondi": stats.get("ev_global", 0.0),
        "roi_simule": stats.get("roi_global", 0.0),
        "roi_reel": stats.get("roi_reel", stats.get("roi_real", 0.0)),
        "sharpe": stats.get("sharpe", stats.get("ev_over_std", 0.0)),
        "drift_sign": stats.get("drift_sign", 0),
    }

    header = list(CSV_HEADER)
    for extra in [
        "prob_implicite_panier",
        "ev_simulee_post_arrondi",
        "roi_simule",
        "roi_reel",
        "sharpe",
        "drift_sign",
    ]:
        if extra not in header:
            header.append(extra)
    if alerte:
        header.append("ALERTE_VALUE")
        data["ALERTE_VALUE"] = "ALERTE_VALUE"

    append_csv_line(path, data, header=header)


__all__ = [
    "compute_overround_cap",
    "filter_exotics_by_overround",
    "validate_exotics_with_simwrapper",
    "export_tracking_csv_line",
]
