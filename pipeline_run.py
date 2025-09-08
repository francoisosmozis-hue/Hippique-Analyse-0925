#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline_run.py — GPI v5.1 (cap 5 €) — version corrigée
Chaîne de décision complète (EV + budget + Kelly cap 60 %) intégrée.

Nouveautés / correctifs :
- Indentation corrigée dans _filter_ev (hiérarchie CP > TRIO > ZE4).
- Ajout de run_pipeline(...) pour compat avec runner_chain.py.
- Fallback internes : simulate_tickets_ev / select_best_two / allocate_kelly_capped.
- Reporting stable ('reporting') consommé par runner_chain.py.

Utilisation CLI (optionnelle) :
  python pipeline_run.py --budget 5 --ttl-seconds 21600 --candidates data/cands.json
  python pipeline_run.py --reunion R1 --course C3 --date 2025-09-07

Sorties :
  - JSON sur stdout (tickets + stakes) OU abstention motivée.
"""

from __future__ import annotations
import json
import sys
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from math import isfinite

# ==== Constantes verrouillées (projet) ====
BUDGET_CAP_EUR = 5.0
EV_MIN_COMBO = 0.40        # +40 % requis pour combinés
ROI_MIN_SP = 0.20          # +20 % mini pour panier SP
PAYOUT_MIN_COMBO = 10.0    # € attendu min pour autoriser un combiné
SP_SHARE, COMBO_SHARE = 0.60, 0.40
MAX_VOL_PER_HORSE = 0.60
MAX_TICKETS = 2

# ==== Imports optionnels (tolérance si absents) ====
def _safe_import(name: str):
    try:
        return __import__(name)
    except Exception:
        return None

simulate_wrapper = _safe_import("simulate_wrapper")
p_finale_export = _safe_import("p_finale_export")
simulate_ev     = _safe_import("simulate_ev")

# =============== Utilitaires internes =================

def _valid_float(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        return v if isfinite(v) else default
    except Exception:
        return default

def _place_slots(n: int) -> int:
    return 3 if n >= 8 else (2 if n >= 4 else 1)

def _implied_p_place_from_snapshot(snapshot: Dict[str, Any]) -> Dict[str, float]:
    """Essaye simulate_ev.implied_probs_place_from_odds ; sinon uniformisé."""
    runners = snapshot.get("runners") or snapshot.get("partants") or []
    if not runners:
        return {}
    if simulate_ev and hasattr(simulate_ev, "implied_probs_place_from_odds"):
        try:
            # attend liste [{"num": "...", "odds_win": x, "odds_place": y?}, ...]
            pmap = simulate_ev.implied_probs_place_from_odds(runners)
            if isinstance(pmap, dict) and pmap:
                return {str(k): float(v) for k, v in pmap.items()}
        except Exception:
            pass
    # fallback: uniformisé (renormalisé à n places)
    ids = [str(r.get("num")) for r in runners if r.get("num") is not None]
    if not ids:
        return {}
    base = 1.0 / max(1, len(ids))
    # renormalise à 'slots'
    slots = float(_place_slots(len(ids)))
    scale = slots / (base*len(ids))
    return {i: base*scale for i in ids}

def _build_market(snapshot: Dict[str, Any], p_place: Dict[str, float]) -> Dict[str, Any]:
    """Construit un dict 'market' (n_partants, horses[{num,p,cote}])."""
    runners = snapshot.get("runners") or snapshot.get("partants") or []
    horses = []
    for r in runners:
        num = str(r.get("num"))
        if not num:
            continue
        p = float(p_place.get(num, 0.0))
        # on essaie de remonter une cote place indicative si fournie
        odds = None
        for key in ("odds_place", "cote_place", "cote"):
            if r.get(key) is not None:
                try:
                    odds = float(str(r[key]).replace(",", "."))
                    break
                except Exception:
                    pass
        horses.append({"num": num, "p": p, "cote": odds})
    return {"n_partants": len(runners), "horses": horses, "overround": None}

# =============== Simulation EV (fallback interne) =================

def _ev_ratio_sp_legs(legs: List[Dict[str, Any]]) -> float:
    """
    EV moyenne pondérée par mises pour un ticket SP de plusieurs legs.
    legs: [{"horse": "7", "p": 0.42, "od]()
