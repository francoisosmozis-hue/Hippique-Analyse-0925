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

from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from simulate_wrapper import evaluate_combo
from logging_io import append_csv_line, CSV_HEADER



def validate_exotics_with_simwrapper(
    exotics: Iterable[List[Dict[str, Any]]],
    bankroll: float,
    *,
    ev_min: float = 0.0,
    roi_min: float = 0.0,
    payout_min: float = 0.0,
    sharpe_min: float = 0.0,
    allow_heuristic: bool = True,
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

    def add_note(label: str) -> None:
        if label not in notes_seen:
            notes.append(label)
            notes_seen.add(label)
            
    for candidate in exotics:
        if not candidate:
            continue
            
        stats = evaluate_combo(candidate, bankroll, allow_heuristic=allow_heuristic)
        ev_ratio = float(stats.get("ev_ratio", 0.0))
        roi = float(stats.get("roi", 0.0))
        payout = float(stats.get("payout_expected", 0.0))
        sharpe = float(stats.get("sharpe", 0.0))
        stats_notes = [str(n) for n in stats.get("notes", [])]
        for note in stats_notes:
            add_note(note)
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
        base_meta: Mapping[str, Any] = {}
        for entry in candidate:
            if isinstance(entry, Mapping):
                base_meta = entry
                break

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

    flags = {"combo": bool(validated), "reasons": {"combo": reasons}}
    if alerte:
        flags["ALERTE_VALUE"] = True

    return validated, {"notes": notes, "flags": flags}


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


__all__ = ["validate_exotics_with_simwrapper", "export_tracking_csv_line"]
