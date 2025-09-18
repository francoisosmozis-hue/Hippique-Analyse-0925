"""Simple simulation wrapper applying calibrated probabilities.

The module reads calibration data produced by ``calibration/calibrate_simulator.py``
from ``calibration/probabilities.yaml``.  For each call, the calibration file
is reloaded if modified so that simulations use the latest probabilities.

If a combination of legs is not present in the calibration data, an estimate is
derived using a simple Beta-Binomial model with a uniform prior
(:math:`\alpha = \beta = 1`).  Each leg is treated as an independent
Bernoulli event and the posterior means are multiplied to obtain the final
probability.  Results are cached in a least-recently-used queue capped at
``MAX_CACHE_SIZE`` entries to avoid unbounded growth.
"""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import os
import yaml

CALIBRATION_PATH = Path("calibration/probabilities.yaml")

# Maximum number of entries to keep in the calibration cache.  When the limit
# is exceeded, least recently used keys are discarded.  This prevents
# unbounded growth when many unique combinations are requested.
MAX_CACHE_SIZE = 500

_calibration_cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
_calibration_mtime: float = 0.0

_EPSILON = 1e-6

_RELIABLE_SOURCES = {
    "calibration",
    "calibration_combo",
    "calibration_leg",
    "leg_calibration",
    "leg_p",
    "leg_p_true",
}


def _coerce_probability(value: Any) -> float | None:
    """Return ``value`` as probability in ``(0, 1)`` when possible."""

    try:
        prob = float(value)
    except (TypeError, ValueError):
        return None
    if not 0.0 < prob < 1.0:
        return None
    return prob


def _coerce_odds(value: Any) -> float | None:
    """Return ``value`` as valid decimal odds (> 1) when possible."""

    try:
        odds = float(value)
    except (TypeError, ValueError):
        return None
    if odds <= 1.0:
        return None
    return odds


def _leg_identifier(leg: Any) -> str:
    """Return a stable identifier for ``leg`` to use as cache key."""

    if isinstance(leg, Mapping):
        for key in ("id", "runner", "participant", "num", "name", "code"):
            if key in leg and leg[key] not in (None, ""):
                return str(leg[key])
    return str(leg)


def _combo_key(legs: Sequence[Any]) -> str:
    """Return canonical cache key for a combination of ``legs``."""

    identifiers = sorted(_leg_identifier(leg) for leg in legs)
    return "|".join(identifiers)


def _extract_leg_probability(leg: Any) -> Tuple[float, str, str]:
    """Return ``(probability, source, identifier)`` for ``leg``."""

    identifier = _leg_identifier(leg)

    if isinstance(leg, Mapping):
        for field in ("p", "probability"):
            prob = _coerce_probability(leg.get(field))
            if prob is not None:
                return prob, "leg_p", identifier
        prob = _coerce_probability(leg.get("p_true"))
        if prob is not None:
            return prob, "leg_p_true", identifier

    entry = _calibration_cache.get(identifier)
    if entry:
        prob = _coerce_probability(entry.get("p"))
        if prob is None:
            alpha = float(entry.get("alpha", 0.0))
            beta = float(entry.get("beta", 0.0))
            if alpha > 0 and beta > 0:
                prob = alpha / (alpha + beta)
        if prob is not None:
            sources = entry.get("sources")
            if isinstance(sources, str):
                source = sources
            elif isinstance(sources, Sequence) and not isinstance(sources, (str, bytes)):
                source = str(next(iter(sources), "calibration"))
            else:
                source = "calibration"
            return prob, source, identifier

    odds_value = None
    if isinstance(leg, Mapping):
        for key in ("odds", "cote", "price", "decimal_odds", "starting_price"):
            if key in leg:
                odds_value = leg.get(key)
                break
    if odds_value is None and not isinstance(leg, Mapping):
        odds_value = getattr(leg, "odds", None)

    odds = _coerce_odds(odds_value)
    if odds is not None:
        implied = 1.0 / odds
        implied = max(min(implied, 1.0 - _EPSILON), _EPSILON)
        return implied, "implied_odds", identifier

    return 0.5, "default", identifier


def _load_calibration() -> None:
    """Reload calibration file if it has changed on disk."""
    global _calibration_cache, _calibration_mtime
    try:
        mtime = CALIBRATION_PATH.stat().st_mtime
    except FileNotFoundError:
        _calibration_cache = OrderedDict()
        _calibration_mtime = 0.0
        return
    if mtime <= _calibration_mtime:
        return
    with CALIBRATION_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
        parsed: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        for k, v in data.items():
            key = "|".join(sorted(k.split("|")))
            alpha = float(v.get("alpha", 1.0))
            beta = float(v.get("beta", 1.0))
            p = float(v.get("p", alpha / (alpha + beta)))
            if alpha <= 0 or beta <= 0 or not (0.0 < p < 1.0):
                raise ValueError(
                    f"Invalid calibration for {k}: alpha={alpha}, beta={beta}, p={p}"
                )
            source = "calibration_combo" if "|" in key else "calibration_leg"
            parsed[key] = {"alpha": alpha, "beta": beta, "p": p, "sources": [source]}
        _calibration_cache = parsed
        while len(_calibration_cache) > MAX_CACHE_SIZE:
            _calibration_cache.popitem(last=False)
    _calibration_mtime = mtime


