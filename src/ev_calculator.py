"""Utility for computing expected value (EV) and return on investment (ROI) for betting tickets.

This module exposes :func:`compute_ev_roi` which handles single bets,
SP dutching groups and combined bets via a caller-provided simulation function
(``simulate_fn``).  Stakes are capped to a fraction of the Kelly criterion
recommended stake (60% by default).
"""

from __future__ import annotations

import itertools
import logging
import math
import sys
from collections import defaultdict
from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from typing import Any

try:  # pragma: no cover - SciPy is optional
    from scipy.optimize import minimize
except ImportError:  # pragma: no cover - handled gracefully
    minimize = None  # type: ignore

from kelly import kelly_fraction

# ``simulate_wrapper`` is an optional dependency kept for backward compatibility.
try:  # pragma: no cover - optional dependency
    from simulate_wrapper import simulate_wrapper  # type: ignore
except Exception:  # pragma: no cover - handled gracefully
    simulate_wrapper = None  # type: ignore

_COPULA_MONTE_CARLO = None
if "simulate_wrapper" in sys.modules:  # pragma: no cover - optional dependency
    module = sys.modules.get("simulate_wrapper")
    _COPULA_MONTE_CARLO = getattr(module, "_monte_carlo_joint_probability", None)

_LOGGER = logging.getLogger(__name__)


def _make_hashable(value: Any) -> Any:
    """Return a hashable representation of ``value`` for caching purposes."""

    if isinstance(value, Hashable):
        return value
    if isinstance(value, Mapping):
        return tuple(sorted((k, _make_hashable(v)) for k, v in value.items()))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(_make_hashable(v) for v in value)
    return repr(value)


def _kelly_fraction(p: float, odds: float) -> float:
    """Return the pure Kelly fraction for given probability and odds."""

    if not 0 < p < 1:
        raise ValueError("probability must be in (0,1)")
    if odds <= 1:
        raise ValueError("odds must be > 1")

    return kelly_fraction(p, odds, lam=1.0, cap=1.0)


def _apply_dutching(tickets: Iterable[dict[str, Any]]) -> None:
    """Normalise stakes inside each dutching group so that profit is identical.

    Tickets that share the same ``dutching`` key are adjusted so that each
    ticket's potential profit ``stake * (odds - 1)`` is constant while keeping
    the total stake of the group unchanged.
    """
    groups: dict[Any, list[dict[str, Any]]] = defaultdict(list)
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
        for t, w in zip(valid_tickets, weights, strict=False):
            t["stake"] = total * w / weight_sum

def _ticket_label(ticket: Mapping[str, Any], index: int) -> str:
    """Return a readable identifier for ``ticket`` when logging covariance."""

    for key in ("id", "name", "label", "selection", "runner"):
        value = ticket.get(key)
        if value not in (None, ""):
            return str(value)
    return f"ticket_{index + 1}"


def _clone_leg(leg: Any) -> Any:
    if isinstance(leg, Mapping):
        return {k: v for k, v in leg.items()}
    if isinstance(leg, Sequence) and not isinstance(leg, (str, bytes)):
        return [_clone_leg(item) for item in leg]
    return leg


def _prepare_legs_for_covariance(
    ticket: Mapping[str, Any],
    legs_for_probability: Iterable[Any] | None,
) -> tuple[Any, ...]:
    """Return legs usable for covariance estimation for ``ticket``."""

    legs_iterable: Iterable[Any] | None = None
    if legs_for_probability:
        legs_iterable = legs_for_probability
    else:
        payload = ticket.get("legs_details") or ticket.get("legs")
        if isinstance(payload, Iterable) and not isinstance(payload, (str, bytes)):
            legs_iterable = payload

    legs: list[Any] = []
    if legs_iterable is not None:
        for leg in legs_iterable:
            legs.append(_clone_leg(leg))
    else:
        for key in ("id", "selection_id", "runner_id", "horse_id"):
            value = ticket.get(key)
            if value not in (None, ""):
                legs.append({"id": value})
                break
    return tuple(legs)


