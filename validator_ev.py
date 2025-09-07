
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validator_ev_v2.py — Validation EV combinés (TRIO / COUPLE PLACE / ZE4)
----------------------------------------------------------------------
- Essaie d'utiliser simulate_ev si disponible (API souple).
- Sinon, calcule une probabilité de succès approximative à partir des p_place
  (indépendance approchée + pénalité de corrélation) et applique une calibration
  de payout si disponible (payout_calibration.yaml).
- Retourne un dict {ev_ratio, payout_expected, p_success, details}.

Formule EV (ratio du stake):
  EV_ratio = p_success * (payout_expected / stake) - (1 - p_success)

Usage:
  from validator_ev_v2 import validate_with_simulate_ev
  res = validate_with_simulate_ev("TRIO", ["3","5","7"], stake=2.0, p_place={"3":0.32,"5":0.28,"7":0.18}, nplace=3,
                                  calib_path="payout_calibration.yaml")
"""

from __future__ import annotations
import math, json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

def _load_yaml_calib(calib_path: str|None) -> Dict[str, Any]:
    if not calib_path: return {}
    p = Path(calib_path)
    if not p.exists(): return {}
    try:
        import yaml  # type: ignore
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}

def _simulate_with_module(combo_type: str, legs_nums: List[str], stake: float,
                          p_map: Dict[str,float], nplace: int,
                          calib_path: str|None) -> Optional[Dict[str, Any]]:
    # Try simulate_ev first
    try:
        import simulate_ev as sev  # type: ignore
    except Exception:
        sev = None
    try:
        import validator_ev as val  # type: ignore
    except Exception:
        val = None
    # Prefer validator_ev if it exposes a richer function
    for mod in (val, sev):
        if not mod: continue
        # Try generic 'validate_with_simulate_ev'
        func = getattr(mod, "validate_with_simulate_ev", None)
        if callable(func):
            try:
                out = func(combo_type, legs_nums, stake, p_map, nplace=nplace, calib_path=calib_path)
                # Expect keys
                if isinstance(out, dict) and "ev_ratio" in out:
                    return out
            except Exception:
                pass
        # Fallback try: 'simulate_combo' returning payout and p_success
        func2 = getattr(mod, "simulate_combo", None)
        if callable(func2):
            try:
                res = func2(combo_type=combo_type, legs=legs_nums, p_place=p_map, nplace=nplace, calib_path=calib_path)
                if isinstance(res, dict) and "p_success" in res and "payout_expected" in res:
                    ps = float(res["p_success"]); payout = float(res["payout_expected"])
                    ev_ratio = ps * (payout/max(1e-9, stake)) - (1.0 - ps)
                    return {"ev_ratio": ev_ratio, "payout_expected": payout, "p_success": ps, "details": {"module":"simulate_combo"}}
            except Exception:
                pass
    return None

def _approx_p_success(combo_type: str, legs_nums: List[str], p_map: Dict[str,float], nplace: int) -> float:
    # Independence approximation with correlation penalty.
    ps = 0.0
    legs = [p_map.get(x, 0.0) for x in legs_nums]
    legs = [max(0.0, min(0.9, float(p))) for p in legs]
    if combo_type.upper() in ("TRIO","ZE4","ZE234"):
        # probability all 3 (or first 3 legs) finish in top nplace (usually 3)
        k = 3
        if len(legs) < k: return 0.0
        legs = legs[:k]
        # naive inclusion: ∏ p_i scaled down by correlation penalty
        naive = 1.0
        for p in legs: naive *= p
        # correlation penalty: gamma^C where C=k*(k-1)/2 (pairs), gamma≈0.85
        C = k*(k-1)//2
        gamma = 0.85 if nplace >= 3 else 0.8
        ps = naive * (gamma ** C)
    elif combo_type.upper() in ("COUPLE","COUPLE_PLACE","CP"):
        # both in top nplace
        if len(legs) < 2: return 0.0
        p1, p2 = legs[0], legs[1]
        naive = p1 * p2
        gamma = 0.90 if nplace >= 3 else 0.85
        ps = naive * gamma
    else:
        ps = 0.0
    # clamp
    return max(0.0, min(0.95, ps))

def _calib_payout_expected(combo_type: str, legs_nums: List[str], p_map: Dict[str,float],
                           calib: Dict[str, Any], default_min: float=10.0) -> float:
    # If calibration provides median/quantile per type and difficulty, use it.
    # Derive a 'difficulty' proxy from sum of (1-p_i) and presence of outsider.
    if not calib:
        return default_min
    typ = combo_type.upper()
    dsum = sum(1.0 - p_map.get(x, 0.0) for x in legs_nums)
    outsider = any(p_map.get(x, 0.0) < 0.18 for x in legs_nums)
    bucket = "hard" if dsum > 2.0 or outsider else "base"
    try:
        return float(calib[typ][bucket]["median"])
    except Exception:
        # try any number in the struct
        try:
            vals = calib.get(typ, {})
            if isinstance(vals, dict):
                for v in vals.values():
                    if isinstance(v, dict) and "median" in v:
                        return float(v["median"])
        except Exception:
            pass
    return default_min

def validate_with_simulate_ev(combo_type: str, legs_nums: List[str], stake: float,
                              p_map: Dict[str,float], nplace: int = 3,
                              calib_path: str|None = None) -> Dict[str, Any]:
    """
    API unifiée utilisée par pipeline_run_v3.py
    """
    # First, try external simulators if available
    out = _simulate_with_module(combo_type, legs_nums, stake, p_map, nplace, calib_path)
    if isinstance(out, dict) and "ev_ratio" in out:
        return out

    # Fallback: approximate computation
    ps = _approx_p_success(combo_type, legs_nums, p_map, nplace)
    calib = _load_yaml_calib(calib_path)
    payout = _calib_payout_expected(combo_type, legs_nums, p_map, calib, default_min=10.0)
    ev_ratio = ps * (payout / max(1e-9, stake)) - (1.0 - ps)

    return {
        "ev_ratio": float(ev_ratio),
        "p_success": float(ps),
        "payout_expected": float(payout),
        "details": {"approx":"indep_gamma", "nplace": nplace}
    }
