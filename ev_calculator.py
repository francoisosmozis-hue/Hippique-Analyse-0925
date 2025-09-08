"""Utility for computing expected value (EV) and return on investment (ROI) for betting tickets.

This module exposes :func:`compute_ev_roi` which handles single bets,
SP dutching groups and combined bets via a caller-provided simulation function
(``simulate_fn``).  Stakes are capped to a fraction of the Kelly criterion
recommended stake (60% by default).
"""
from __future__ import annotations

from collections import defaultdict
import math
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

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
            

def risk_of_ruin(total_ev: float, total_variance: float, bankroll: float) -> float:
    """Approximate the probability of losing the entire bankroll.

    The approximation is based on the gambler's ruin model for a process with
    drift ``total_ev`` and variance ``total_variance`` over one period:
    ``exp(-2 * total_ev * bankroll / total_variance)``.  When the expected
    value is non-positive the risk is ``1`` as ruin is inevitable.

    Parameters
    ----------
    total_ev:
        Expected profit of the set of bets.
    total_variance:
        Variance of the profit distribution.
    bankroll:
        Current bankroll to protect.

    Returns
    -------
    float
        Approximate risk of ruin, between ``0`` (no risk) and ``1`` (certainty
        of ruin).
    """

    if bankroll <= 0:
        raise ValueError("bankroll must be > 0")
    if total_ev <= 0:
        return 1.0
    if total_variance <= 0:
        return 0.0
    exponent = -2 * total_ev * bankroll / total_variance
    return min(1.0, math.exp(exponent))


def compute_ev_roi(
    tickets: List[Dict[str, Any]],
    budget: float,
    simulate_fn: Optional[Callable[[Iterable[Any]], float]] = None,
    *,
    cache_simulations: bool = True,
    ev_threshold: float = 0.40,
    roi_threshold: float = 0.20,
    kelly_cap: float = KELLY_CAP,
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
        Bankroll used for Kelly criterion computations. Must be greater than ``0``.
    simulate_fn:
        Callable used to estimate the probability of combined bets from their
        ``legs``.  Its signature must be ``legs -> probability``.  Required when
        tickets contain ``legs`` without providing ``p``.
    cache_simulations:
        When ``True`` (default), results of ``simulate_fn`` are cached so that
        repeated combined bets with identical ``legs`` reuse the previously
        computed probability.  Set to ``False`` to disable this behaviour.
    ev_threshold:
        Minimum EV ratio (``ev / budget``) required for the ticket set to be
        considered "green".
    roi_threshold:
        Minimum ROI required for the ticket set to be considered "green".
    kelly_cap:
        Maximum fraction of the Kelly stake to actually wager.  Defaults to
        :data:`KELLY_CAP`.

    Returns
    -------
    dict
        A dictionary with keys ``ev`` (global expected value), ``roi`` (overall
        ROI), ``ev_ratio`` (EV relative to the budget), ``green`` (boolean flag)
        and ``total_stake_normalized`` (total stake after potential
        normalisation).  When ``green`` is ``False`` an additional
        ``failure_reasons`` list explains which criteria were not met
    Raises
    ------
    ValueError
        If ``budget`` is not greater than ``0``.
    """
    if budget <= 0:
        raise ValueError("budget must be > 0")
        
    # First adjust stakes for dutching groups
    _apply_dutching(tickets)

    if simulate_fn is None:
        simulate_fn = simulate_wrapper

    cache: Dict[Tuple[Any, ...], float] = {}
    total_ev = 0.0
    total_variance = 0.0
    total_stake = 0.0
    combined_expected_payout = 0.0
    has_combined = False
    total_clv = 0.0
    clv_count = 0
 
    for t in tickets:
        p = t.get("p")
        if p is None:
            legs = t.get("legs")
            if legs is not None:
                if simulate_fn is None:
                    raise ValueError(
                        "simulate_fn must be provided when tickets include 'legs'"
                    )
                if cache_simulations:
                    key: Tuple[Any, ...] = tuple(legs)
                    p = cache.get(key)
                    if p is None:
                        p = simulate_fn(legs)
                        cache[key] = p
                else:
                    p = simulate_fn(legs)
                t["p"] = p
            else:
                raise ValueError("Ticket must include probability 'p'")
        odds = t["odds"]
        closing_odds = t.get("closing_odds")
        if not 0 < p < 1:
            raise ValueError("probability must be in (0,1)")
        if odds <= 1:
            raise ValueError("odds must be > 1")
        if closing_odds is not None and odds > 0:
            clv = (closing_odds - odds) / odds
            t["clv"] = clv
            total_clv += clv
            clv_count += 1
        else:
            t["clv"] = 0.0
        kelly_stake = _kelly_fraction(p, odds) * budget
        stake_input = t.get("stake", kelly_stake)
        stake = min(stake_input, kelly_stake * kelly_cap)
        t["stake"] = stake

        ev = stake * (p * (odds - 1) - (1 - p))
        total_ev += ev
        total_stake += stake
        total_variance += p * (1 - p) * (stake * odds) ** 2
        
        if "legs" in t:
            has_combined = True
            combined_expected_payout += p * stake * odds

    total_stake_normalized = total_stake
    if total_stake > budget:
        scale = budget / total_stake
        for t in tickets:
            t["stake"] *= scale
        total_ev *= scale
        combined_expected_payout *= scale
        total_variance *= scale ** 2
        total_stake_normalized = budget

    roi_total = total_ev / total_stake_normalized if total_stake_normalized else 0.0
    ev_ratio = total_ev / budget if budget else 0.0
    ruin_risk = risk_of_ruin(total_ev, total_variance, budget)

    reasons = []
    if ev_ratio < ev_threshold:
        reasons.append(f"EV ratio below {ev_threshold:.2f}")
    if roi_total < roi_threshold:
        reasons.append(f"ROI below {roi_threshold:.2f}")
    if has_combined and combined_expected_payout <= 10:
        reasons.append("expected payout for combined bets ≤ 10€")

    green_flag = not reasons

    result = {
        "ev": total_ev,
        "roi": roi_total,
        "ev_ratio": ev_ratio,
        "green": green_flag,
        "total_stake_normalized": total_stake_normalized,
        "risk_of_ruin": ruin_risk,
        "clv": (total_clv / clv_count) if clv_count else 0.0,
    }
    if not green_flag:
        result["failure_reasons"] = reasons
    return result


__all__ = ["compute_ev_roi", "risk_of_ruin"]
