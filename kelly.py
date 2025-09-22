"""Utilities to compute Kelly betting fraction."""


def kelly_fraction(p_true, odds_dec, cap=None):
    """Compute the Kelly fraction given the true probability and decimal odds.

    Args:
        p_true (float): Estimated true probability of the outcome.
        odds_dec (float): Decimal odds offered by the bookmaker.
        cap (float | None): Optional upper bound for the returned fraction.

    Returns:
        float: Kelly fraction clipped to the requested bounds.
    """
    
    try:
        p = float(p_true)
        odds = float(odds_dec)
    except (TypeError, ValueError):
        return 0.0

    if not 0.0 < p < 1.0:
        return 0.0    
    if odds <= 1.0:
        return 0.0

    b = odds - 1.0
    numerator = b * p - (1.0 - p)
    if numerator <= 0.0:
        return 0.0

    fraction = numerator / b
    fraction = max(0.0, min(1.0, fraction))

    if cap is not None:
        try:
            cap_value = float(cap)
        except (TypeError, ValueError):
            cap_value = None
        else:
            if cap_value < 0.0:
                return 0.0
            fraction = min(fraction, cap_value)

    return fraction
