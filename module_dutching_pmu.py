# -*- coding: utf-8 -*-
"""
module_dutching_pmu.py — GPI v5.1
---------------------------------
Allocation des mises en **Simple Placé** (ou assimilé) par **Kelly fractionné**,
avec **cap 60 %** par cheval et **budget total configurable** (par défaut 5 €).
Compatibilité pandas.

Principes
- On maximise l'EV du **panier** sous contrainte de risque.
- Kelly "net odds" : f* = (b*p - (1-p))/b, b = (odds - 1).
- Fractionnement λ (par défaut 0.5) pour limiter la variance (risk control).
- Cap par cheval (par défaut 0.60) pour éviter la concentration.
- Arrondi à 0,10 € par défaut (compatibilité opérateurs).
- Si `probs` est absent, fallback p ≈ 1/odds (prudence).

API principale
- dutching_kelly_fractional(odds, total_stake=5.0, probs=None,
                            lambda_kelly=0.5, cap_per_horse=0.60, round_to=0.1)
  → DataFrame: Cheval, Cote, p, f_kelly, Part (share), Mise (€), Gain brut (€), EV (€)

- ev_panier(df): EV total du panier (en €)

Notes
- Prévu pour des **cotes décimales** de type **placé**.
- Si vous passez des cotes gagnant, fournissez des `probs` adaptées (p_win).
"""
from typing import List, Optional, Sequence
import math
import pandas as pd

def _safe_prob(p: float) -> float:
    return max(0.01, min(0.90, float(p)))

def _kelly_fraction(p: float, o: float) -> float:
    b = max(0.0, float(o) - 1.0)
    if b <= 0.0:
        return 0.0
    f = (b * p - (1.0 - p)) / b
    return max(0.0, min(1.0, f))

def dutching_kelly_fractional(
    odds: Sequence[float],
    total_stake: float = 5.0,
    probs: Optional[Sequence[float]] = None,
    lambda_kelly: float = 0.5,
    cap_per_horse: float = 0.60,
    round_to: float = 0.10,
    horse_labels: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """
    Calcule une allocation Kelly fractionnée et capée.
    Args:
        odds: liste des cotes décimales (placé de préférence).
        total_stake: budget total à répartir (par défaut 5.0 €).
        probs: probabilités estimées (même ordre que `odds`). Si None, fallback 1/odds.
        lambda_kelly: fraction de Kelly (0<λ≤1), défaut 0.5.
        cap_per_horse: part max du budget par cheval (0..1), défaut 0.60.
        round_to: granularité d'arrondi des mises (€, 0.10 par défaut).
        horse_labels: noms/identifiants à afficher (optionnel).
    Returns:
        DataFrame avec colonnes: Cheval, Cote, p, f_kelly, Part, Mise (€), Gain brut (€), EV (€)
    """
    if not odds or len(odds) == 0:
        raise ValueError("`odds` ne peut pas être vide.")
    n = len(odds)
    if probs is None:
        probs = [1.0/max(1.01, float(o)) for o in odds]
    if horse_labels is None:
        horse_labels = [f"#{i+1}" for i in range(n)]

    # Kelly pur puis λ-fraction
    f_k = []
    for p, o in zip(probs, odds):
        p = _safe_prob(float(p))
        o = float(o)
        f_star = _kelly_fraction(p, o) * float(lambda_kelly)
        f_k.append(max(0.0, f_star))

    sum_f = sum(f_k)
    # Si tout 0 (EV négatives), on répartit à parts égales minimales (protéger pipeline)
    if sum_f <= 0:
        shares = [1.0/n] * n
    else:
        shares = [f/sum_f for f in f_k]

    # Appliquer cap par cheval puis renormaliser
    shares = [min(cap_per_horse, s) for s in shares]
    s = sum(shares)
    if s <= 0:
        shares = [1.0/n] * n
        s = 1.0
    shares = [s_i / s for s_i in shares]

    # Mises brutes puis arrondi
    stakes = [s_i * total_stake for s_i in shares]
    # Arrondir à la granularité (0.10 € par défaut)
    def _round_to(x: float, step: float) -> float:
        return round(x/step)*step
    stakes = [_round_to(st, round_to) for st in stakes]

    # Corriger l'écart d'arrondi pour respecter strictement le budget
    diff = round(total_stake - sum(stakes), 2)
    if abs(diff) >= round_to/2:
        # on pousse le reliquat sur le cheval le plus "efficace" (f_k max)
        try:
            idx = max(range(n), key=lambda i: f_k[i])
        except ValueError:
            idx = 0
        stakes[idx] = max(0.0, _round_to(stakes[idx] + diff, round_to))

    # Calculs gains/EV
    gains = [st * o for st, o in zip(stakes, odds)]
    evs = []
    for st, o, p in zip(stakes, odds, probs):
        p = _safe_prob(float(p))
        gain_net = st * (o - 1.0)
        ev = p * gain_net - (1.0 - p) * st
        evs.append(ev)

    df = pd.DataFrame({
        "Cheval": horse_labels,
        "Cote": [float(o) for o in odds],
        "p": [float(_safe_prob(p)) for p in probs],
        "f_kelly": f_k,
        "Part": shares,
        "Mise (€)": [round(st,2) for st in stakes],
        "Gain brut (€)": [round(g,2) for g in gains],
        "EV (€)": [round(e,2) for e in evs],
    })
    return df

def ev_panier(df: pd.DataFrame) -> float:
    """EV totale (en €) du panier SP."""
    if df.empty:
        return 0.0
    return float(df["EV (€)"].sum())
