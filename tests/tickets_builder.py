import os


def allow_combo(ev_global: float, payout_est: float) -> bool:
    """Simple helper used in tests.

    Returns
    -------
    bool
        ``True`` if ``ev_global`` meets ``EV_MIN_GLOBAL`` and ``payout_est`` is
        strictly greater than 10.
    """
    try:
        threshold = float(os.getenv("EV_MIN_GLOBAL", "0"))
    except ValueError:
        threshold = 0.0
    return ev_global >= threshold and payout_est > 10.0


__all__ = ["allow_combo"]
