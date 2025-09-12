#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from typing import Dict


class ValidationError(Exception):
    """Raised when EV metrics do not meet required thresholds."""
    

def must_have(value, msg):
    """Raise ``RuntimeError`` if ``value`` is falsy."""
    if not value:
        raise RuntimeError(msg)
    return value


def validate_inputs(cfg, partants, odds, stats_je):
    """Validate raw inputs before any EV computation.

    This simplified validator only checks a single odds snapshot.

    Parameters
    ----------
    cfg : dict
        Configuration containing flags such as ``ALLOW_JE_NA``.
    partants : list[dict]
        List of runners with at least an ``id`` key.
    odds : dict
        Mapping ``id`` -> cote for the snapshot to analyse.
    stats_je : dict
        Dictionary containing at least a ``coverage`` percentage.
    """

    allow_je_na = cfg.get("ALLOW_JE_NA", False)
    if not partants or len(partants) < 6:
        raise ValidationError("Nombre de partants insuffisant (min 6)")

    if not odds:
        raise ValidationError("Cotes manquantes")
    for cid, cote in odds.items():
        if cote is None:
            raise ValidationError(f"Cote manquante pour {cid}")

    if not allow_je_na:
        coverage = stats_je.get("coverage") if stats_je else None
        if coverage is None or float(coverage) < 80:
            raise ValidationError("Couverture J/E insuffisante (<80%)") 
    
    return True


def validate(h30: dict, h5: dict, allow_je_na: bool) -> bool:
    ids30 = [x["id"] for x in h30.get("runners", [])]
    ids05 = [x["id"] for x in h5.get("runners", [])]
    if set(ids30) != set(ids05):
        raise ValueError("Partants incohérents (H-30 vs H-5).")
    if not ids05:
        raise ValueError("Aucun partant.")

    for snap, label in [(h30, "H-30"), (h5, "H-5")]:
        for r in snap.get("runners", []):
            if "odds" not in r or r["odds"] in (None, ""):
                raise ValueError(
                    f"Cotes manquantes {label} pour {r.get('name', r.get('id'))}."
                )
            try:
                if float(r["odds"]) <= 1.01:
                    raise ValueError(
                        f"Cote invalide {label} pour {r.get('name', r.get('id'))}: {r['odds']}"
                    )
            except Exception:
                raise ValueError(
                    f"Cote non numérique {label} pour {r.get('name', r.get('id'))}: {r.get('odds')}"
                )
    if not allow_je_na:
        for r in h5.get("runners", []):
            je = r.get("je_stats", {})
            if not je or ("j_win" not in je and "e_win" not in je):
                raise ValueError(
                    f"Stats J/E manquantes: {r.get('name', r.get('id'))}"
                )
    return True


def validate_ev(ev_sp: float, ev_global: float | None, need_combo: bool = True) -> bool:
    """Validate SP and combined EVs against environment thresholds.
    
    Parameters
    ----------
    ev_sp:
        Expected value for simple bets.
    ev_global:
        Expected value for combined bets. Ignored when ``need_combo`` is
        ``False``.
    need_combo:
        When ``True`` both SP and combined EVs must satisfy their respective
        thresholds.

    Returns
    -------
    bool
        ``True`` if all required thresholds are met.

    Raises
    ------
    ValidationError
        If any required EV is below its threshold.
    """

    min_sp = float(os.getenv("EV_MIN_SP", 0.20))
    min_global = float(os.getenv("EV_MIN_GLOBAL", 0.40))

    if ev_sp < min_sp:
        raise ValidationError("EV SP below threshold")

    if need_combo:
        if ev_global is None or ev_global < min_global:
            raise ValidationError("EV global below threshold")
            
    return True


def validate_policy(ev_global: float, roi_global: float, min_ev: float, min_roi: float) -> bool:
    """Validate global EV and ROI against minimum thresholds."""
    if ev_global < min_ev:
        raise ValidationError("EV global below threshold")
    if roi_global < min_roi:
        raise ValidationError("ROI global below threshold")
    return True


def validate_budget(stakes: Dict[str, float], budget_cap: float, max_vol_per_horse: float) -> bool:
    """Ensure total stake and per-horse stakes respect budget constraints."""
    total = sum(stakes.values())
    if total > budget_cap:
        raise ValidationError("Budget cap exceeded")
    per_horse_cap = budget_cap * max_vol_per_horse
    for horse, stake in stakes.items():
        if stake > per_horse_cap:
            raise ValidationError(f"Stake cap exceeded for {horse}")
    return True


def validate_combos(expected_payout: float, min_payout: float = 10.0) -> bool:
    """Validate that combined expected payout exceeds the minimum required.

    Parameters
    ----------
    expected_payout:
        Expected payout from the combined tickets.
    min_payout:
        Minimum acceptable payout. Defaults to ``10.0`` (euros).
    """
    if expected_payout <= min_payout:
        raise ValidationError("expected payout for combined bets below threshold")
    return True
