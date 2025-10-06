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

import argparse
import csv
import json
import logging
import os
import re
import unicodedata
from pathlib import Path


from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from scripts.simulate_ev import simulate_ev_batch
from scripts.simulate_wrapper import PAYOUT_CALIBRATION_PATH
from logging_io import append_csv_line, CSV_HEADER


logger = logging.getLogger(__name__)

try:
    MAX_COMBO_OVERROUND = float(os.getenv("MAX_COMBO_OVERROUND", "1.30"))
except (TypeError, ValueError):  # pragma: no cover - defensive fallback
    MAX_COMBO_OVERROUND = 1.30

CALIB_PATH = os.getenv("CALIB_PATH", str(PAYOUT_CALIBRATION_PATH))


def _resolve_calibration_path() -> tuple[Path, bool]:
    """Return the payout calibration path and whether it exists."""

    candidates: list[Path] = []
    if CALIB_PATH:
        try:
            candidates.append(Path(CALIB_PATH))
        except TypeError:  # pragma: no cover - defensive guard
            pass
    for candidate in (
        PAYOUT_CALIBRATION_PATH,
        Path("config/payout_calibration.yaml"),
        Path("calibration/payout_calibration.yaml"),
    ):
        if candidate not in candidates:
            candidates.append(candidate)

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
    default_cap: float = 1.30,
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
    calibration: str | os.PathLike[str] | None = None,
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
        Deprecated toggle kept for backwards compatibility.  Any truthy value
        is ignored and evaluation proceeds only with a valid calibration file.
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
    if allow_heuristic:
        logger.warning(
            "[COMBO] Heuristic override requested; enforcing calibration-only "
            "evaluation. Use the versioned payout calibration skeleton (version: 1) "
            "if you need to refresh the file."
        )
        allow_heuristic = False

    validated: List[Dict[str, Any]] = []
    notes: List[str] = []
    notes_seen: set[str] = set()
    reasons: List[str] = []
    alerte = False

    if calibration is not None:
        try:
            calib_path = Path(calibration)
        except TypeError:  # pragma: no cover - defensive fallback
            calib_path = Path(str(calibration))
        has_calib = calib_path.exists()
    else:
        calib_path, has_calib = _resolve_calibration_path()
    if not has_calib:
        logger.warning(
            "[COMBO] Calibration payout introuvable (%s). Renseignez "
            "config/payout_calibration.yaml en suivant le squelette versionné "
            "(version: 1 → couple_place/trio/ze4) pour réactiver les combinés.",
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

        stats = evaluate_combo(
            candidate,
            bankroll,
            calibration=calib_path,
            allow_heuristic=allow_heuristic,
        )
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


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_probability(value: Any) -> float | None:
    prob = _coerce_float(value)
    if prob is None:
        return None
    if prob <= 0.0 or prob >= 1.0:
        return None
    return prob


def _normalise_runner_id(record: Mapping[str, Any], fallback_index: int) -> str:
    for key in ("id", "runner_id", "num", "number", "participant", "code"):
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return str(fallback_index)

_PLACE_ODDS_KEYS = (
    "odds_place",
    "place_odds",
    "placeOdds",
    "place",
    "cote_place",
    "decimal_place_odds",
    "place_decimal_odds",
    "odds_place_dec",
)


def _normalise_runner_name(record: Mapping[str, Any]) -> str | None:
    for key in ("name", "nom", "horse", "runner", "participant_label"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    value = record.get("id")
    if value not in (None, ""):
        return str(value)
    return None


_PLACE_ODDS_KEYS = (
    "odds_place",
    "place_odds",
    "placeOdds",
    "place",
    "cote_place",
    "decimal_place_odds",
    "place_decimal_odds",
    "odds_place_dec",
)


def _resolve_odds(record: Mapping[str, Any]) -> float | None:
    odds_keys = (
        "odds_place",
        "place_odds",
        "odds_sp",
        "odds",
        "cote_place",
        "expected_odds",
        "closing_odds",
    )
    for key in odds_keys:
        if key not in record:
            continue
        value = _coerce_float(record.get(key))
        if value is None or value <= 1.0:
            continue
        return value
    return None


def _resolve_place_odds(record: Mapping[str, Any]) -> float | None:
    for key in _PLACE_ODDS_KEYS:
        if key not in record:
            continue
        value = _coerce_float(record.get(key))
        if value is None or value <= 1.0:
            continue
        return value

    indicator_fields = ("bet_type", "type", "label", "market_type")
    indicator_text = " ".join(
        str(record.get(field, "") or "") for field in indicator_fields
    ).lower()
    if "place" not in indicator_text:
        return None

    fallback_keys = (
        "odds",
        "cote",
        "odd",
        "decimal_odds",
        "odds_dec",
        "odds_sp",
        "expected_odds",
        "closing_odds",
    )
    for key in fallback_keys:
        if key not in record:
            continue
        value = _coerce_float(record.get(key))
        if value is None or value <= 1.0:
            continue
        return value
    return None


def _resolve_probability(record: Mapping[str, Any]) -> float | None:
    prob_keys = (
        "p_place",
        "prob_place",
        "p",
        "probability",
        "prob",
        "p_true",
        "p_imp",
        "p_imp_h5",
    )
    for key in prob_keys:
        if key not in record:
            continue
        prob = _coerce_probability(record.get(key))
        if prob is not None:
            return prob
    return None


def _load_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def _extract_sp_candidates(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        odds = _resolve_odds(row)
        if odds is None:
            continue
        place_odds = _resolve_place_odds(row)
        if place_odds is not None:
            odds = place_odds
        probability = _resolve_probability(row)
        candidate = {
            "id": _normalise_runner_id(row, idx),
            "name": _normalise_runner_name(row),
            "odds": odds,
        }
        if place_odds is not None:
            candidate["odds_place"] = place_odds
        if probability is not None:
            candidate["p"] = probability
        candidates.append(candidate)
    return candidates


def _prepare_sp_legs(
    legs: Sequence[Mapping[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not legs:
        return [], []

    prepared: list[dict[str, Any]] = []
    missing_ids: list[str] = []
    for index, leg in enumerate(legs):
        if not isinstance(leg, Mapping):
            continue
        place_odds = _resolve_place_odds(leg)
        if place_odds is None or place_odds <= 1.0:
            missing_ids.append(_normalise_runner_id(leg, index))
            continue
        entry = {str(key): value for key, value in leg.items()}
        entry["odds_place"] = place_odds
        entry["odds"] = place_odds
        prepared.append(entry)
    return prepared, missing_ids


def estimate_sp_ev(
    legs: Sequence[Mapping[str, Any]] | None,
) -> tuple[float | None, bool]:
    """Return the average EV ratio for ``legs`` with valid place odds."""

    if not legs:
        return None, False

    filtered, missing_ids = _prepare_sp_legs(legs)
    unique_missing = list(dict.fromkeys(missing_ids))
    some_missing = bool(unique_missing) or len(filtered) < sum(
        1 for leg in legs if isinstance(leg, Mapping)
    )
    if unique_missing:
        logger.warning(
            "[SP] Place odds missing for legs: %s",
            ", ".join(unique_missing),
        )

    if len(filtered) < 2:
        return None, some_missing

    total_ev = 0.0
    total_stake = 0.0
    for leg in filtered:
        odds_value = _coerce_float(leg.get("odds_place"))
        if odds_value is None or odds_value <= 1.0:
            odds_value = _coerce_float(leg.get("odds"))
        if odds_value is None or odds_value <= 1.0:
            some_missing = True
            continue
        probability = _resolve_probability(leg)
        if probability is None:
            probability = 1.0 / odds_value if odds_value > 0 else None
        if probability is None or probability <= 0.0 or probability >= 1.0:
            some_missing = True
            probability = None
        if probability is None:
            continue
        total_ev += probability * odds_value - 1.0
        total_stake += 1.0

    if total_stake < 2:
        return None, some_missing

    ev_ratio = total_ev / total_stake if total_stake else None
    return ev_ratio, some_missing


def _split_legs(text: str) -> list[str]:
    if not text:
        return []
    cleaned = text.strip()
    if not cleaned:
        return []
    if cleaned.startswith("[") or cleaned.startswith("{"):
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(parsed, list):
                return [str(item) for item in parsed if str(item).strip()]
    if "|" in cleaned:
        parts = cleaned.split("|")
    else:
        parts = cleaned.split(",")
    legs = [part.strip() for part in parts if part.strip()]
    return [str(part) for part in legs]


def _extract_combo_candidates(rows: Sequence[Mapping[str, Any]]) -> list[list[dict[str, Any]]]:
    combos: list[list[dict[str, Any]]] = []
    json_fields = ("combo_json", "combo_candidates", "exotics", "combinaisons", "combos")
    for row in rows:
        for field in json_fields:
            value = row.get(field)
            if not isinstance(value, str) or not value.strip():
                continue
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, Mapping):
                        combo = _normalize_combo_record(item)
                        if combo:
                            combos.append([combo])
            elif isinstance(parsed, Mapping):
                combo = _normalize_combo_record(parsed)
                if combo:
                    combos.append([combo])
        combo = _normalize_combo_record(row)
        if combo:
            combos.append([combo])
    # Deduplicate combos by identifier/legs/type triplet
    seen: set[tuple[str, tuple[str, ...]]] = set()
    unique: list[list[dict[str, Any]]] = []
    for candidate in combos:
        if not candidate:
            continue
        ticket = candidate[0]
        key = (str(ticket.get("type", "")), tuple(sorted(ticket.get("legs", []))))
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _normalize_combo_record(record: Mapping[str, Any]) -> dict[str, Any] | None:
    legs_value: Any = None
    for key in ("combo_legs", "legs", "participants", "combination", "combinaison"):
        value = record.get(key)
        if value:
            legs_value = value
            break
    legs: list[str] = []
    if isinstance(legs_value, str):
        legs = _split_legs(legs_value)
    elif isinstance(legs_value, Sequence) and not isinstance(legs_value, (bytes, bytearray, str)):
        legs = [str(item) for item in legs_value if str(item).strip()]
    elif isinstance(legs_value, Mapping):
        legs = [str(v) for v in legs_value.values() if str(v).strip()]
    if not legs:
        return None
    odds_value: float | None = None
    for key in ("combo_odds", "odds", "payout", "expected_odds", "cote"):
        odds_value = _coerce_float(record.get(key))
        if odds_value is not None and odds_value > 1.0:
            break
    if odds_value is None or odds_value <= 1.0:
        return None
    stake_value = _coerce_float(record.get("combo_stake"))
    if stake_value is None or stake_value <= 0.0:
        stake_value = 1.0
    combo_type = str(record.get("combo_type") or record.get("type") or "CP").upper()
    ticket = {
        "id": str(record.get("combo_id") or record.get("id") or "|".join(legs)),
        "type": combo_type,
        "legs": legs,
        "odds": float(odds_value),
        "stake": float(stake_value),
    }
    prob = _coerce_probability(record.get("combo_p") or record.get("p"))
    if prob is not None:
        ticket["p"] = prob
    return ticket


def _extract_overround(rows: Sequence[Mapping[str, Any]]) -> float | None:
    for row in rows:
        for key in ("overround", "combo_overround", "overround_cp", "overround_total"):
            value = _coerce_float(row.get(key))
            if value is not None and value > 0:
                return value
    return None


def _safe_json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=False)


def _write_tracking_snapshot(path: Path, payload: Mapping[str, Any]) -> None:
    header = ("status", "reasons", "guards", "tickets")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerow(
            {
                "status": payload.get("status", ""),
                "reasons": _safe_json_dumps(payload.get("reasons", [])),
                "guards": _safe_json_dumps(payload.get("guards", {})),
                "tickets": _safe_json_dumps(payload.get("tickets", [])),
            }
        )


__all__ = [
    "compute_overround_cap",
    "filter_exotics_by_overround",
    "validate_exotics_with_simwrapper",
    "export_tracking_csv_line",
    "build_cli_parser",
    "main",
]


def build_cli_parser() -> argparse.ArgumentParser:
    """Return an argument parser exposing runner-chain utilities."""

    parser = argparse.ArgumentParser(description="Evaluate runner chain tickets for a course")
    parser.add_argument(
        "course_dir",
        help="Directory containing je_stats.csv and chronos.csv for the course",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=5.0,
        help="Total bankroll dedicated to the course (default: 5)",
    )
    parser.add_argument(
        "--overround-max",
        dest="overround_max",
        type=float,
        default=1.30,
        help="Maximum accepted market overround for exotic tickets (default: 1.30)",
    )
    parser.add_argument(
        "--ev-min-exotic",
        dest="ev_min_exotic",
        type=float,
        default=0.40,
        help="Minimum EV ratio required for exotic tickets (default: 0.40)",
    )
    parser.add_argument(
        "--payout-min-exotic",
        dest="payout_min_exotic",
        type=float,
        default=10.0,
        help="Minimum expected payout required for exotic tickets (default: 10)",
    )
    parser.add_argument(
        "--ev-min-sp",
        dest="ev_min_sp",
        type=float,
        default=0.40,
        help="Minimum EV ratio required for SP dutching (default: 0.40)",
    )
    parser.add_argument(
        "--roi-min-global",
        dest="roi_min_global",
        type=float,
        default=0.20,
        help="Minimum ROI required for the global ticket pack (default: 0.20)",
    )
    parser.add_argument(
        "--kelly-frac",
        dest="kelly_frac",
        type=float,
        default=0.4,
        help="Kelly fraction applied to SP dutching (default: 0.4)",
    )
    parser.add_argument(
        "--analysis-path",
        dest="analysis_path",
        default=None,
        help="Optional override for the analysis_H5.json destination",
    )
    parser.add_argument(
        "--tracking-path",
        dest="tracking_path",
        default=None,
        help="Optional override for the tracking.csv destination",
    )
    parser.add_argument(
        "--calibration",
        default=str(PAYOUT_CALIBRATION_PATH),
        help="Path to payout_calibration.yaml used for combo validation (default: repository calibration)",
    )
    return parser


def _analyse_course(
    course_dir: Path,
    *,
    budget: float,
    overround_max: float,
    ev_min_exotic: float,
    payout_min_exotic: float,
    ev_min_sp: float,
    roi_min_global: float,
    kelly_frac: float,
    calibration: str | None,
) -> Dict[str, Any]:
    course_dir = course_dir.resolve()
    je_path = course_dir / "je_stats.csv"
    chronos_path = course_dir / "chronos.csv"

    missing: list[str] = []
    for path, label in ((je_path, "je_stats"), (chronos_path, "chronos")):
        if not path.is_file():
            missing.append(label)
    if missing:
        guards = {
            "jouable": False,
            "reason": "data_missing",
            "missing": missing,
        }
        return {
            "status": "aborted",
            "reasons": ["data_missing"],
            "guards": guards,
            "tickets": [],
        }

    rows = _load_csv_rows(je_path)
    try:
        chronos_rows = _load_csv_rows(chronos_path)
    except Exception:  # pragma: no cover - resilience for malformed chronos
        chronos_rows = []

    guards: Dict[str, Any] = {
        "course_dir": str(course_dir),
        "je_rows": len(rows),
        "chronos_rows": len(chronos_rows),
        "calibration": calibration,
    }
    meta: Dict[str, Any] = {"course_dir": str(course_dir)}
    rc_match = re.match(r"^(R\d+)(C\d+)$", course_dir.name.upper())
    if rc_match:
        meta["reunion"], meta["course"] = rc_match.groups()

    reasons: list[str] = []

    sp_candidates_all = _extract_sp_candidates(rows)
    guards["sp_candidates"] = len(sp_candidates_all)

    sp_ev_estimate, some_odds_missing = estimate_sp_ev(sp_candidates_all)
    guards["sp_some_odds_missing"] = some_odds_missing
    meta["sp_some_odds_missing"] = some_odds_missing
    if sp_ev_estimate is not None:
        guards["sp_ev_estimate"] = sp_ev_estimate

    sp_candidates, _ = _prepare_sp_legs(sp_candidates_all)
    guards["sp_candidates_with_place_odds"] = len(sp_candidates)
    sp_tickets: list[dict[str, Any]] = []
    ev_sp_total = 0.0
    sp_status = "ok"

    if len(sp_candidates_all) < 2:
        reasons.append("sp_insufficient_candidates")
        if len(sp_candidates) < 2:
            sp_status = "insufficient_data"
            if "sp_insufficient_data" not in reasons:
                reasons.append("sp_insufficient_data")

    guards["sp_status"] = sp_status
    meta["sp_status"] = sp_status

    if sp_status == "ok":
        cfg = {
            "BUDGET_TOTAL": float(budget),
            "SP_RATIO": 1.0,
            "KELLY_FRACTION": float(kelly_frac),
            "MAX_VOL_PAR_CHEVAL": 0.60,
        }
        sp_tickets_alloc, ev_sp = allocate_dutching_sp(cfg, sp_candidates)
        sp_tickets = [dict(ticket) for ticket in sp_tickets_alloc]
        guards["sp_tickets"] = len(sp_tickets)
        ev_sp_total = ev_sp
        if len(sp_tickets) < 2:
            reasons.append("sp_insufficient_after_allocation")
            sp_tickets = []
        else:
            cap = float(budget) * 0.60
            for ticket in sp_tickets:
                stake = float(ticket.get("stake", 0.0))
                if stake > cap:
                    ticket["stake"] = cap
            ev_sp_ratio = (ev_sp / budget) if budget > 0 else 0.0
            guards["ev_sp_ratio"] = ev_sp_ratio
            if ev_sp_ratio < ev_min_sp:
                reasons.append("sp_ev_below_min")
                sp_tickets = []
    else:
        guards["sp_tickets"] = 0
    combo_candidates = _extract_combo_candidates(rows)
    guards["combo_candidates"] = len(combo_candidates)
    combo_overround = _extract_overround(rows)
    if combo_overround is not None:
        guards["combo_overround"] = combo_overround

    combo_tickets: list[dict[str, Any]] = []
    combo_info: Dict[str, Any] = {"notes": [], "flags": {}}
    guards.setdefault("combo_notes", [])
    guards.setdefault("combo_flags", {})
    guards.setdefault("combo_decision", None)
    if combo_candidates:
        if combo_overround is not None and combo_overround > overround_max:
            reasons.append("combo_overround_exceeded")
        else:
            combo_tickets, combo_info = validate_exotics_with_simwrapper(
                combo_candidates,
                bankroll=float(budget),
                ev_min=float(ev_min_exotic),
                roi_min=float(roi_min_global),
                payout_min=float(payout_min_exotic),
                sharpe_min=0.0,
                allow_heuristic=False,
                calibration=calibration,
            )
            guards["combo_notes"] = list(combo_info.get("notes", []))
            guards["combo_flags"] = combo_info.get("flags", {})
            guards["combo_decision"] = combo_info.get("decision")
            if not combo_tickets:
                decision = combo_info.get("decision")
                if decision:
                    reasons.append(f"combo_{decision}")
    tickets = sp_tickets + combo_tickets

    if sp_status != "ok":
        tickets = []
        sp_tickets = []
        combo_tickets = []

    stats: Dict[str, Any] = {}
    if sp_status == "ok" and tickets:
        try:
            stats = simulate_ev_batch(
                [dict(ticket) for ticket in tickets],
                bankroll=float(budget),
                kelly_cap=float(kelly_frac),
            )
        except Exception as exc:  # pragma: no cover - robustness guard
            logger.exception("EV simulation failed: %s", exc)
            reasons.append("ev_simulation_failed")
            tickets = []
            stats = {}
    guards["ev_sp_total"] = ev_sp_total
    if stats:
        guards["ev_global"] = stats.get("ev", 0.0)
        guards["ev_ratio"] = stats.get("ev_ratio", 0.0)
        guards["roi_global"] = stats.get("roi", 0.0)
        if float(stats.get("roi", 0.0)) < roi_min_global:
            reasons.append("roi_global_below_min")
            sp_tickets = []
            combo_tickets = []
            tickets = []

    jouable = bool(tickets)
    guards["jouable"] = jouable
    if not jouable and reasons:
        guards.setdefault("reason", reasons[0])

    guards["sp_final"] = len(sp_tickets)
    guards["combo_final"] = len(combo_tickets)

    status = "ok" if jouable else "abstain"
    payload: Dict[str, Any] = {
        "status": status,
        "reasons": list(dict.fromkeys(reasons)),
        "guards": guards,
        "tickets": tickets,
    }
    if meta:
        payload["meta"] = meta
    if stats:
        payload["stats"] = {
            "ev": stats.get("ev", 0.0),
            "roi": stats.get("roi", 0.0),
            "ev_ratio": stats.get("ev_ratio", 0.0),
        }
    return payload


def _format_excel_command(course_dir: Path, analysis_path: Path) -> str:
    rc = course_dir.name.upper()
    meeting: str | None = None
    race: str | None = None
    match = re.match(r"^(R\d+)(C\d+)$", rc)
    if match:
        meeting, race = match.groups()
    arrivee = course_dir / "arrivee.json"
    parts = ["python", "post_course.py", "--arrivee", str(arrivee), "--tickets", str(analysis_path)]
    if meeting:
        parts.extend(["--reunion", meeting])
    if race:
        parts.extend(["--course", race])
    return " ".join(parts)


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry point configuring the payout calibration path."""

    parser = build_cli_parser()
    args = parser.parse_args(argv)

    course_dir = Path(args.course_dir)
    analysis_path = Path(args.analysis_path) if args.analysis_path else course_dir / "analysis_H5.json"
    tracking_path = Path(args.tracking_path) if args.tracking_path else course_dir / "tracking.csv"

    global CALIB_PATH
    CALIB_PATH = str(args.calibration)
    os.environ["CALIB_PATH"] = CALIB_PATH

    payload = _analyse_course(
        course_dir,
        budget=float(args.budget),
        overround_max=float(args.overround_max),
        ev_min_exotic=float(args.ev_min_exotic),
        payout_min_exotic=float(args.payout_min_exotic),
        ev_min_sp=float(args.ev_min_sp),
        roi_min_global=float(args.roi_min_global),
        kelly_frac=float(args.kelly_frac),
        calibration=CALIB_PATH,
    )

    analysis_path.parent.mkdir(parents=True, exist_ok=True)
    analysis_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_tracking_snapshot(tracking_path, payload)

    command = _format_excel_command(course_dir, analysis_path)
    print(command)


if __name__ == "__main__":
    main()
