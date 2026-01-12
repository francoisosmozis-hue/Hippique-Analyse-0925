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
- Si `probs` est absent, `prob_fallback` fournit p (défaut ≈ 1/odds).

API principale
- dutching_kelly_fractional(odds, total_stake=5.0, probs=None,
                            prob_fallback=lambda o: 1/max(1.01,o),
                            lambda_kelly=0.5, cap_per_horse=0.60, round_to=0.1)
  → DataFrame: Cheval, Cote, p, f_kelly, Part (share), Stake (€), Gain brut (€), EV (€)

- ev_panier(df): EV total du panier (en €)

Notes
- Prévu pour des **cotes décimales** de type **placé**.
- Si vous passez des cotes gagnant, fournissez des `probs` adaptées (p_win).
"""

from collections.abc import Callable, Sequence

import pandas as pd
from kelly import kelly_fraction


def _safe_prob(p: float) -> float:
    return max(0.01, min(0.90, float(p)))


def dutching_kelly_fractional(
    odds: Sequence[float],
    total_stake: float = 5.0,
    probs: Sequence[float] | None = None,
    prob_fallback: Callable[[float], float] = lambda o: 1 / max(1.01, float(o)),
    lambda_kelly: float = 0.5,
    cap_per_horse: float = 0.60,
    round_to: float = 0.10,
    horse_labels: Sequence[str] | None = None,
) -> pd.DataFrame:
    """
    Calcule une allocation Kelly fractionnée et capée.
    Args:
        odds: liste des cotes décimales (placé de préférence).
        total_stake: budget total à répartir (par défaut 5.0 €).
        probs: probabilités estimées (même ordre que `odds`). Si None, `prob_fallback` est utilisé.
        prob_fallback: fonction appliquée aux cotes pour obtenir p si `probs` est None
                       (défaut lambda o: 1/max(1.01,o)).
        lambda_kelly: fraction de Kelly (0<λ≤1), défaut 0.5.
        cap_per_horse: ratio max du Kelly par cheval (0..1), défaut 0.60.
        round_to: granularité d'arrondi des mises (€, 0.10 par défaut). Utilisez
            une valeur ≤ 0 pour désactiver l'arrondi et conserver les montants
            Kelly exacts.
        horse_labels: noms/identifiants à afficher (optionnel).
    Returns:
        DataFrame avec colonnes: Cheval, Cote, p, f_kelly, Part, Stake (€), Gain brut (€), EV (€).
        Lorsque l'arrondi est actif, les montants de mises et les EV/ROI sont
        calculés sur les valeurs arrondies. Avec `round_to <= 0`, aucune
        correction d'arrondi n'est appliquée et les EV/ROI reflètent les mises
        continues issues du Kelly fractionné.
    """
    if not odds or len(odds) == 0:
        raise ValueError("`odds` ne peut pas être vide.")
    n = len(odds)
    if probs is None:
        probs = [prob_fallback(float(o)) for o in odds]
    if horse_labels is None:
        horse_labels = [f"#{i + 1}" for i in range(n)]

    # Fraction Kelly directe par cheval (déjà capée)
    f_k = []
    for p, o in zip(probs, odds, strict=True):
        p = _safe_prob(float(p))
        o = float(o)
        f_k.append(kelly_fraction(p, o, lam=float(lambda_kelly), cap=float(cap_per_horse)))

    if sum(f_k) <= 0:
        stakes = [total_stake / n] * n
    else:
        stakes = [f * total_stake for f in f_k]
        total_alloc = sum(stakes)
        if total_alloc > total_stake:
            factor = total_stake / total_alloc
            stakes = [st * factor for st in stakes]

    # Arrondir à la granularité (0.10 € par défaut)
    def _round_to(x: float, step: float) -> float:
        if step <= 0:
            return float(x)
        return round(x / step) * step

    stakes = [_round_to(st, round_to) for st in stakes]

    # Corriger l'écart d'arrondi uniquement si dépassement (et arrondi actif)
    if round_to > 0:
        diff = round(total_stake - sum(stakes), 2)
        if abs(diff) >= round_to / 2:
            try:
                idx = max(range(n), key=lambda i: f_k[i])
            except ValueError:
                idx = 0
            stakes[idx] = max(0.0, _round_to(stakes[idx] + diff, round_to))

    sum_alloc = sum(stakes)
    shares = [st / sum_alloc if sum_alloc else 0 for st in stakes]

    # Calculs gains/EV
    gains = [st * o for st, o in zip(stakes, odds, strict=True)]
    evs = []
    for st, o, p in zip(stakes, odds, probs, strict=True):
        p = _safe_prob(float(p))
        gain_net = st * (o - 1.0)
        ev = p * gain_net - (1.0 - p) * st
        evs.append(ev)

    df = pd.DataFrame(
        {
            "Cheval": horse_labels,
            "Cote": [float(o) for o in odds],
            "p": [float(_safe_prob(p)) for p in probs],
            "f_kelly": f_k,
            "Part": shares,
            "Stake (€)": [round(st, 2) for st in stakes],
            "Gain brut (€)": [round(g, 2) for g in gains],
            "EV (€)": [round(e, 2) for e in evs],
        }
    )
    return df


def ev_panier(df: pd.DataFrame) -> float:
    """EV totale (en €) du panier SP."""
    if df.empty:
        return 0.0
    return float(df["EV (€)"].sum())


# ================== Dutching SP – Implémentation + Aliases Legacy ==================
from typing import Any


def _parse_odds_place(r: dict[str, Any]) -> float:
    for k in ("odds_place", "cote_place", "odds", "cote"):
        v = r.get(k)
        if v is not None:
            try:
                return float(str(v).replace(",", "."))
            except Exception:
                pass
    return 4.0  # fallback prudente


def _implied_probs_place_from_odds(runners: list[dict[str, Any]]) -> dict[str, float]:
    ids, px = [], []
    for r in runners:
        num = str(r.get("num") or r.get("id") or "").strip()
        if not num:
            continue
        o = _parse_odds_place(r)
        o = 1.01 if o <= 1.0 else o  # borne
        p = max(0.01, min(0.90, 1.0 / o))
        ids.append(num)
        px.append(p)
    if not ids:
        return {}
    n = len(ids)
    places = 3 if n >= 8 else (2 if n >= 4 else 1)
    s = sum(px)
    scale = float(places) / s if s > 0 else 1.0
    return {i: max(0.005, min(0.90, p * scale)) for i, p in zip(ids, px, strict=False)}


def _kelly_fraction(p: float, odds: float) -> float:
    """Kelly pour pari binaire avec cote décimale 'odds' (incluant la mise)."""
    b = max(1e-6, odds - 1.0)
    return max(0.0, (p * odds - 1.0) / b)


def _round_to(x: float, step: float) -> float:
    return round(max(0.0, x) / step) * step


def allocate_dutching_sp(
    cfg: dict[str, float], runners: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], float]:
    """
    Dutching Simple Placé (GPI v5.1)
    Retourne (tickets, ev_panier) où:
      - tickets = [{num, mise, odds_place, p_place, kelly}]
      - ev_panier = EV par € misé (somme EV / somme mises)
    """
    if not runners:
        return [], 0.0

    budget_total = float(cfg.get("BUDGET_TOTAL", 5.0))
    sp_ratio = float(cfg.get("SP_RATIO", 1.0))  # ex: 0.60 si mix
    budget_sp = max(0.0, min(budget_total, budget_total * sp_ratio))

    kelly_frac_user = float(cfg.get("KELLY_FRACTION", 0.5))
    cap_vol = float(cfg.get("MAX_VOL_PAR_CHEVAL", 0.60))
    step = float(cfg.get("ROUND_TO_SP", 0.10))
    min_stake = float(cfg.get("MIN_STAKE_SP", 0.10))

    # Probabilités implicites normalisées "place"
    p_map = _implied_probs_place_from_odds(runners)

    # Candidats: odds 2.5–7.0, triés par valeur p*odds décroissante (proxy EV)
    cand = []
    for r in runners:
        num = str(r.get("num") or "").strip()
        if not num or num not in p_map:
            continue
        odds = _parse_odds_place(r)
        if odds < 2.5 or odds > 7.0:
            continue
        p = p_map[num]
        val = p * odds
        cand.append((num, odds, p, val, r))
    if not cand:
        # fallback: on prend 2 meilleurs par p*odds sans filtre de cote
        for r in runners:
            num = str(r.get("num") or "").strip()
            if not num or num not in p_map:
                continue
            odds = _parse_odds_place(r)
            p = p_map[num]
            val = p * odds
            cand.append((num, odds, p, val, r))

    cand.sort(key=lambda t: t[3], reverse=True)
    cand = cand[:3]  # GPI v5.1 → 2–3 chevaux

    # Kelly théorique puis Kelly effectif (fraction utilisateur + cap volatilité)
    stakes = []
    for num, odds, p, _, r in cand:
        k_theo = _kelly_fraction(p, odds)  # 0..1
        k_eff = min(cap_vol, k_theo * kelly_frac_user)  # cap 60% par cheval
        stakes.append((num, odds, p, k_eff, r))

    # Normalisation au budget SP
    s_k = sum(max(1e-9, k) for _, _, _, k, _ in stakes)
    tickets: list[dict[str, Any]] = []
    remaining = budget_sp
    for num, odds, p, k, r in stakes:
        raw = budget_sp * (k / s_k) if s_k > 0 else budget_sp / max(1, len(stakes))
        mise = _round_to(raw, step)
        if mise < min_stake:
            continue
        remaining -= mise
        tickets.append(
            {
                "num": num,
                "mise": round(mise, 2),
                "odds_place": odds,
                "p_place": round(p, 4),
                "kelly": round(k, 4),
            }
        )

    # Si on a perdu trop à l'arrondi, réinjecte le reliquat sur le meilleur cheval
    if remaining >= min_stake and tickets:
        tickets[0]["mise"] = round(_round_to(tickets[0]["mise"] + remaining, step), 2)
        remaining = 0.0

    total_stake = sum(t["mise"] for t in tickets)
    if total_stake <= 0:
        return [], 0.0

    # EV par ticket: p*(odds-1) - (1-p)
    ev_sum = 0.0
    for t in tickets:
        p = float(t["p_place"])
        odds = float(t["odds_place"])
        ev_per_euro = p * (odds - 1.0) - (1.0 - p)
        ev_sum += ev_per_euro * float(t["mise"])

    ev_panier = ev_sum / total_stake  # EV par € misé
    return tickets, ev_panier


# Aliases possibles si ton code legacy appelle d'autres noms
try:
    compute_dutching_sp  # existant ?
except NameError:

    def compute_dutching_sp(cfg, runners):
        return allocate_dutching_sp(cfg, runners)
