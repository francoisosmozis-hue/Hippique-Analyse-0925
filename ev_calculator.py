"""Utility for computing expected value (EV) and return on investment (ROI) for betting tickets.

This module exposes :func:`compute_ev_roi` which handles single bets,
SP dutching groups and combined bets via ``simulate_wrapper``.  Stakes are
capped to 60% of the Kelly criterion recommended stake.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List

# ``simulate_wrapper`` is expected to be provided by the caller's environment.
try:  # pragma: no cover - optional dependency
    from simulate_wrapper import simulate_wrapper  # type: ignore
except Exception:  # pragma: no cover - handled gracefully
    simulate_wrapper = None  # type: ignore

KELLY_CAP = 0.60


def _kelly_fraction(p: float, odds: float) -> float:
    """Return the Kelly fraction for given probability and odds."""
    return max((p * odds - 1) / (odds - 1), 0.0)


def _apply_dutching(tickets: Iterable[Dict[str, Any]]) -> None:
    """Normalise stakes inside each dutching group so that profit is identical.

    Tickets that share the same ``dutching`` key are adjusted so that each
    ticket's potential profit ``stake * (odds - 1)`` is constant while keeping
    the total stake of the group unchanged.
    """
    groups: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for t in tickets:
        group = t.get("dutching")
        if group is not None:
            groups[group].append(t)

    for group_tickets in groups.values():
         valid_tickets = []
        for t in group_tickets:
            odds = t["odds"]
            if odds <= 1:
                raise ValueError(
                    f"Odds must be greater than 1 for dutching, got {odds}"
                )
            valid_tickets.append(t)

        total = sum(t.get("stake", 0) for t in valid_tickets)
        weights = [1 / (t["odds"] - 1) for t in valid_tickets]
        weight_sum = sum(weights)
        for t, w in zip(valid_tickets, weights):
            t["stake"] = total * w / weight_sum


def compute_ev_roi(tickets: List[Dict[str, Any]], budget: float) -> Dict[str, Any]:
    """Compute EV and ROI for a list of betting tickets.

    Parameters
    ----------
    tickets:
        Each ticket is a mapping containing ``p`` (probability), ``odds`` and an
        optional ``stake``.  Tickets forming a dutching SP group may share a
        ``dutching`` identifier.  Combined bets may provide ``legs`` and omit
        ``p``; in that case ``simulate_wrapper`` is used to estimate the
        probability.
    budget:
        Bankroll used for Kelly criterion computations.

    Returns
    -------
    dict
        A dictionary with keys ``ev`` (global expected value), ``roi`` (overall
        ROI), ``green`` (boolean flag, ``True`` when EV is positive) and
        ``total_stake_normalized`` (sum of stakes after potential normalization
        against the budget).
    """
    # First adjust stakes for dutching groups
    _apply_dutching(tickets)

    total_ev = 0.0
    total_stake = 0.0

    for t in tickets:
        p = t.get("p")
        if p is None and simulate_wrapper and "legs" in t:
            p = simulate_wrapper(t["legs"])  # type: ignore
        if p is None:
            raise ValueError("Ticket must include probability 'p' or legs for simulation")
        odds = t["odds"]
        if not (0 < p < 1):
            raise ValueError(f"Probability 'p' must be between 0 and 1, got {p}")
        if odds <= 1:
            raise ValueError(f"Odds must be greater than 1, got {odds}")

        kelly_stake = _kelly_fraction(p, odds) * budget
        stake_input = t.get("stake", kelly_stake)
        stake = min(stake_input, kelly_stake * KELLY_CAP)
        t["stake"] = stake
        ev = stake * (p * (odds - 1) - (1 - p))
        total_ev += ev
        total_stake += stake

    if total_stake > budget:
        ratio = budget / total_stake
        for t in tickets:
            t["stake"] *= ratio
        total_ev *= ratio
        total_stake_normalized = budget
    else:
        total_stake_normalized = total_stake

    roi_total = total_ev / total_stake_normalized if total_stake_normalized else 0.0
    green_flag = total_ev > 0
    return {
        "ev": total_ev,
        "roi": roi_total,
        "green": green_flag,
        "total_stake_normalized": total_stake_normalized,
    }


__all__ = ["compute_ev_roi"]
