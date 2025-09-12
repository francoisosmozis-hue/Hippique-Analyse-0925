import os


def _get_env_float(name: str, default: float) -> float:
    """Return a float from environment or the provided default."""
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def allow_combo(ev_global: float, roi_global: float, payout_est: float) -> bool:
    """Decide if a combo ticket can be issued based on EV, ROI and payout."""
    ev_min = _get_env_float("EV_MIN_GLOBAL", 0.0)
    roi_min = _get_env_float("ROI_MIN_GLOBAL", 0.0)
    min_payout = _get_env_float("MIN_PAYOUT_COMBOS", 10.0)
    if ev_global < ev_min or roi_global < roi_min or payout_est < min_payout:
        return False
    return True

__all__ = ["allow_combo"]
