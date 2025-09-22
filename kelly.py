from __future__ import annotations


def kelly_fraction(p: float, odds: float, lam: float = 1.0, cap: float = 1.0) -> float:
    """Return a capped Kelly fraction for the given probability and odds."""

    try:
        probability = float(p)
        price = float(odds)
        lam_value = float(lam)
        cap_value = float(cap)
    except (TypeError, ValueError):
        return 0.0

    if not 0.0 < probability < 1.0:
        return 0.0
    if price <= 1.0:
        return 0.0
    if not lam_value > 0.0:
        return 0.0

    net_odds = price - 1.0
    if net_odds <= 0.0:
        return 0.0

    kelly = (probability * price - 1.0) / net_odds
    if kelly <= 0.0:
        return 0.0

    kelly *= lam_value
    if cap_value > 0.0:
        return min(cap_value, kelly)
    return kelly
