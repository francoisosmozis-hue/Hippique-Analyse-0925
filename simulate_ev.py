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
    kelly_coef = float(cfg.get("KELLY_FRACTION", 0.5))

    tickets: List[Dict[str, Any]] = []
    ev_sp = 0.0
    for runner, p, o, k in zip(runners, probs, odds, kellys):
        f = min(cap, k * kelly_coef / total_kelly)
        stake = round(budget * f, 2)
        if stake <= 0 or stake < float(cfg["MIN_STAKE_SP"]):
            continue
        ev_ticket = stake * (p * (o - 1.0) - (1.0 - p))
        ticket = {
            "type": "SP",
            "id": runner.get("id"),
            "name": runner.get("name", runner.get("id")),
            "odds": o,
            "stake": stake,
            "p": p,
            "ev_ticket": ev_ticket,
        }
        tickets.append(ticket)
        ev_sp += ev_ticket
    return tickets, ev_sp


def gate_ev(
    cfg: Dict[str, float],
    ev_sp: float,
    ev_global: float,
    roi_sp: float,
    roi_global: float,
    min_payout_combos: float,
    risk_of_ruin: float = 0.0,
    ev_over_std: float = 0.0,
) -> Dict[str, Any]:
    """Return activation flags and failure reasons for SP and combinés."""

    reasons = {"sp": [], "combo": []}
    
    sp_budget = float(cfg.get("BUDGET_TOTAL", 0.0)) * float(cfg.get("SP_RATIO", 1.0))
    
    if ev_sp < float(cfg.get("EV_MIN_SP", 0.0)) * sp_budget:
        reasons["sp"].append("EV_MIN_SP")
    if roi_sp < float(cfg.get("ROI_MIN_SP", 0.0)):
        reasons["sp"].append("ROI_MIN_SP")

    if ev_global < float(cfg.get("EV_MIN_GLOBAL", 0.0)) * float(cfg.get("BUDGET_TOTAL", 0.0)):
        reasons["combo"].append("EV_MIN_GLOBAL")
    if roi_global < float(cfg.get("ROI_MIN_GLOBAL", 0.0)):
        reasons["combo"].append("ROI_MIN_GLOBAL")
    if min_payout_combos < float(cfg.get("MIN_PAYOUT_COMBOS", 0.0)):
        reasons["combo"].append("MIN_PAYOUT_COMBOS")

    ror_max = float(cfg.get("ROR_MAX", 1.0))
    if risk_of_ruin > ror_max:
        reasons["sp"].append("ROR_MAX")
        reasons["combo"].append("ROR_MAX")

    sharpe_min = float(cfg.get("SHARPE_MIN", 0.0))
    if ev_over_std < sharpe_min:
        reasons["sp"].append("SHARPE_MIN")
        reasons["combo"].append("SHARPE_MIN")

    sp_ok = not reasons["sp"]
    combo_ok = not reasons["combo"]

    return {"sp": sp_ok, "combo": combo_ok, "reasons": reasons}


def simulate_ev_batch(tickets: List[Dict[str, Any]], bankroll: float) -> Dict[str, Any]:
    """Return EV/ROI statistics for ``tickets`` given a ``bankroll``.

    This is a thin wrapper around :func:`compute_ev_roi` that also hooks into
    :func:`simulate_wrapper` to estimate probabilities of combined bets.
    """
    stats = compute_ev_roi(tickets, budget=bankroll, simulate_fn=simulate_wrapper)
    return stats
