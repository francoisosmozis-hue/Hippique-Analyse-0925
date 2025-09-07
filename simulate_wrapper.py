
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
simulate_wrapper.py — Wrapper EV factuel (aucun hasard)
------------------------------------------------------
But : fournir une interface UNIQUE, déterministe et vérifiable pour évaluer
l'EV des combinés (TRIO / COUPLE PLACE / ZE4...), SANS heuristique par défaut.

Principe :
- Tente d'abord validator_ev_v2.validate_with_simulate_ev(...).
- Si la calibration ou les entrées sont insuffisantes → **renvoie un statut "insufficient_data"**
  et n'estime PAS l'EV (ev_ratio=None). Aucune supposition.
- Un fallback conservateur n'est possible que si allow_heuristic=True (défaut=False).

Sortie standardisée :
{
  "status": "ok" | "insufficient_data" | "error",
  "source": "validator_ev_v2" | "simulate_ev" | "heuristic",
  "ev_ratio": float | null,
  "p_success": float | null,
  "payout_expected": float | null,
  "notes": [ ... informations factuelles ... ],
  "requirements": {
      "has_p_place": bool,
      "has_calibration": bool,
      "nplace": int,
      "legs": [ ... ]
  }
}

Décision pipeline :
- Si status != "ok" → pas de combiné (abstention sur combinés, SP possible).
- Si status == "ok" → appliquer les seuils GPI (EV ≥ +40 %, payout ≥ 10 €).
"""

from __future__ import annotations
import json, math
from pathlib import Path
from typing import Dict, Any, List, Optional

def _has_calibration(calib_path: Optional[str]) -> bool:
    if not calib_path: return False
    p = Path(calib_path)
    return p.exists() and p.stat().st_size > 0

def _sanitize_pmap(p_map: Dict[str, float], nplace: int) -> Dict[str, float]:
    # Clamp [0.005, 0.90] puis renormalisation stricte à "nplace"
    if not p_map: return {}
    clamped = {str(k): max(0.005, min(0.90, float(v))) for k,v in p_map.items()}
    s = sum(clamped.values())
    if s <= 0:
        return clamped
    scale = float(nplace) / s
    return {k: v*scale for k,v in clamped.items()}

def evaluate_combo(
    combo_type: str,
    legs: List[str],
    stake: float,
    p_place: Dict[str, float],
    nplace: int,
    calib_path: Optional[str] = "payout_calibration.yaml",
    allow_heuristic: bool = False
) -> Dict[str, Any]:
    """
    Évalue un combiné de manière factuelle (pas d'approx si données insuffisantes).
    """
    notes: List[str] = []
    # Pré-conditions minimales
    if not combo_type or not legs or stake <= 0:
        return {"status": "error", "source": None, "ev_ratio": None, "p_success": None,
                "payout_expected": None, "notes": ["invalid_inputs"], "requirements": {
                    "has_p_place": bool(p_place), "has_calibration": _has_calibration(calib_path),
                    "nplace": int(nplace), "legs": legs}}

    has_calib = _has_calibration(calib_path)
    if not p_place:
        return {"status": "insufficient_data", "source": None, "ev_ratio": None, "p_success": None,
                "payout_expected": None, "notes": ["missing_p_place"], "requirements": {
                    "has_p_place": False, "has_calibration": has_calib, "nplace": int(nplace), "legs": legs}}

    # Sanitize p_map
    p_map = _sanitize_pmap(p_place, nplace)

    # Essayer le validateur/simulateur officiel
    try:
        import validator_ev_v2 as val  # prioritaire (standardisé)
        out = val.validate_with_simulate_ev(combo_type, legs, stake, p_map, nplace=nplace, calib_path=calib_path)
        if isinstance(out, dict) and "ev_ratio" in out and "payout_expected" in out:
            # Si la calibration n'était pas disponible, val retourne quand même un payout par défaut.
            # Ici, pour rester 100% factuel, on exige la calibration sauf si allow_heuristic=True.
            if not has_calib and not allow_heuristic:
                return {"status": "insufficient_data", "source": "validator_ev_v2", "ev_ratio": None,
                        "p_success": float(out.get("p_success", 0.0)) if out.get("p_success") is not None else None,
                        "payout_expected": None,
                        "notes": ["no_calibration_yaml"], "requirements": {
                            "has_p_place": True, "has_calibration": False, "nplace": int(nplace), "legs": legs}}
            return {"status": "ok", "source": "validator_ev_v2", "ev_ratio": float(out["ev_ratio"]),
                    "p_success": float(out.get("p_success", 0.0)) if out.get("p_success") is not None else None,
                    "payout_expected": float(out["payout_expected"]),
                    "notes": out.get("details", {}), "requirements": {
                        "has_p_place": True, "has_calibration": has_calib, "nplace": int(nplace), "legs": legs}}
    except Exception as e:
        notes.append(f"validator_error:{type(e).__name__}")

    # Sans calibration et allow_heuristic=False => pas d'estimation
    if not has_calib and not allow_heuristic:
        return {"status": "insufficient_data", "source": None, "ev_ratio": None, "p_success": None,
                "payout_expected": None, "notes": notes + ["no_calibration_yaml"],
                "requirements": {"has_p_place": True, "has_calibration": False, "nplace": int(nplace), "legs": legs}}

    # Dernier recours : heuristique (UNIQUEMENT si explicitement autorisée)
    if allow_heuristic:
        try:
            from validator_ev_v2 import _approx_p_success, _load_yaml_calib, _calib_payout_expected  # type: ignore
            ps = _approx_p_success(combo_type, legs, p_map, nplace)
            calib = _load_yaml_calib(calib_path) if has_calib else {}
            payout = _calib_payout_expected(combo_type, legs, p_map, calib, default_min=10.0)
            ev_ratio = ps * (payout / max(1e-9, stake)) - (1.0 - ps)
            return {"status": "ok", "source": "heuristic", "ev_ratio": float(ev_ratio),
                    "p_success": float(ps), "payout_expected": float(payout),
                    "notes": ["heuristic_mode"], "requirements": {
                        "has_p_place": True, "has_calibration": has_calib, "nplace": int(nplace), "legs": legs}}
        except Exception as e:
            notes.append(f"heuristic_error:{type(e).__name__}")

    return {"status": "error", "source": None, "ev_ratio": None, "p_success": None,
            "payout_expected": None, "notes": notes or ["unknown_error"],
            "requirements": {"has_p_place": True, "has_calibration": has_calib, "nplace": int(nplace), "legs": legs}}
