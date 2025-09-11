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
from pathlib import Path
from typing import Dict, Iterable

import yaml

CALIBRATION_PATH = Path("calibration/probabilities.yaml")

# Maximum number of entries to keep in the calibration cache.  When the limit
# is exceeded, least recently used keys are discarded.  This prevents
# unbounded growth when many unique combinations are requested.
MAX_CACHE_SIZE = 500

_calibration_cache: OrderedDict[str, Dict[str, float]] = OrderedDict()
_calibration_mtime: float = 0.0


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
        parsed: OrderedDict[str, Dict[str, float]] = OrderedDict()
        for k, v in data.items():
            key = "|".join(sorted(k.split("|")))
            alpha = float(v.get("alpha", 1.0))
            beta = float(v.get("beta", 1.0))
            p = float(v.get("p", alpha / (alpha + beta)))
            if alpha <= 0 or beta <= 0 or not (0.0 < p < 1.0):
                raise ValueError(
                    f"Invalid calibration for {k}: alpha={alpha}, beta={beta}, p={p}"
                )
            parsed[key] = {"alpha": alpha, "beta": beta, "p": p}
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
        Calibrated probability if available. When absent, each leg is assigned
        a Beta posterior mean with :math:`\alpha = \beta = 1` if no data is
        available, and the resulting probabilities are multiplied..
    """
    _load_calibration()
    key = "|".join(sorted(map(str, legs)))
    if key in _calibration_cache:
        _calibration_cache.move_to_end(key)
        return _calibration_cache[key]["p"]

    prob = 1.0
    alpha = beta = 1.0
    for leg in legs:
        s = str(leg)
        if s in _calibration_cache:
            alpha = _calibration_cache[s].get("alpha", 1.0)
            beta = _calibration_cache[s].get("beta", 1.0)
        else:
            alpha = beta = 1.0
        prob *= alpha / (alpha + beta)

    _calibration_cache[key] = {"alpha": alpha, "beta": beta, "p": prob}
    _calibration_cache.move_to_end(key)
    while len(_calibration_cache) > MAX_CACHE_SIZE:
        _calibration_cache.popitem(last=False)
    return prob

