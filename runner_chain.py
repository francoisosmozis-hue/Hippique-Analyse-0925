from __future__ import annotations

"""Utilities for validating exotic tickets and exporting tracking lines.

This module exposes two helper functions used by the pipeline:

``validate_exotics_with_simwrapper`` evaluates combiné tickets via
:func:`simulate_wrapper.evaluate_combo` and retains only the most attractive
candidate based on EV ratio and expected payout. When the combination offers
both a high EV and a large expected payout an ``ALERTE_VALUE`` flag is attached.

``export_tracking_csv_line`` appends a line to the tracking CSV and supports an
optional ``ALERTE_VALUE`` column when the alert flag is present.
"""

from typing import Any, Dict, Iterable, List, Mapping, Tuple

from config.env_utils import get_env

from simulate_wrapper import evaluate_combo
from logging_io import append_csv_line, CSV_HEADER



def validate_exotics_with_simwrapper(
    exotics: Iterable[List[Dict[str, Any]]],
    bankroll: float,
    *,
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
    allow_heuristic:
        Passed through to :func:`evaluate_combo` to allow evaluation without
        calibration data.

    Returns
    -------
    tuple
        ``(tickets, info)`` where ``tickets`` contains at most one validated
        exotic ticket and ``info`` exposes ``notes`` and ``flags`` gathered
        during validation.
    """
    ev_min = get_env("EV_MIN_GLOBAL", 0.0, cast=float)
    payout_min = get_env("MIN_PAYOUT_COMBOS", 0.0, cast=float)

    validated: List[Dict[str, Any]] = []
    notes: List[str] = []
    reasons: List[str] = []
    alerte = False

    for candidate in exotics:
        stats = evaluate_combo(candidate, bankroll, allow_heuristic=allow_heuristic)
        ev_ratio = float(stats.get("ev_ratio", 0.0))
        payout = float(stats.get("payout_expected", 0.0))
        if ev_ratio < ev_min:
            reasons.append("ev_ratio_below_threshold")
            continue
        if payout < payout_min:
            reasons.append("payout_expected_below_threshold")
            continue
        ticket = {
            "id": f"CP{len(validated) + 1}",
            "type": "CP",
            "legs": [t.get("id") for t in candidate],
            "ev_check": {"ev_ratio": ev_ratio, "payout_expected": payout},
        }
        if payout > 20 and ev_ratio > 0.5:
            ticket.setdefault("flags", []).append("ALERTE_VALUE")
            notes.append("ALERTE_VALUE")
            alerte = True
        validated.append(ticket)

    # Restrict to at most one exotic ticket with best EV ratio
    validated.sort(key=lambda t: t["ev_check"]["ev_ratio"], reverse=True)
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

    data: Dict[str, Any] = {
        "reunion": meta.get("reunion", ""),
        "course": meta.get("course", ""),
        "hippodrome": meta.get("hippodrome", ""),
        "date": meta.get("date", ""),
        "discipline": meta.get("discipline", ""),
        "partants": meta.get("partants", ""),
        "nb_tickets": len(tickets_list),
        "total_stake": sum(float(t.get("stake", 0.0)) for t in tickets_list),
        "ev_sp": stats.get("ev_sp", 0.0),
        "ev_global": stats.get("ev_global", 0.0),
        "roi_sp": stats.get("roi_sp", 0.0),
        "roi_global": stats.get("roi_global", 0.0),
        "risk_of_ruin": stats.get("risk_of_ruin", 0.0),
        "clv_moyen": stats.get("clv_moyen", 0.0),
        "model": stats.get("model", ""),
    }

    header = list(CSV_HEADER)
    if alerte:
        header.append("ALERTE_VALUE")
        data["ALERTE_VALUE"] = "ALERTE_VALUE"

    append_csv_line(path, data, header=header)


__all__ = ["validate_exotics_with_simwrapper", "export_tracking_csv_line"]
