from __future__ import annotations


def kelly_fraction(p: float, odds: float, lam: float = 1.0, cap: float = 1.0) -> float:
    """Return Kelly fraction for given probability and odds.

    Parameters
    ----------
    p : float
        Win probability (0<p<1).
    odds : float
        Decimal odds (>1).
    lam : float, optional
        Fraction of Kelly to use, default 1.0.
    cap : float, optional
        Maximum allowed fraction, default 1.0.
    """
    if not 0 < p < 1:
        raise ValueError("p must be in (0,1)")
    if odds <= 1:
        raise ValueError("odds must be >1")
    frac = (p * odds - 1) / (odds - 1)
    frac *= lam
    return max(0.0, min(cap, frac))
