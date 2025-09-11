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

from scipy.optimize import minimize

# ``simulate_wrapper`` is an optional dependency kept for backward compatibility.
try:  # pragma: no cover - optional dependency
    from simulate_wrapper import simulate_wrapper  # type: ignore
except Exception:  # pragma: no cover - handled gracefully
    simulate_wrapper = None  # type: ignore


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
            

def optimize_stake_allocation(
    tickets: List[Dict[str, Any]],
    budget: float,
    kelly_cap: float,
) -> List[float]:
    """Optimise stakes to maximise the sum of expected log-returns.

    Each ticket's stake is bounded above by ``kelly_cap`` times its Kelly
    recommendation and the total stake cannot exceed the budget.  The objective
    maximises ``sum(p*log(1 + f*(odds-1)) + (1-p)*log(1-f))`` where ``f`` is the
    fraction of bankroll wagered on each ticket.

    Parameters
    ----------
    tickets:
        List of tickets containing ``p`` and ``odds``.
    budget:
        Total bankroll available.
    kelly_cap:
        Fraction of the Kelly stake allowed per ticket.

    Returns
    -------
    list of float
        Optimised stakes for each ticket.
    """

    p_odds: List[Tuple[float, float]] = []
    bounds: List[Tuple[float, float]] = []
    x0: List[float] = []
    for t in tickets:
        p = t["p"]
        odds = t["odds"]
        kelly_frac = _kelly_fraction(p, odds)
        cap_fraction = min(kelly_frac * kelly_cap, 1 - 1e-9)
        p_odds.append((p, odds))
        bounds.append((0.0, cap_fraction))
        x0.append(min(t.get("stake", 0.0) / budget, cap_fraction))

    def objective(fractions: Iterable[float]) -> float:
        total = 0.0
        for f, (p, odds) in zip(fractions, p_odds):
            total += p * math.log1p(f * (odds - 1)) + (1 - p) * math.log1p(-f)
        return -total

    constraints = {"type": "ineq", "fun": lambda x: 1.0 - sum(x)}
    res = minimize(objective, x0, bounds=bounds, constraints=[constraints], method="SLSQP")
    fractions = x0 if not res.success else res.x
    return [max(0.0, budget * f) for f in fractions]


def risk_of_ruin(total_ev: float, total_variance: float, bankroll: float) -> float:
    """Return the gambler's ruin approximation for a given EV and variance."""
 
    if bankroll <= 0:
        raise ValueError("bankroll must be > 0")
    if total_ev <= 0:
        return 1.0
    if total_variance <= 0:
        return 0.0
    return math.exp(-2 * total_ev * bankroll / total_variance)