def _ticket_dependency_keys(
    ticket: Mapping[str, Any], legs: Sequence[Any]
) -> frozenset[str]:
    """Return dependency identifiers extracted from ``ticket`` and ``legs``."""

    exposures: set[str] = set()
    for key in ("id", "selection_id", "runner_id", "horse_id"):
        value = ticket.get(key)
        if value not in (None, ""):
            exposures.add(f"id:{value}")

    for leg in legs:
        identifier: str | None = None
        if isinstance(leg, Mapping):
            for leg_key in ("id", "runner", "participant", "num", "name", "code"):
                data = leg.get(leg_key) if isinstance(leg, Mapping) else None
                if data not in (None, ""):
                    identifier = str(data)
                    break
        else:
            identifier = str(leg)
        if identifier:
            exposures.add(f"leg:{identifier}")
    return frozenset(exposures)


def _prepare_ticket_dependencies(
    ticket: Mapping[str, Any], legs_for_probability: Iterable[Any] | None
) -> dict[str, Any]:
    legs = _prepare_legs_for_covariance(ticket, legs_for_probability)
    exposures = _ticket_dependency_keys(ticket, legs)
    return {"legs": legs, "exposures": exposures}


def _rho_for_shared_exposures(shared: frozenset[str]) -> float:
    if not shared:
        return 0.0
    if any(key.startswith("id:") for key in shared):
        return 0.85
    if any(key.startswith("leg:") for key in shared):
        return 0.60
    return 0.40


def _approx_joint_probability(p_i: float, p_j: float, rho: float) -> float:
    rho = max(min(rho, 0.99), -0.99)
    independence = p_i * p_j
    if rho == 0.0:
        return independence
    term = rho * math.sqrt(max(p_i * (1 - p_i), 0.0) * max(p_j * (1 - p_j), 0.0))
    lower = max(0.0, p_i + p_j - 1.0)
    upper = min(p_i, p_j)
    estimate = independence + term
    estimate = max(lower, min(upper, estimate))
    return max(independence, estimate)


def _merge_legs(a: Sequence[Any], b: Sequence[Any]) -> list[Any]:
    merged: list[Any] = []
    seen: set[Any] = set()
    for source in (a, b):
        for leg in source:
            key = _make_hashable(leg)
            if key in seen:
                continue
            seen.add(key)
            merged.append(_clone_leg(leg))
    return merged


def _simulate_joint_probability(
    legs: Sequence[Any],
    simulate_fn: Callable[[Iterable[Any]], float] | None,
    cache: dict[tuple[Any, ...], float] | None,
) -> float | None:
    if not simulate_fn or not legs:
        return None

    key = tuple(_make_hashable(leg) for leg in legs)
    if cache is not None and key in cache:
        return cache[key]

    try:
        value = float(simulate_fn(legs))
    except Exception:  # pragma: no cover - defensive
        return None

    if cache is not None:
        cache[key] = value
    return value


def _estimate_joint_probability(
    info_i: dict[str, Any],
    info_j: dict[str, Any],
    simulate_fn: Callable[[Iterable[Any]], float] | None,
    cache: dict[tuple[Any, ...], float] | None,
) -> float:
    shared: frozenset[str] = info_i["exposures"] & info_j["exposures"]
    rho = _rho_for_shared_exposures(shared)
    joint: float | None = None

    legs_i: Sequence[Any] = info_i.get("legs_for_sim", ())
    legs_j: Sequence[Any] = info_j.get("legs_for_sim", ())
    merged = _merge_legs(legs_i, legs_j)
    joint = _simulate_joint_probability(merged, simulate_fn, cache)

    if joint is None and callable(_COPULA_MONTE_CARLO):  # pragma: no cover - optional
        try:
            mc = _COPULA_MONTE_CARLO([info_i["p"], info_j["p"]], rho)
        except Exception:  # pragma: no cover - defensive
            mc = None
        if mc is not None:
            joint = float(mc)

    if joint is None:
        joint = _approx_joint_probability(info_i["p"], info_j["p"], rho)

    lower = max(0.0, info_i["p"] + info_j["p"] - 1.0)
    upper = min(info_i["p"], info_j["p"])
    independence = info_i["p"] * info_j["p"]
    joint = max(lower, min(upper, float(joint)))
    return max(independence, joint)


