"""Utility for computing expected value (EV) and return on investment (ROI) for betting tickets.

This module exposes :func:`compute_ev_roi` which handles single bets,
SP dutching groups and combined bets via a caller-provided simulation function
(``simulate_fn``).  Stakes are capped to 60% of the Kelly criterion
recommended stake.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Dict, Iterable, List, Optional

# ``simulate_wrapper`` is an optional dependency kept for backward compatibility.
try:  # pragma: no cover - optional dependency
    from simulate_wrapper import simulate_wrapper  # type: ignore
except Exception:  # pragma: no cover - handled gracefully
    simulate_wrapper = None  # type: ignore

KELLY_CAP = 0.60


def _kelly_fraction(p: float, odds: float) -> float:
     """Return the Kelly fraction for given probability and odds.

    Parameters
    ----------
    p:
        Estimated probability of winning the bet.  Must satisfy ``0 < p < 1``.
    odds:
        Decimal odds offered for the bet.  Must be greater than ``1``.

    Returns
    -------
    float
        The fraction of the bankroll to wager according to the Kelly
        criterion, capped at zero when the edge is negative.

    Raises
    ------
    ValueError
        If ``p`` is not in the interval ``(0, 1)`` or ``odds`` is not greater
        than ``1``.
    """

    if not 0 < p < 1:
        raise ValueError("probability must be in (0,1)")
    if odds <= 1:
        raise ValueError("odds must be > 1")

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
        # Skip tickets with invalid odds to avoid division by zero when
        # computing ``1 / (odds - 1)``.  These tickets are left untouched and
        # will later trigger validation errors in ``compute_ev_roi``.
        valid_tickets = [t for t in group_tickets if t.get("odds", 0) > 1]
        if len(valid_tickets) < 2:
            continue

        total = sum(t.get("stake", 0) for t in valid_tickets)
        weights = [1 / (t["odds"] - 1) for t in valid_tickets]
        weight_sum = sum(weights)
        for t, w in zip(valid_tickets, weights):
            t["stake"] = total * w / weight_sum


def compute_ev_roi(
    tickets: List[Dict[str, Any]],
    budget: float,
    simulate_fn: Optional[Callable[[Iterable[Any]], float]] = None,
) -> Dict[str, Any]:
    """Compute EV and ROI for a list of betting tickets.

    Parameters
    ----------
    tickets:
        Each ticket is a mapping containing ``p`` (probability), ``odds`` and an
        optional ``stake``.  Tickets forming a dutching SP group may share a
        ``dutching`` identifier.  Combined bets may provide ``legs`` and omit
        ``p``; in that case ``simulate_fn`` is used to estimate the
        probability.
    budget:
        Bankroll used for Kelly criterion computations.
    simulate_fn:
        Callable used to estimate the probability of combined bets from their
        ``legs``.  Its signature must be ``legs -> probability``.  Required when
        tickets contain ``legs`` without providing ``p``.

    Returns
    -------
    dict
        A dictionary with keys ``ev`` (global expected value), ``roi`` (overall
        ROI), ``ev_ratio`` (EV relative to the budget) and ``green`` (boolean
        flag).  When ``green`` is ``False`` an additional ``failure_reasons``
        list explains which criteria were not met
    """
    # First adjust stakes for dutching groups
    _apply_dutching(tickets)

    if simulate_fn is None:
        simulate_fn = simulate_wrapper

    total_ev = 0.0
    total_stake = 0.0
    combined_expected_payout = 0.0
    has_combined = False
 
    for t in tickets:
        p = t.get("p")
        if p is None:
            legs = t.get("legs")
            if legs is not None:
                if simulate_fn is None:
                    raise ValueError(
                        "simulate_fn must be provided when tickets include 'legs'"
                    )
                p = simulate_fn(legs)
            else:
                raise ValueError("Ticket must include probability 'p'")
        odds = t["odds"]
        if not 0 < p < 1:
            raise ValueError("probability must be in (0,1)")
        if odds <= 1:
            raise ValueError("odds must be > 1")
        kelly_stake = _kelly_fraction(p, odds) * budget
        stake_input = t.get("stake", kelly_stake)
        stake = min(stake_input, kelly_stake * KELLY_CAP)

        ev = stake * (p * (odds - 1) - (1 - p))
        total_ev += ev
        total_stake += stake  

        if "legs" in t:
            has_combined = True
            combined_expected_payout += p * stake * odds

    roi_total = total_ev / total_stake if total_stake else 0.0
    ev_ratio = total_ev / budget if budget else 0.0

    reasons = []
    if ev_ratio < 0.40:
        reasons.append("EV ratio below 0.40")
    if roi_total < 0.20:
        reasons.append("ROI below 0.20")
    if has_combined and combined_expected_payout <= 10:
        reasons.append("expected payout for combined bets ≤ 10€")

    green_flag = not reasons

    result = {"ev": total_ev, "roi": roi_total, "ev_ratio": ev_ratio, "green": green_flag}
    if not green_flag:
        result["failure_reasons"] = reasons
    return result


__all__ = ["compute_ev_roi"]