def compute_ev_roi(
    tickets: List[Dict[str, Any]],
    budget: float,
    simulate_fn: Optional[Callable[[Iterable[Any]], float]] = None,
    *,
    cache_simulations: bool = True,
    ev_threshold: float = 0.40,
    roi_threshold: float = 0.20,
    kelly_cap: float = 0.60,
    round_to: float = 0.10,
    optimize: bool = False,
    variance_cap: Optional[float] = None,
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
        ``0.60``.
    round_to:
        Amount to which individual stakes are rounded.  ``0.10`` by default.
        Set to ``0`` to disable rounding.
    optimize:
        When ``True`` the stake allocation is optimised globally to maximise
        the sum of expected log-returns under the budget and Kelly cap
        constraints.  The result will also include ``ev_individual`` and
        ``roi_individual`` for the pre-optimisation allocation.

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
    if variance_cap is not None and variance_cap <= 0:
        raise ValueError("variance_cap must be > 0")
        
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
    ticket_metrics: List[Dict[str, float]] = []
 
    processed: List[Dict[str, Any]] = []
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
            clv = 0.0
            t["clv"] = clv
            
        kelly_stake = _kelly_fraction(p, odds) * budget
        max_stake = kelly_stake * kelly_cap
        stake_input = t.get("stake", kelly_stake)
        capped = stake_input > max_stake
        stake = min(stake_input, max_stake)
        if round_to > 0:
            stake = round(stake / round_to) * round_to

        processed.append(
            {
                "ticket": t,
                "p": p,
                "odds": odds,
                "stake": stake,
                "kelly_stake": kelly_stake,
                "max_stake": max_stake,
                "capped": capped,
                "clv": clv,
            }
        )
        if "legs" in t:
            has_combined = True

         total_stake = sum(d["stake"] for d in processed)
    if round_to > 0 and total_stake < budget:
        remaining = budget - total_stake
        non_capped = [d for d in processed if not d["capped"]]
        if non_capped and remaining >= round_to / 2:
            weight_sum = sum(d["kelly_stake"] for d in non_capped)
            for d in non_capped:
                max_extra = d["max_stake"] - d["stake"]
                if max_extra <= 0:
                    continue
                allocation = (
                    remaining * (d["kelly_stake"] / weight_sum) if weight_sum else 0.0
                )
                allocation = min(allocation, max_extra)
                allocation = math.floor((allocation + 1e-12) / round_to) * round_to
                d["stake"] += allocation
                remaining -= allocation
            if remaining >= round_to / 2:
                non_capped.sort(key=lambda x: x["kelly_stake"], reverse=True)
                for d in non_capped:
                    if remaining < round_to / 2:
                        break
                    max_extra = d["max_stake"] - d["stake"]
                    add_units = min(
                        int((max_extra + 1e-12) / round_to),
                        int((remaining + 1e-12) / round_to),
                    )
                    if add_units <= 0:
                        continue
                    add_amount = add_units * round_to
                    d["stake"] += add_amount
                    remaining -= add_amount
                    if remaining < round_to / 2:
                        break
            total_stake = budget - remaining

    for d in processed:
        t = d["ticket"]
        stake = d["stake"]
        p = d["p"]
        odds = d["odds"]

        ev = stake * (p * (odds - 1) - (1 - p))
        variance = p * (stake * (odds - 1)) ** 2 + (1 - p) * (-stake) ** 2 - ev ** 2
        roi = ev / stake if stake else 0.0
        metrics = {
            "kelly_stake": d["kelly_stake"],
            "stake": stake,
            "ev": ev,
            "roi": roi,
            "variance": variance,
            "clv": d["clv"],
        }
        t.update(metrics)
        ticket_metrics.append(metrics)
        total_ev += ev
        total_variance += variance
        if "legs" in t:
            combined_expected_payout += p * stake * odds

    total_stake_normalized = total_stake
    if total_stake > budget:
        scale = budget / total_stake
        for t, metrics in zip(tickets, ticket_metrics):
            t["stake"] *= scale
            t["ev"] *= scale
            t["variance"] *= scale ** 2
            metrics["stake"] *= scale
            metrics["ev"] *= scale
            metrics["variance"] *= scale ** 2
            t["roi"] = t["ev"] / t["stake"] if t["stake"] else 0.0
            metrics["roi"] = t["roi"]
        total_ev *= scale
        combined_expected_payout *= scale
        total_variance *= scale ** 2
        total_stake_normalized = budget

    variance_exceeded = False
    var_limit = variance_cap * budget ** 2 if variance_cap is not None else None
    if var_limit is not None and total_variance > var_limit:
        variance_exceeded = True
        scale = math.sqrt(var_limit / total_variance)
        for t, metrics in zip(tickets, ticket_metrics):
            t["stake"] *= scale
            t["ev"] *= scale
            t["variance"] *= scale ** 2
            metrics["stake"] *= scale
            metrics["ev"] *= scale
            metrics["variance"] *= scale ** 2
            t["roi"] = t["ev"] / t["stake"] if t["stake"] else 0.0
            metrics["roi"] = t["roi"]
        total_ev *= scale
        combined_expected_payout *= scale
        total_variance *= scale ** 2
        total_stake_normalized *= scale

    roi_total = total_ev / total_stake_normalized if total_stake_normalized else 0.0
    ev_ratio = total_ev / budget if budget else 0.0
    ruin_risk = risk_of_ruin(total_ev, total_variance, budget)
    std_dev = math.sqrt(total_variance)
    ev_over_std = total_ev / std_dev if std_dev else 0.0

    if optimize:
        baseline_metrics = ticket_metrics
        baseline_ev = total_ev
        baseline_roi = roi_total
        optimized_stakes = optimize_stake_allocation(tickets, budget, kelly_cap)

        opt_ev = 0.0
        opt_variance = 0.0
        opt_stake_sum = 0.0
        opt_combined_payout = 0.0
        optimized_metrics: List[Dict[str, float]] = []
        for t, stake_opt in zip(tickets, optimized_stakes):
            p = t["p"]
            odds = t["odds"]
            ev = stake_opt * (p * (odds - 1) - (1 - p))
            variance = (
                p * (stake_opt * (odds - 1)) ** 2
                + (1 - p) * (-stake_opt) ** 2
                - ev ** 2
            )
            roi = ev / stake_opt if stake_opt else 0.0
            metrics = {
                "kelly_stake": _kelly_fraction(p, odds) * budget,
                "stake": stake_opt,
                "ev": ev,
                "roi": roi,
                "variance": variance,
                "clv": t.get("clv", 0.0),
            }
            optimized_metrics.append(metrics)
            t["optimized_stake"] = stake_opt
            opt_ev += ev
            opt_variance += variance
            opt_stake_sum += stake_opt
            if "legs" in t:
                opt_combined_payout += p * stake_opt * odds

        variance_exceeded_opt = False
        if var_limit is not None and opt_variance > var_limit:
            variance_exceeded_opt = True
            scale = math.sqrt(var_limit / opt_variance)
            for t, metrics, stake_opt in zip(tickets, optimized_metrics, optimized_stakes):
                metrics["stake"] *= scale
                metrics["ev"] *= scale
                metrics["variance"] *= scale ** 2
                stake_scaled = stake_opt * scale
                t["optimized_stake"] = stake_scaled
            opt_ev *= scale
            opt_variance *= scale ** 2
            opt_stake_sum *= scale
            opt_combined_payout *= scale

        roi_opt = opt_ev / opt_stake_sum if opt_stake_sum else 0.0
        ev_ratio_opt = opt_ev / budget if budget else 0.0
        ruin_risk_opt = risk_of_ruin(opt_ev, opt_variance, budget)
        std_dev_opt = math.sqrt(opt_variance)
        ev_over_std_opt = opt_ev / std_dev_opt if std_dev_opt else 0.0

        reasons = []
        if ev_ratio_opt < ev_threshold:
            reasons.append(f"EV ratio below {ev_threshold:.2f}")
        if roi_opt < roi_threshold:
            reasons.append(f"ROI below {roi_threshold:.2f}")
        if has_combined and opt_combined_payout <= 10:
            reasons.append("expected payout for combined bets ≤ 10€")
        if variance_exceeded_opt:
            reasons.append(f"variance above {variance_cap:.2f} * bankroll^2")

        green_flag = not reasons
        result = {
            "ev": opt_ev,
            "roi": roi_opt,
            "ev_ratio": ev_ratio_opt,
            "green": green_flag,
            "total_stake_normalized": opt_stake_sum,
            "risk_of_ruin": ruin_risk_opt,
            "clv": (total_clv / clv_count) if clv_count else 0.0,
            "std_dev": std_dev_opt,
            "ev_over_std": ev_over_std_opt,
            "variance": opt_variance,
            "ticket_metrics": optimized_metrics,
            "ev_individual": baseline_ev,
            "roi_individual": baseline_roi,
            "ticket_metrics_individual": baseline_metrics,
            "optimized_stakes": optimized_stakes,
            "combined_expected_payout": opt_combined_payout,
        }
        if not green_flag:
            result["failure_reasons"] = reasons
        return result
        
    reasons = []
    if ev_ratio < ev_threshold:
        reasons.append(f"EV ratio below {ev_threshold:.2f}")
    if roi_total < roi_threshold:
        reasons.append(f"ROI below {roi_threshold:.2f}")
    if has_combined and combined_expected_payout <= 10:
        reasons.append("expected payout for combined bets ≤ 10€")
    if variance_exceeded:
        reasons.append(f"variance above {variance_cap:.2f} * bankroll^2")

    green_flag = not reasons

    result = {
        "ev": total_ev,
        "roi": roi_total,
        "ev_ratio": ev_ratio,
        "green": green_flag,
        "total_stake_normalized": total_stake_normalized,
        "risk_of_ruin": ruin_risk,
        "clv": (total_clv / clv_count) if clv_count else 0.0,
        "std_dev": std_dev,
        "ev_over_std": ev_over_std,
        "variance": total_variance,
        "ticket_metrics": ticket_metrics,
        "combined_expected_payout": combined_expected_payout,
    }
    if not green_flag:
        result["failure_reasons"] = reasons
    return result


__all__ = ["compute_ev_roi", "risk_of_ruin", "optimize_stake_allocation"]
