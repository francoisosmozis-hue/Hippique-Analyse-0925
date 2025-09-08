"""Risk management utilities for betting strategies.

This module maintains a simple JSON history of bets and resulting bankroll
states.  It provides helpers to compute risk metrics such as maximum drawdown
and variance of returns, and exposes :func:`next_stake` which applies a
fractional Kelly criterion adjusted by those metrics to limit losses.
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import variance as _variance
from typing import Dict, List, Optional

# Location of the history file relative to this module
_HISTORY_FILE = Path(__file__).with_name("bankroll_history.json")


# ---------------------------------------------------------------------------
# History handling
# ---------------------------------------------------------------------------
def _load_history(path: Path = _HISTORY_FILE) -> List[Dict[str, float]]:
    """Load betting history from ``path`` if it exists."""
    if path.exists():
        return json.loads(path.read_text())
    return []


def _save_history(history: List[Dict[str, float]], path: Path = _HISTORY_FILE) -> None:
    """Persist ``history`` to ``path`` in JSON format."""
    path.write_text(json.dumps(history, indent=2))


def record_bet(stake: float, profit: float, path: Path = _HISTORY_FILE) -> float:
    """Append a bet result to the history.

    Parameters
    ----------
    stake:
        Amount wagered.
    profit:
        Net profit for the bet (negative for a loss).
    path:
        Optional custom location for the history file.

    Returns
    -------
    float
        Updated bankroll after recording the bet.
    """
    history = _load_history(path)
    bankroll = history[-1]["bankroll"] + profit if history else profit
    history.append({"stake": stake, "profit": profit, "bankroll": bankroll})
    _save_history(history, path)
    return bankroll


# ---------------------------------------------------------------------------
# Risk metrics
# ---------------------------------------------------------------------------
def max_drawdown(bankrolls: List[float]) -> float:
    """Return the maximum drawdown for a sequence of bankroll values."""
    peak = bankrolls[0] if bankrolls else 0.0
    max_dd = 0.0
    for value in bankrolls:
        if value > peak:
            peak = value
        drawdown = peak - value
        if drawdown > max_dd:
            max_dd = drawdown
    return max_dd


def variance_of_returns(bankrolls: List[float]) -> float:
    """Return the variance of successive bankroll returns."""
    if len(bankrolls) < 2:
        return 0.0
    returns = [b - a for a, b in zip(bankrolls[:-1], bankrolls[1:])]
    if len(returns) < 2:
        return 0.0
    return _variance(returns)


# ---------------------------------------------------------------------------
# Stake management
# ---------------------------------------------------------------------------
def next_stake(budget: float, kelly_fraction: float, bankroll_state: Optional[List[float]] = None) -> float:
    """Compute the next stake using fractional Kelly adjusted for risk metrics.

    Parameters
    ----------
    budget:
        Current available bankroll.
    kelly_fraction:
        Fractional Kelly to apply (between 0 and 1).
    bankroll_state:
        Sequence of historical bankroll values used to estimate drawdown and
        variance.  If ``None`` the on-disk history is used.

    Returns
    -------
    float
        Recommended stake for the next bet, capped by ``budget`` and adjusted
        downwards when drawdown or variance are high.
    """
    bankrolls = bankroll_state if bankroll_state is not None else [h["bankroll"] for h in _load_history()]
    base_stake = budget * kelly_fraction

    if not bankrolls:
        return min(base_stake, budget)

    dd = max_drawdown(bankrolls)
    var = variance_of_returns(bankrolls)

    risk_adjust = 1.0
    if budget > 0:
        risk_adjust -= dd / budget
    if var > 0:
        risk_adjust /= 1 + var

    stake = max(base_stake * max(risk_adjust, 0.0), 0.0)
    return min(stake, budget)


__all__ = [
    "record_bet",
    "max_drawdown",
    "variance_of_returns",
    "next_stake",
]
