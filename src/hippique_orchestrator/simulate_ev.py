"""Utilities for simple SP dutching and EV simulations."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from .ev_calculator import compute_ev_roi
from .kelly import kelly_fraction
from .simulate_wrapper import simulate_wrapper


def implied_prob(odds: float) -> float:
    """Return the implied probability from decimal odds."""

    try:
        value = float(odds)
    except (TypeError, ValueError):
        return 0.0
    if value <= 1.0 or not math.isfinite(value):
        return 0.0
    return 1.0 / value


def normalize_overround(probs: dict[str, float]) -> dict[str, float]:
    """Normalise a probability dictionary to remove the bookmaker overround."""

    cleaned: dict[str, float] = {}
    total = 0.0
    for key, value in probs.items():
        try:
            prob = float(value)
        except (TypeError, ValueError):
            prob = 0.0
        if not math.isfinite(prob) or prob < 0.0:
            prob = 0.0
        cleaned[key] = prob
        total += prob
    if total <= 0.0:
        return {key: 0.0 for key in cleaned}
    return {key: prob / total for key, prob in cleaned.items()}


def implied_probs(odds_list: Sequence[float]) -> list[float]:
    """Return normalised implied probabilities from decimal ``odds_list``."""

    raw = {str(index): implied_prob(odds) for index, odds in enumerate(odds_list)}
    normalised = normalize_overround(raw)
    return [normalised[str(index)] for index in range(len(odds_list))]


def allocate_dutching_sp(
    cfg: dict[str, float], runners: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], float]:
    """Allocate SP dutching stakes according to a Kelly share with 60% cap.

    When each ``runner`` provides an estimated win probability ``p``, those
    probabilities are used directly.  Otherwise, probabilities are inferred
    from decimal ``odds`` via :func:`implied_probs`.
    """

    if not runners:
        return [], 0.0

    odds: list[float] = []
    direct_probs: dict[str, float] = {}
    fallback_probs: dict[str, float] = {}
    ordered_keys: list[str] = []

    for index, runner in enumerate(runners):
        key = str(runner.get("id", index))
        ordered_keys.append(key)
        try:
            odds_value = float(runner.get("odds", 0.0))
        except (TypeError, ValueError):
            odds_value = 0.0
        if not math.isfinite(odds_value) or odds_value <= 1.0:
            odds_value = 0.0
        odds.append(odds_value)

        prob_primary = runner.get("p")
        if prob_primary is None:
            prob_primary = runner.get("p_true")
        prob_value: float | None
        try:
            prob_value = float(prob_primary) if prob_primary is not None else None
        except (TypeError, ValueError):
            prob_value = None
        if prob_value is not None and (
            not math.isfinite(prob_value) or prob_value <= 0.0 or prob_value >= 1.0
        ):
            prob_value = None

        if prob_value is not None:
            direct_probs[key] = prob_value
            continue

        fallback_source = runner.get("p_imp_h5", runner.get("p_imp"))
        try:
            fallback_value = float(fallback_source) if fallback_source is not None else None
        except (TypeError, ValueError):
            fallback_value = None
        if fallback_value is None or not math.isfinite(fallback_value) or fallback_value <= 0.0:
            fallback_value = implied_prob(odds_value) if odds_value > 0 else 0.0
        fallback_probs[key] = fallback_value

    combined_probs: dict[str, float] = {}
    if direct_probs and not fallback_probs:
        total_direct = sum(direct_probs.values())
        if total_direct > 1.0:
            scale = 1.0 / total_direct
            combined_probs = {key: value * scale for key, value in direct_probs.items()}
        else:
            combined_probs = dict(direct_probs)
    elif not direct_probs and fallback_probs:
        combined_probs = normalize_overround(fallback_probs)
    else:
        combined_probs = dict(direct_probs)
        total_direct = sum(direct_probs.values())
        if total_direct >= 1.0 or not fallback_probs:
            for key in fallback_probs:
                combined_probs.setdefault(key, 0.0)
        else:
            remaining = max(0.0, 1.0 - total_direct)
            normalised_fallback = normalize_overround(fallback_probs)
            for key, value in normalised_fallback.items():
                combined_probs[key] = value * remaining

    probs = [combined_probs.get(key, 0.0) for key in ordered_keys]
    budget = float(cfg.get("BUDGET_TOTAL", 0.0)) * float(cfg.get("SP_RATIO", 1.0))
    cap = float(cfg.get("MAX_VOL_PAR_CHEVAL", 0.60))

    valid: list[tuple[dict[str, Any], float, float]] = []
    total_kelly = 0.0
    for runner, p, o in zip(runners, probs, odds, strict=False):
        if not (0.0 < p < 1.0) or o <= 1.0:
            continue
        k = kelly_fraction(p, o, lam=1.0, cap=1.0)
        total_kelly += k
        valid.append((runner, p, o))
    if not valid:
        return [], 0.0
    total_kelly = total_kelly or 1.0
    kelly_coef = float(cfg.get("KELLY_FRACTION", 0.5))
    raw_total = budget * kelly_coef
    step = float(cfg.get("ROUND_TO_SP", 0.10))
    min_stake = float(cfg.get("MIN_STAKE_SP", 0.1))
    rounding_enabled = step > 0

    tickets: list[dict[str, Any]] = []
    ev_sp = 0.0
    for runner, p, o in valid:
        frac = kelly_fraction(p, o, lam=kelly_coef / total_kelly, cap=1.0)
        raw_stake = budget * frac
        cap_value = budget * cap
        raw_stake = min(raw_stake, cap_value)
        if rounding_enabled:
            stake = round(raw_stake / step) * step
            stake = min(stake, cap_value)
        else:
            stake = raw_stake
        if stake <= 0 or stake < min_stake:
            continue
        ev_ticket = stake * (p * (o - 1.0) - (1.0 - p))
        ticket = {
            "type": "SP",
            "id": runner.get("id"),
            "name": runner.get("name", runner.get("id")),
            "odds": o,
            "stake": stake,
            "p": p,
            "ev_ticket": ev_ticket,
        }
        tickets.append(ticket)

    if tickets:
        total_stake = sum(t["stake"] for t in tickets)
        if rounding_enabled:
            diff = round((raw_total - total_stake) / step) * step
        else:
            diff = raw_total - total_stake
        if abs(diff) > 1e-9:
            best = max(tickets, key=lambda t: t["ev_ticket"])
            target_stake = best["stake"] + diff
            if rounding_enabled:
                target_stake = round(target_stake / step) * step
            new_stake = max(0.0, min(target_stake, budget * cap))
            if new_stake >= min_stake - 1e-9:
                best["stake"] = new_stake
                best["ev_ticket"] = new_stake * (
                    best["p"] * (best["odds"] - 1.0) - (1.0 - best["p"])
                )
            else:
                tickets.remove(best)
        ev_sp = sum(t["ev_ticket"] for t in tickets)
    else:
        ev_sp = 0.0
    return tickets, ev_sp


def gate_ev(
    cfg: dict[str, float],
    ev_sp: float,
    ev_global: float,
    roi_sp: float,
    roi_global: float,
    min_payout_combos: float,
    risk_of_ruin: float = 0.0,
    ev_over_std: float = 0.0,
    homogeneous_field: bool = False,
) -> dict[str, Any]:
    """Return activation flags and failure reasons for SP and combinés.

    When ``homogeneous_field`` is true the SP EV threshold falls back to
    ``EV_MIN_SP_HOMOGENEOUS`` when provided in the configuration.
    """

    reasons = {"sp": [], "combo": []}

    sp_budget = float(cfg.get("BUDGET_TOTAL", 0.0)) * float(cfg.get("SP_RATIO", 1.0))

    ev_min_sp_ratio = float(cfg.get("EV_MIN_SP", 0.0))
    if homogeneous_field:
        ev_min_sp_ratio = float(cfg.get("EV_MIN_SP_HOMOGENEOUS", ev_min_sp_ratio))

    if ev_sp < ev_min_sp_ratio * sp_budget:
        reasons["sp"].append("EV_MIN_SP")
    if roi_sp < float(cfg.get("ROI_MIN_SP", 0.0)):
        reasons["sp"].append("ROI_MIN_SP")

    if ev_global < float(cfg.get("EV_MIN_GLOBAL", 0.0)) * float(cfg.get("BUDGET_TOTAL", 0.0)):
        reasons["combo"].append("EV_MIN_GLOBAL")
    if roi_global < float(cfg.get("ROI_MIN_GLOBAL", 0.0)):
        reasons["combo"].append("ROI_MIN_GLOBAL")
    if min_payout_combos < float(cfg.get("MIN_PAYOUT_COMBOS", 0.0)):
        reasons["combo"].append("MIN_PAYOUT_COMBOS")

    ror_max = float(cfg.get("ROR_MAX", 1.0))
    epsilon = 1e-9
    if risk_of_ruin > ror_max + epsilon:
        reasons["sp"].append("ROR_MAX")
        reasons["combo"].append("ROR_MAX")

    sharpe_min = float(cfg.get("SHARPE_MIN", 0.0))
    if ev_over_std < sharpe_min:
        reasons["sp"].append("SHARPE_MIN")
        reasons["combo"].append("SHARPE_MIN")

    sp_ok = not reasons["sp"]
    combo_ok = not reasons["combo"]

    return {"sp": sp_ok, "combo": combo_ok, "reasons": reasons}


def simulate_ev_batch(
    tickets: list[dict[str, Any]],
    bankroll: float,
    *,
    kelly_cap: float | None = None,
    optimize: bool = False,
) -> dict[str, Any]:
    """Return EV/ROI statistics for ``tickets`` given a ``bankroll``.

    This is a thin wrapper around :func:`compute_ev_roi` that also hooks into
    :func:`simulate_wrapper` to estimate probabilities of combined bets.
    """
    kwargs: dict[str, Any] = {}
    if kelly_cap is not None:
        kwargs["kelly_cap"] = kelly_cap
    if optimize:
        kwargs["optimize"] = True
    stats = compute_ev_roi(
        tickets,
        budget=bankroll,
        simulate_fn=simulate_wrapper,
        **kwargs,
    )
    stats.setdefault("sharpe", stats.get("ev_over_std", 0.0))
    if "calibrated_expected_payout" not in stats:
        stats["calibrated_expected_payout"] = sum(
            float(ticket.get("expected_payout", 0.0)) for ticket in tickets
        )
    return stats


# === COMPATIBILITÉ LEGACY (aliases & helpers attendus par d'anciens scripts) ===
# À coller tout en bas de simulate_ev.py, après simulate_ev_batch(...)


def implied_probs_place_from_odds(runners: list[dict[str, Any]]) -> dict[str, float]:
    """
    Construit des probabilités 'place' implicites à partir des cotes.
    Cherche dans l'ordre: odds_place, cote_place, odds, cote.
    Normalise ensuite au nb de places (3 si >=8 partants, 2 si 4-7, sinon 1).
    """
    ids, px = [], []
    for r in runners:
        num = str(r.get("num") or r.get("id") or "")
        if not num:
            continue
        odds = None
        for k in ("odds_place", "cote_place", "odds", "cote"):
            v = r.get(k)
            if v is not None:
                try:
                    odds = float(str(v).replace(",", "."))
                    break
                except Exception:
                    pass
        if odds is None or odds <= 1.0:
            # fallback prudente si cote manquante: ~25% avant renormalisation
            odds = 4.0
        # borne 1%–90% avant renormalisation
        p = max(0.01, min(0.90, 1.0 / odds))
        ids.append(num)
        px.append(p)

    if not ids:
        return {}

    n = len(ids)
    places = 3 if n >= 8 else (2 if n >= 4 else 1)
    s = sum(px)
    scale = float(places) / s if s > 0 else 1.0
    return {i: max(0.005, min(0.90, p * scale)) for i, p in zip(ids, px, strict=False)}


# -- Aliases historiques pour éviter les ImportError sur vieux scripts ---------

# compute_ev était importé depuis simulate_ev; redirige vers compute_ev_roi
try:
    compute_ev  # type: ignore[name-defined]
except NameError:
    def compute_ev(*args, **kwargs):
        # Réutilise la fonction déjà importée en tête du fichier
        return compute_ev_roi(*args, **kwargs)

# ev_sp anciennement attendu: renvoie tickets SP + EV du panier SP
try:
    ev_sp  # type: ignore[name-defined]
except NameError:
    def ev_sp(cfg: dict[str, float], runners: list[dict[str, Any]]):
        """
        Interface de compat:
        - input: cfg (budget/ratios) + runners
        - output: dict { 'tickets': [...], 'ev_sp': float }
        """
        tickets, ev = allocate_dutching_sp(cfg, runners)
        return {"tickets": tickets, "ev_sp": ev}

# cp_ev et estimate_payout: stubs raisonnables si appelés par du legacy
try:
    cp_ev  # type: ignore[name-defined]
except NameError:
    def cp_ev(*args, **kwargs):
        # À remplacer par ton calcul réel si nécessaire
        return {"ev": 0.0, "roi": 0.0, "ok": False}

try:
    estimate_payout  # type: ignore[name-defined]
except NameError:
    def estimate_payout(*args, **kwargs) -> float:
        # Valeur par défaut conservatrice; mets ta calibration réelle si dispo
        return 10.0