def _covariance_from_joint(
    info_i: dict[str, Any], info_j: dict[str, Any], joint: float
) -> float:
    win_i = info_i["win_value"]
    loss_i = info_i["loss_value"]
    win_j = info_j["win_value"]
    loss_j = info_j["loss_value"]

    p_i = info_i["p"]
    p_j = info_j["p"]
    joint = max(0.0, min(joint, p_i, p_j))

    p_i_only = max(0.0, p_i - joint)
    p_j_only = max(0.0, p_j - joint)
    p_none = max(0.0, 1.0 - p_i - p_j + joint)

    total = joint + p_i_only + p_j_only + p_none
    if total <= 0:
        return 0.0

    joint /= total
    p_i_only /= total
    p_j_only /= total
    p_none /= total

    expected_product = (
        joint * win_i * win_j
        + p_i_only * win_i * loss_j
        + p_j_only * loss_i * win_j
        + p_none * loss_i * loss_j
    )
    return expected_product - info_i["ev"] * info_j["ev"]


def compute_joint_moments(
    ticket_infos: Sequence[dict[str, Any]],
    *,
    simulate_fn: Callable[[Iterable[Any]], float] | None = None,
    cache: dict[tuple[Any, ...], float] | None = None,
) -> tuple[float, list[dict[str, Any]]]:
    """Return covariance adjustment and detailed pairs for correlated tickets."""

    if len(ticket_infos) < 2:
        return 0.0, []

    exposure_map: dict[str, list[int]] = defaultdict(list)
    for idx, info in enumerate(ticket_infos):
        for key in info.get("exposures", frozenset()):
            exposure_map[key].append(idx)

    candidate_pairs: set[tuple[int, int]] = set()
    for indices in exposure_map.values():
        if len(indices) < 2:
            continue
        for i, j in itertools.combinations(sorted(set(indices)), 2):
            candidate_pairs.add((i, j))

    if not candidate_pairs:
        return 0.0, []

    adjustment = 0.0
    details: list[dict[str, Any]] = []
    for i, j in sorted(candidate_pairs):
        info_i = ticket_infos[i]
        info_j = ticket_infos[j]
        shared = info_i["exposures"] & info_j["exposures"]
        if not shared:
            continue
        joint = _estimate_joint_probability(info_i, info_j, simulate_fn, cache)
        covariance = _covariance_from_joint(info_i, info_j, joint)
        if abs(covariance) < 1e-12:
            continue
        adjustment += 2.0 * covariance
        details.append(
            {
                "tickets": (info_i.get("label"), info_j.get("label")),
                "shared": sorted(shared),
                "joint_probability": joint,
                "covariance": covariance,
            }
        )

    return adjustment, details


def optimize_stake_allocation(
    tickets: list[dict[str, Any]],
    budget: float,
    kelly_cap: float,
) -> list[float]:
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

    p_odds: list[tuple[float, float]] = []
    bounds: list[tuple[float, float]] = []
    x0: list[float] = []
    for t in tickets:
        p = t["p"]
        odds = t["odds"]
        cap_fraction = kelly_fraction(p, odds, lam=kelly_cap, cap=1.0)
        cap_fraction = min(cap_fraction, 1 - 1e-9)
        p_odds.append((p, odds))
        bounds.append((0.0, cap_fraction))
        x0.append(min(t.get("stake", 0.0) / budget, cap_fraction))

    def objective(fractions: Iterable[float]) -> float:
        total = 0.0
        for f, (p, odds) in zip(fractions, p_odds, strict=False):
            total += p * math.log1p(f * (odds - 1)) + (1 - p) * math.log1p(-f)
        return -total

    constraints = {"type": "ineq", "fun": lambda x: 1.0 - sum(x)}
    if minimize is not None:
        res = minimize(
            objective, x0, bounds=bounds, constraints=[constraints], method="SLSQP"
        )
        fractions = x0 if not res.success else res.x
    else:
        # Fallback: naive grid search with 5 % granularity
        step = 0.05
        best_val = float("inf")
        best_fracs = x0[:]

        def search(i: int, remaining: float, current: list[float]) -> None:
            nonlocal best_val, best_fracs
            if i == len(p_odds):
                if remaining < -1e-9:
                    return
                val = objective(current)
                if val < best_val:
                    best_val = val
                    best_fracs = current[:]
                return

            max_f = min(bounds[i][1], remaining)
            f = 0.0
            while f <= max_f + 1e-9:
                current.append(f)
                search(i + 1, remaining - f, current)
                current.pop()
                f += step

        search(0, 1.0, [])
        fractions = best_fracs
    return [max(0.0, budget * f) for f in fractions]