def simulate_wrapper(legs: Iterable[object]) -> float:
    """Return calibrated win probability for a combination of ``legs``.

    Parameters
    ----------
    legs:
        Iterable describing the components of the combiné.

    Returns
    -------
    float
        Calibrated probability if available. When absent, each leg uses the
        most informative source among provided ``p`` values, cached
        calibrations or ``1 / odds`` as conservative fallback. The resulting
        probabilities are multiplied.
    """
    _load_calibration()
    legs_list = list(legs)
    key = _combo_key(legs_list)
    cached = _calibration_cache.get(key)
    if cached is not None:
        _calibration_cache.move_to_end(key)
        prob = cached.get("p")
        if prob is None:
            alpha = float(cached.get("alpha", 1.0))
            beta = float(cached.get("beta", 1.0))
            if alpha <= 0 or beta <= 0:
                raise ValueError(f"Invalid cached calibration for {key}: {cached}")
            prob = alpha / (alpha + beta)
            cached["p"] = prob
        return float(prob)

    prob = 1.0
    sources: List[str] = []
    details: Dict[str, Dict[str, Any]] = {}
    for leg in legs_list:
        leg_prob, source, identifier = _extract_leg_probability(leg)
        prob *= leg_prob
        sources.append(source)
        details[identifier] = {"p": leg_prob, "source": source}

    prob = max(min(prob, 1.0 - _EPSILON), _EPSILON)

    _calibration_cache[key] = {
        "alpha": 1.0,
        "beta": 1.0,
        "p": prob,
        "sources": sorted(set(sources)),
        "details": details,
    }
    _calibration_cache.move_to_end(key)
    while len(_calibration_cache) > MAX_CACHE_SIZE:
        _calibration_cache.popitem(last=False)
    return prob


def _combo_sources(legs: Iterable[Any]) -> set[str]:
    """Return source labels recorded for a combination of ``legs``."""

    legs_list = list(legs)
    if not legs_list:
        return set()
    key = _combo_key(legs_list)
    entry = _calibration_cache.get(key)
    if not entry:
        return set()
    sources = entry.get("sources")
    if isinstance(sources, str):
        return {sources}
    if isinstance(sources, Sequence) and not isinstance(sources, (str, bytes)):
        return {str(item) for item in sources}
    if sources is None:
        return {"calibration"}
    return {str(sources)}


def evaluate_combo(
    tickets: List[Dict[str, Any]],
    bankroll: float,
    *,
    calibration: str | os.PathLike[str] = "payout_calibration.yaml",
    allow_heuristic: bool | None = None,
) -> Dict[str, Any]:
    """Return EV ratio and expected payout for combined ``tickets``.

    Parameters
    ----------
    tickets:
        List of ticket mappings understood by :func:`ev_calculator.compute_ev_roi`.
    bankroll:
        Bankroll used for EV ratio computation.
    calibration:
        Path to ``payout_calibration.yaml``.  When absent and ``allow_heuristic``
        is ``False`` the evaluation is skipped.
    allow_heuristic:
        Optional override.  When ``True`` evaluation proceeds even if the
        calibration file is missing.

    Returns
    -------
    dict
        Mapping with keys ``status``, ``ev_ratio``, ``payout_expected``,
        ``notes`` and ``requirements``.
    """

    if allow_heuristic is None:
        allow_heuristic = os.getenv("ALLOW_HEURISTIC", "").lower() in {
            "1",
            "true",
            "yes",
        }

    calib_path = Path(calibration)
    notes: List[str] = []
    requirements: List[str] = []
    if not calib_path.exists():
        notes.append("no_calibration_yaml")
        requirements.append(str(calib_path))
        if not allow_heuristic:
            return {
                "status": "insufficient_data",
                "ev_ratio": 0.0,
                "roi": 0.0,
                "payout_expected": 0.0,
                "notes": notes,
                "requirements": requirements,
            }

    from ev_calculator import compute_ev_roi

    stats = compute_ev_roi(
        [dict(t) for t in tickets],
        budget=bankroll,
        simulate_fn=simulate_wrapper,
        kelly_cap=1.0,
        round_to=0.0,
    )

    combo_notes: List[str] = []
    for ticket in tickets:
        legs = ticket.get("legs")
        if not legs:
            continue
        sources = _combo_sources(legs)
        if not sources:
            continue
        if sources & _RELIABLE_SOURCES:
            continue
        combo_notes.append("combo_probabilities_unreliable")

    for note in combo_notes:
        if note not in notes:
            notes.append(note)

    return {
        "status": "ok",
        "ev_ratio": float(stats.get("ev_ratio", 0.0)),
        "roi": float(stats.get("roi", 0.0)),
        "payout_expected": float(stats.get("combined_expected_payout", 0.0)),
        "notes": notes,
        "requirements": requirements,
    }

