"""Utilities for simple SP dutching and EV simulations."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence

from ev_calculator import compute_ev_roi
from simulate_wrapper import simulate_wrapper


def implied_probs(odds_list: Sequence[float]) -> List[float]:
    """Return normalised implied probabilities from decimal ``odds_list``."""

    inv = [1.0 / float(o) if float(o) > 0 else 0.0 for o in odds_list]
    total = sum(inv)
    if total <= 0:
        return [0.0] * len(inv)
    return [x / total for x in inv]


def kelly_fraction(p: float, b: float) -> float:
    """Return the Kelly fraction for win probability ``p`` and net odds ``b``."""

    if b <= 0:
        return 0.0
    f = (b * p - (1.0 - p)) / b
    return max(0.0, min(1.0, f))


def allocate_dutching_sp(cfg: Dict[str, float], runners: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], float]:
    """Allocate SP dutching stakes according to a Kelly share with 60% cap.

    When each ``runner`` provides an estimated win probability ``p``, those
    probabilities are used directly.  Otherwise, probabilities are inferred
    from decimal ``odds`` via :func:`implied_probs`.
    """

    if not runners:
        return [], 0.0

    odds = [float(r["odds"]) for r in runners]
    if all("p" in r for r in runners):
        probs = [float(r["p"]) for r in runners]
    else:
        probs = implied_probs(odds)
    budget = float(cfg.get("BUDGET_TOTAL", 0.0)) * float(cfg.get("SP_RATIO", 1.0))
    cap = float(cfg.get("MAX_VOL_PAR_CHEVAL", 0.60))

    kellys = [kelly_fraction(p, o - 1.0) for p, o in zip(probs, odds)]
    total_kelly = sum(kellys) or 1.0

    tickets: List[Dict[str, Any]] = []
    ev_sp = 0.0
    for runner, p, o, k in zip(runners, probs, odds, kellys):
        f = min(cap, k / total_kelly)
        stake = round(budget * f, 2)
        if stake <= 0:
            continue
        ticket = {
            "type": "SP",
            "id": runner.get("id"),
            "name": runner.get("name", runner.get("id")),
            "odds": o,
            "stake": stake,
        }
        tickets.append(ticket)
        ev_sp += stake * (p * (o - 1.0) - (1.0 - p))
    return tickets, ev_sp


def gate_ev(
    cfg: Dict[str, float],
    ev_sp: float,
    ev_global: float,
    min_payout_combos: float,
) -> Dict[str, bool]:
    """Return activation flags for SP and combinés based on EV thresholds."""

    sp_budget = float(cfg.get("BUDGET_TOTAL", 0.0)) * float(cfg.get("SP_RATIO", 1.0))
    sp_ok = ev_sp >= float(cfg.get("EV_MIN_SP", 0.0)) * sp_budget

    combo_ok = (
        ev_global >= float(cfg.get("EV_MIN_GLOBAL", 0.0)) * float(cfg.get("BUDGET_TOTAL", 0.0))
        and min_payout_combos >= float(cfg.get("MIN_PAYOUT_COMBOS", 0.0))
    )

    return {"sp": sp_ok, "combo": combo_ok}


def simulate_ev_batch(tickets: List[Dict[str, Any]], bankroll: float) -> Dict[str, Any]:
    """Return EV/ROI statistics for ``tickets`` given a ``bankroll``.

    This is a thin wrapper around :func:`compute_ev_roi` that also hooks into
    :func:`simulate_wrapper` to estimate probabilities of combined bets.
    """
    return compute_ev_roi(tickets, budget=bankroll, simulate_fn=simulate_wrapper)
