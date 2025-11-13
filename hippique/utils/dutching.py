"""Dutching helpers used by the ROI-first staking policy."""
from __future__ import annotations

from collections.abc import Iterable


def equal_profit_stakes(odds_list: Iterable[float], total_stake: float) -> list[float]:
    """Return equal-profit stakes for the provided decimal odds."""

    inv_sum = sum(1.0 / float(o) for o in odds_list)
    if inv_sum <= 0:
        raise ValueError("Invalid odds list")
    return [(total_stake / float(o)) / inv_sum for o in odds_list]


def diversify_guard(horses_meta: Iterable[dict]) -> bool:
    """Return ``False`` when multiple legs are overly correlated.

    The heuristic is deliberately simple: if at least two legs share the same
    stable (``ecurie``) *and* the same driver/jockey, the dutching is refused
    when their last recorded chrono differs by less than ``0.4`` seconds.  When
    the metadata is incomplete the guard is lenient and allows the ticket.
    """

    seen: dict[tuple[str | None, str | None], dict] = {}
    for horse in horses_meta:
        key = (horse.get("ecurie"), horse.get("driver"))
        if not any(key):
            continue  # insufficient information to enforce the guard
        if key in seen:
            prev = seen[key]
            chrono_prev = prev.get("chrono_last")
            chrono_curr = horse.get("chrono_last")
            if chrono_prev is None or chrono_curr is None:
                continue
            if abs(float(chrono_curr) - float(chrono_prev)) < 0.4:
                return False
        else:
            seen[key] = horse
    return True


def require_mid_odds(horses_meta: Iterable[dict]) -> bool:
    """Ensure at least one leg offers a mid-range odds (between 4.0 and 7.0)."""

    for horse in horses_meta:
        odds = horse.get("odds")
        if odds is None:
            continue
        if 4.0 <= float(odds) <= 7.0:
            return True
    return False
