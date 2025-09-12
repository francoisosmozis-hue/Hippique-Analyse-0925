import os


def allow_combo(ev_global: float, payout_est: float) -> bool:
    """Minimal helper to decide if a combo ticket can be issued."""
    try:
        threshold = float(os.getenv("EV_MIN_GLOBAL", "0"))
    except ValueError:
        threshold = 0.0
    return ev_global >= threshold and payout_est > 10.0


__all__ = ["allow_combo"]