def risk_of_ruin(
    total_ev: float,
    total_variance: float,
    bankroll: float,
    *,
    baseline_variance: float | None = None,
) -> float:
    """Return the gambler's ruin approximation for a given EV and variance."""

    if bankroll <= 0:
        raise ValueError("bankroll must be > 0")
    if total_ev <= 0:
        return 1.0
    if total_variance <= 0:
        return 0.0

    effective_variance = total_variance
    if baseline_variance is not None and baseline_variance > total_variance:
        effective_variance = baseline_variance

    return math.exp(-2 * total_ev * bankroll / effective_variance)


def compute_ev_roi(
    tickets: list[dict[str, Any]],
    budget: float,
    simulate_fn: Callable[[Iterable[Any]], float] | None = None,
    *,
    cache_simulations: bool = True,
    ev_threshold: float = 0.35,
    roi_threshold: float = 0.25,
    ror_threshold: float | None = None,
    kelly_cap: float = 0.60,
    round_to: float = 0.10,
    optimize: bool = False,
    variance_cap: float | None = None,
) -> dict[str, Any]:
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

    cache: dict[tuple[Any, ...], float] = {}
    total_ev = 0.0
    total_variance = 0.0
    total_stake = 0.0
    combined_expected_payout = 0.0
    total_expected_payout = 0.0
    has_combined = False
    total_clv = 0.0
    clv_count = 0
    ticket_metrics: list[dict[str, float]] = []

    processed: list[dict[str, Any]] = []
    for t in tickets:
        p = t.get("p")
        legs_for_probability = t.get("legs_details") or t.get("legs")
        if p is None:
            legs_for_sim = legs_for_probability
            if legs_for_sim is not None:
                if simulate_fn is None:
                    raise ValueError(
                        "simulate_fn must be provided when tickets include 'legs'"
                    )
                if cache_simulations:
                    key: tuple[Any, ...] = tuple(
                        _make_hashable(leg) for leg in legs_for_sim
                    )
                    p = cache.get(key)
                    if p is None:
                        p = simulate_fn(legs_for_sim)
                        cache[key] = p
                else:
                    p = simulate_fn(legs_for_sim)
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
        max_stake = kelly_fraction(p, odds, lam=kelly_cap, cap=1.0) * budget
        stake_input = t.get("stake", kelly_stake)
        capped = stake_input > max_stake
        stake = min(stake_input, max_stake)
        if round_to > 0:
            stake = round(stake / round_to) * round_to

        dependencies = _prepare_ticket_dependencies(t, legs_for_probability)

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
                "dependencies": dependencies,
            }
        )
        if "legs" in t or "legs_details" in t:
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

    covariance_inputs: list[dict[str, Any]] = []

    for d in processed:
        t = d["ticket"]
        stake = d["stake"]
        p = d["p"]
        odds = d["odds"]

        ev = stake * (p * (odds - 1) - (1 - p))
        variance = p * (stake * (odds - 1)) ** 2 + (1 - p) * (-stake) ** 2 - ev**2
        roi = ev / stake if stake else 0.0
        expected_payout = p * stake * odds
        ticket_variance = max(variance, 0.0)
        ticket_std = math.sqrt(ticket_variance)
        sharpe_ticket = ev / ticket_std if ticket_std else 0.0
        metrics = {
            "kelly_stake": d["kelly_stake"],
            "stake": stake,
            "ev": ev,
            "roi": roi,
            "variance": ticket_variance,
            "clv": d["clv"],
            "expected_payout": expected_payout,
            "sharpe": sharpe_ticket,
        }
        t.update(metrics)
        ticket_metrics.append(metrics)
        total_ev += ev
        total_variance += ticket_variance
        total_expected_payout += expected_payout
        if "legs" in t:
            combined_expected_payout += p * stake * odds

        dependencies = d.get("dependencies", {})
        covariance_inputs.append(
            {
                "p": p,
                "ev": ev,
                "win_value": stake * (odds - 1),
                "loss_value": -stake,
                "exposures": dependencies.get("exposures", frozenset()),
                "legs_for_sim": dependencies.get("legs", ()),
                "label": _ticket_label(t, len(covariance_inputs)),
            }
        )

    total_variance_naive = total_variance
    covariance_adjustment = 0.0
    covariance_details: list[dict[str, Any]] = []
    joint_cache = cache if cache_simulations else None
    if covariance_inputs:
        covariance_adjustment, covariance_details = compute_joint_moments(
            covariance_inputs,
            simulate_fn=simulate_fn,
            cache=joint_cache,
        )
        total_variance = max(0.0, total_variance_naive + covariance_adjustment)

    total_stake_normalized = total_stake
    if total_stake > budget:
        scale = budget / total_stake
        for t, metrics in zip(tickets, ticket_metrics, strict=False):
            t["stake"] *= scale
            t["ev"] *= scale
            t["variance"] *= scale**2
            metrics["stake"] *= scale
            metrics["ev"] *= scale
            metrics["variance"] *= scale**2
            t["expected_payout"] *= scale
            metrics["expected_payout"] *= scale
            t["roi"] = t["ev"] / t["stake"] if t["stake"] else 0.0
            metrics["roi"] = t["roi"]
        total_ev *= scale
        combined_expected_payout *= scale
        total_variance *= scale**2
        total_variance_naive *= scale**2
        covariance_adjustment *= scale**2
        for detail in covariance_details:
            detail["covariance"] *= scale**2
        total_stake_normalized = budget
        total_expected_payout *= scale

    variance_exceeded = False
    var_limit = variance_cap * budget**2 if variance_cap is not None else None
    if var_limit is not None and total_variance > var_limit:
        variance_exceeded = True
        scale = math.sqrt(var_limit / total_variance)
        for t, metrics in zip(tickets, ticket_metrics, strict=False):
            t["stake"] *= scale
            t["ev"] *= scale
            t["variance"] *= scale**2
            metrics["stake"] *= scale
            metrics["ev"] *= scale
            metrics["variance"] *= scale**2
            t["expected_payout"] *= scale
            metrics["expected_payout"] *= scale
            t["roi"] = t["ev"] / t["stake"] if t["stake"] else 0.0
            metrics["roi"] = t["roi"]
        total_ev *= scale
        combined_expected_payout *= scale
        total_variance *= scale**2
        total_variance_naive *= scale**2
        covariance_adjustment *= scale**2
        for detail in covariance_details:
            detail["covariance"] *= scale**2
        total_stake_normalized *= scale
        total_expected_payout *= scale

    final_variance_naive = total_variance_naive
    final_covariance_adjustment = covariance_adjustment
    final_covariance_details = covariance_details

    roi_total = total_ev / total_stake_normalized if total_stake_normalized else 0.0
    ev_ratio = total_ev / budget if budget else 0.0
    ruin_risk = risk_of_ruin(
        total_ev,
        total_variance,
        budget,
        baseline_variance=total_variance_naive,
    )
    std_dev = math.sqrt(total_variance)
    ev_over_std = total_ev / std_dev if std_dev else 0.0

    if optimize:
        baseline_metrics = ticket_metrics
        baseline_ev = total_ev
        baseline_roi = roi_total
        baseline_variance_naive = total_variance_naive
        baseline_covariance_adjustment = covariance_adjustment
        baseline_covariance_details = [dict(detail) for detail in covariance_details]
        optimized_stakes = optimize_stake_allocation(tickets, budget, kelly_cap)

        opt_ev = 0.0
        opt_variance = 0.0
        opt_stake_sum = 0.0
        opt_combined_payout = 0.0
        optimized_metrics: list[dict[str, float]] = []
        opt_expected_payout = 0.0
        opt_covariance_inputs: list[dict[str, Any]] = []
        for idx, (t, stake_opt) in enumerate(zip(tickets, optimized_stakes, strict=False)):
            p = t["p"]
            odds = t["odds"]
            ev = stake_opt * (p * (odds - 1) - (1 - p))
            variance = (
                p * (stake_opt * (odds - 1)) ** 2 + (1 - p) * (-stake_opt) ** 2 - ev**2
            )
            roi = ev / stake_opt if stake_opt else 0.0
            expected_payout = p * stake_opt * odds
            ticket_variance = max(variance, 0.0)
            ticket_std = math.sqrt(ticket_variance)
            sharpe_ticket = ev / ticket_std if ticket_std else 0.0
            metrics = {
                "kelly_stake": _kelly_fraction(p, odds) * budget,
                "stake": stake_opt,
                "ev": ev,
                "roi": roi,
                "variance": ticket_variance,
                "clv": t.get("clv", 0.0),
                "expected_payout": expected_payout,
                "sharpe": sharpe_ticket,
            }
            optimized_metrics.append(metrics)
            t["optimized_stake"] = stake_opt
            t["optimized_expected_payout"] = expected_payout
            t["optimized_sharpe"] = sharpe_ticket
            opt_ev += ev
            opt_variance += ticket_variance
            opt_stake_sum += stake_opt
            opt_expected_payout += expected_payout
            if "legs" in t:
                opt_combined_payout += p * stake_opt * odds

            dependencies_opt = processed[idx].get("dependencies", {})
            opt_covariance_inputs.append(
                {
                    "p": p,
                    "ev": ev,
                    "win_value": stake_opt * (odds - 1),
                    "loss_value": -stake_opt,
                    "exposures": dependencies_opt.get("exposures", frozenset()),
                    "legs_for_sim": dependencies_opt.get("legs", ()),
                    "label": _ticket_label(t, len(opt_covariance_inputs)),
                }
            )

        opt_variance_naive = opt_variance
        opt_covariance_adjustment = 0.0
        opt_covariance_details: list[dict[str, Any]] = []
        if opt_covariance_inputs:
            opt_covariance_adjustment, opt_covariance_details = compute_joint_moments(
                opt_covariance_inputs,
                simulate_fn=simulate_fn,
                cache=joint_cache,
            )
            opt_variance = max(0.0, opt_variance_naive + opt_covariance_adjustment)

        variance_exceeded_opt = False
        if var_limit is not None and opt_variance > var_limit:
            variance_exceeded_opt = True
            scale = math.sqrt(var_limit / opt_variance)
            for t, metrics, stake_opt in zip(
                tickets, optimized_metrics, optimized_stakes, strict=False
            ):
                metrics["stake"] *= scale
                metrics["ev"] *= scale
                metrics["variance"] *= scale**2
                stake_scaled = stake_opt * scale
                t["optimized_stake"] = stake_scaled
                metrics["expected_payout"] *= scale
                t["optimized_expected_payout"] *= scale
            opt_ev *= scale
            opt_variance *= scale**2
            opt_variance_naive *= scale**2
            opt_covariance_adjustment *= scale**2
            for detail in opt_covariance_details:
                detail["covariance"] *= scale**2
            opt_stake_sum *= scale
            opt_combined_payout *= scale
            opt_expected_payout *= scale

        roi_opt = opt_ev / opt_stake_sum if opt_stake_sum else 0.0
        ev_ratio_opt = opt_ev / budget if budget else 0.0
        ruin_risk_opt = risk_of_ruin(
            opt_ev,
            opt_variance,
            budget,
            baseline_variance=opt_variance_naive,
        )
        std_dev_opt = math.sqrt(opt_variance)
        ev_over_std_opt = opt_ev / std_dev_opt if std_dev_opt else 0.0

        if opt_ev + 1e-9 < baseline_ev:
            # Optimisation should never deteriorate the EV – fall back to the
            # baseline allocation when the optimiser converges to a worse
            # configuration (may happen when the budget is already close to the
            # Kelly cap or when rounding effects dominate).
            opt_ev = baseline_ev
            roi_opt = baseline_roi
            ev_ratio_opt = baseline_ev / budget if budget else 0.0
            ruin_risk_opt = ruin_risk
            std_dev_opt = math.sqrt(total_variance)
            ev_over_std_opt = ev_over_std
            opt_variance = total_variance
            opt_variance_naive = baseline_variance_naive
            opt_covariance_adjustment = baseline_covariance_adjustment
            opt_covariance_details = [
                dict(detail) for detail in baseline_covariance_details
            ]
            opt_stake_sum = total_stake_normalized
            opt_combined_payout = combined_expected_payout
            opt_expected_payout = total_expected_payout
            optimized_metrics = baseline_metrics
            optimized_stakes = [
                metrics.get("stake", 0.0) for metrics in baseline_metrics
            ]
            for ticket, metrics in zip(tickets, baseline_metrics, strict=False):
                ticket["optimized_stake"] = metrics.get("stake")
                ticket["optimized_expected_payout"] = metrics.get("expected_payout")
                ticket["optimized_sharpe"] = metrics.get("sharpe")

        final_variance_naive = opt_variance_naive
        final_covariance_adjustment = opt_covariance_adjustment
        final_covariance_details = opt_covariance_details

        reasons = []
        if ev_ratio_opt < ev_threshold:
            reasons.append(f"EV ratio below {ev_threshold:.2f}")
        if roi_opt < roi_threshold:
            reasons.append(f"ROI below {roi_threshold:.2f}")
        if has_combined and opt_combined_payout <= 12:
            reasons.append("expected payout for combined bets ≤ 12€")
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
            "variance_naive": opt_variance_naive,
            "covariance_adjustment": opt_covariance_adjustment,
            "covariance_pairs": opt_covariance_details,
            "ticket_metrics": optimized_metrics,
            "ev_individual": baseline_ev,
            "roi_individual": baseline_roi,
            "ticket_metrics_individual": baseline_metrics,
            "variance_naive_individual": baseline_variance_naive,
            "covariance_adjustment_individual": baseline_covariance_adjustment,
            "covariance_pairs_individual": baseline_covariance_details,
            "optimized_stakes": optimized_stakes,
            "combined_expected_payout": opt_combined_payout,
            "calibrated_expected_payout": opt_expected_payout,
            "calibrated_expected_payout_individual": total_expected_payout,
            "sharpe": ev_over_std_opt,
            "sharpe_individual": ev_over_std,
        }
        if not green_flag:
            result["failure_reasons"] = reasons
        return result

    reasons = []
    if variance_exceeded:
        reasons.append(f"variance above {variance_cap:.2f} * bankroll^2")
    if ev_ratio < ev_threshold:
        reasons.append(f"EV ratio below {ev_threshold:.2f}")
    if roi_total < roi_threshold:
        reasons.append(f"ROI below {roi_threshold:.2f}")
    if has_combined and combined_expected_payout <= 12:
        reasons.append("expected payout for combined bets ≤ 12€")
    if ror_threshold is not None and ruin_risk > ror_threshold:
        reasons.append(f"risk of ruin above {ror_threshold:.2%}")

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
        "variance_naive": final_variance_naive,
        "covariance_adjustment": final_covariance_adjustment,
        "covariance_pairs": final_covariance_details,
        "ticket_metrics": ticket_metrics,
        "combined_expected_payout": combined_expected_payout,
        "calibrated_expected_payout": total_expected_payout,
        "sharpe": ev_over_std,
    }
    if not green_flag:
        result["failure_reasons"] = reasons
    return result


__all__ = ["compute_ev_roi", "risk_of_ruin", "optimize_stake_allocation"]
