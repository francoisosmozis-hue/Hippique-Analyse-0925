import os
from typing import Any, Dict, Iterable, List, Tuple

from simulate_ev import allocate_dutching_sp
from runner_chain import validate_exotics_with_simwrapper


# ---------------------------------------------------------------------------
# Defaults & constants
# ---------------------------------------------------------------------------

BUDGET_CAP_EUR: float = 5.0
"""Maximum total budget allowed per course (EUR)."""

SP_SHARE: float = 0.60
"""Fraction of the budget dedicated to Single Placé tickets."""

COMBO_SHARE: float = 0.40
"""Fraction of the budget dedicated to combination tickets."""

EV_MIN_COMBO: float = 0.40
"""Minimum EV ratio required for a combination ticket to be considered."""

PAYOUT_MIN_COMBO: float = 10.0
"""Minimum expected payout (EUR) for a combination ticket."""

MAX_TICKETS: int = 2
"""Maximum number of tickets emitted (1 SP + 1 combo)."""

def _get_env_float(name: str, default: float) -> float:
    """Return a float from environment or the provided default."""
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def allow_combo(ev_global: float, roi_global: float, payout_est: float) -> bool:
    """Decide if a combo ticket can be issued based on EV, ROI and payout."""
    ev_min = _get_env_float("EV_MIN_GLOBAL", EV_MIN_COMBO)
    roi_min = _get_env_float("ROI_MIN_GLOBAL", 0.0)
    min_payout = _get_env_float("MIN_PAYOUT_COMBOS", PAYOUT_MIN_COMBO)
    if ev_global < ev_min or roi_global < roi_min or payout_est < min_payout:
        return False
    return True

def apply_ticket_policy(
    runners: Iterable[Dict[str, Any]],
    combo_candidates: Iterable[List[Dict[str, Any]]],
    *,
    ev_threshold: float = EV_MIN_COMBO,
    roi_threshold: float = 0.0,
    payout_threshold: float = PAYOUT_MIN_COMBO,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Allocate SP and combo tickets using the project defaults.

    Parameters
    ----------
    runners:
        Iterable of runner mappings ``{'id', 'name', 'odds', 'p'}`` used for SP
        dutching.
    combo_candidates:
        Iterable of candidate combination tickets evaluated via
        :func:`runner_chain.validate_exotics_with_simwrapper`.
    ev_threshold:
        Minimum EV ratio required for a combo ticket.
    roi_threshold:
        Minimum ROI required for a combo ticket.
    payout_threshold:
        Minimum expected payout (EUR) for a combo ticket.

    Returns
    -------
    tuple
        ``(tickets, info)`` where ``tickets`` contains at most one SP ticket
        and one combo ticket. ``info`` aggregates notes and flags from combo
        validation (including ``ALERTE_VALUE`` when applicable).
    """

    cfg_sp = {
        "BUDGET_TOTAL": BUDGET_CAP_EUR,
        "SP_RATIO": SP_SHARE,
        "MAX_VOL_PAR_CHEVAL": 0.60,
        "MIN_STAKE_SP": 0.10,
        "ROUND_TO_SP": 0.10,
        "KELLY_FRACTION": 0.5,
    }
    sp_tickets, _ = allocate_dutching_sp(cfg_sp, list(runners))
    sp_tickets.sort(key=lambda t: t.get("ev_ticket", 0.0), reverse=True)
    sp_tickets = sp_tickets[:1]

    combo_tickets: List[Dict[str, Any]] = []
    info: Dict[str, Any] = {"notes": [], "flags": {}}

    if combo_candidates:
        combo_tickets, info = validate_exotics_with_simwrapper(
            combo_candidates,
            bankroll=BUDGET_CAP_EUR * COMBO_SHARE,
            ev_min=ev_threshold,
            roi_min=roi_threshold,
            payout_min=payout_threshold,
        )
        combo_tickets = combo_tickets[:1]

    tickets = sp_tickets + combo_tickets
    if len(tickets) > MAX_TICKETS:
        tickets = tickets[:MAX_TICKETS]

    return tickets, info


# Provide a convenient alias
build_tickets = apply_ticket_policy


__all__ = [
    "allow_combo",
    "apply_ticket_policy",
    "build_tickets",
    "BUDGET_CAP_EUR",
    "SP_SHARE",
    "COMBO_SHARE",
    "EV_MIN_COMBO",
    "PAYOUT_MIN_COMBO",
    "MAX_TICKETS",
]
