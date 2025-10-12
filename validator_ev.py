from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple

# --- Seuils GPI v5.1 / Projet (cap dur) ---
BUDGET_CAP_EUR: float = 5.0          # budget total par course
EV_MIN_COMBO: float = 0.40           # EV minimale pour autoriser un combiné
PAYOUT_MIN_COMBO_EUR: float = 10.0   # payout attendu minimal pour jouer un combiné
MAX_VOL_PER_HORSE: float = 0.60      # cap de volatilité par cheval (SP dutching)
OVERROUND_PLACE_MAX: float = 1.30    # seuil générique place
OVERROUND_PLACE_MAX_BIG_FLAT: float = 1.25  # optionnel: handicaps plats >14 partants

@dataclass
class GuardrailsDecision:
    allowed: bool
    reason: str

def overround_ok(discipline: str, n_partants: int, overround_place: float) -> GuardrailsDecision:
    """Valide l'overround place selon le profil de course."""
    disc = (discipline or "").lower()
    if "plat" in disc and n_partants >= 15:
        ok = overround_place <= OVERROUND_PLACE_MAX_BIG_FLAT
        return GuardrailsDecision(ok, f"flat15+ cap={OVERROUND_PLACE_MAX_BIG_FLAT:.2f}, ov={overround_place:.3f}")
    ok = overround_place <= OVERROUND_PLACE_MAX
    return GuardrailsDecision(ok, f"generic cap={OVERROUND_PLACE_MAX:.2f}, ov={overround_place:.3f}")

def combos_allowed(ev_combo: float,
                   payout_expected_eur: float,
                   overround_place: float,
                   discipline: str,
                   n_partants: int) -> GuardrailsDecision:
    """Règle d'activation combinés (Trio/ZE4/CP/CG)."""
    if payout_expected_eur < PAYOUT_MIN_COMBO_EUR:
        return GuardrailsDecision(False, f"payout<{PAYOUT_MIN_COMBO_EUR}€ (got {payout_expected_eur:.2f}€)")
    if ev_combo < EV_MIN_COMBO:
        return GuardrailsDecision(False, f"EV<{EV_MIN_COMBO:.2f} (got {ev_combo:.3f})")
    ov = overround_ok(discipline, n_partants, overround_place)
    if not ov.allowed:
        return GuardrailsDecision(False, f"overround KO ({ov.reason})")
    return GuardrailsDecision(True, "ok")

def cap_stakes_kelly(stakes: Dict[str, float],
                     budget_cap: float = BUDGET_CAP_EUR,
                     max_vol_per_horse: float = MAX_VOL_PER_HORSE) -> Dict[str, float]:
    """
    - borne total budget à budget_cap
    - borne chaque cheval à max_vol_per_horse * budget_cap
    - renormalise si nécessaire
    """
    if not stakes:
        return {}
    # cap par cheval
    capped = {k: min(v, max_vol_per_horse * budget_cap) for k, v in stakes.items()}
    total = sum(capped.values())
    if total <= 0.0:
        return {k: 0.0 for k in capped}
    # cap budget total
    scale = min(1.0, budget_cap / total)
    return {k: round(v * scale, 2) for k, v in capped.items()}  # arrondi au centime

def clamp_drift_adjustment(adjust_pct: float, limit: float = 0.15) -> float:
    """Plafonne l'effet du drift/CLV sur p_place à ±limit (15% par défaut)."""
    if adjust_pct > limit:
        return limit
    if adjust_pct < -limit:
        return -limit
    return adjust_pct

def ignore_noise_clv(clv: float, eps: float = 0.02) -> float:
    """Ignore les petits CLV (bruit)."""
    return 0.0 if abs(clv) < eps else clv
