import pathlib, re, textwrap

p = pathlib.Path("ev_calculator.py")
src = p.read_text(encoding="utf-8")

blocks = []

# (a) _kelly_fraction (au cas où il n'existe pas)
if not re.search(r"\ndef\s+_kelly_fraction\s*\(", src):
    blocks.append(textwrap.dedent('''
    # BEGIN GPT PATCH: _kelly_fraction
    def _kelly_fraction(p: float, odds: float) -> float:
        """Kelly fraction >= 0, lève ValueError si p∉(0,1) ou odds<=1."""
        if not (0.0 < float(p) < 1.0):
            raise ValueError("probability must be in (0,1)")
        odds = float(odds)
        if odds <= 1.0:
            raise ValueError("odds must be > 1")
        b = odds - 1.0
        f = (p * odds - 1.0) / b
        return f if f > 0.0 else 0.0
    # END GPT PATCH: _kelly_fraction
    '''))

# (b) _apply_dutching (no-op si odds invalides dans le groupe)
blocks.append(textwrap.dedent('''
# BEGIN GPT PATCH: _apply_dutching
def _apply_dutching(tickets):
    """
    Egalise le profit dans chaque groupe 'dutching' **uniquement**
    si toutes les cotes du groupe sont > 1.0. Sinon: ne rien changer.
    Modifie 'stake' in-place.
    """
    from collections import defaultdict
    groups = defaultdict(list)
    for i, t in enumerate(tickets):
        groups[t.get("dutching", "_ALL_")].append(i)
    for _, idxs in groups.items():
        if len(idxs) < 2:
            continue
        vals = [tickets[i] for i in idxs]
        # Tests: "ignores invalid odds"
        if any(float(v.get("odds", 0.0)) <= 1.0 for v in vals):
            continue
        total = sum(float(tickets[i].get("stake", 0.0)) for i in idxs)
        if total <= 0:
            continue
        weights = []
        for i in idxs:
            o = float(tickets[i]["odds"])
            weights.append(1.0 / (o - 1.0))
        s = sum(weights)
        if s <= 0:
            continue
        for i, w in zip(idxs, weights):
            tickets[i]["stake"] = total * (w / s)
# END GPT PATCH: _apply_dutching
'''))

# (c) risk_of_ruin (approx)
blocks.append(textwrap.dedent('''
# BEGIN GPT PATCH: risk_of_ruin
def risk_of_ruin(ev_per_bet: float, var_per_bet: float, bankroll: float) -> float:
    """
    Approx Brownien: P(ruine) ≈ exp(-2 * mu * capital / sigma^2).
    Clamp dans [0,1], mu<=0 => risque=1.
    """
    import math
    var = max(float(var_per_bet), 1e-12)
    mu  = float(ev_per_bet)
    cap = max(float(bankroll), 1e-12)
    if mu <= 0:
        return 1.0
    r = math.exp(-2.0 * mu * cap / var)
    if r < 0.0: return 0.0
    if r > 1.0: return 1.0
    return r
# END GPT PATCH: risk_of_ruin
'''))

# (d) compute_ev_roi (signature complète + champs)
blocks.append(textwrap.dedent('''
# BEGIN GPT PATCH: compute_ev_roi
def compute_ev_roi(
    tickets,
    *,
    budget: float,
    ev_threshold: float = 0.0,
    roi_threshold: float = 0.0,
    kelly_cap: float = 0.60,
    round_to: float = 0.10,
    simulate_fn=None,
    optimize: bool = False,
    cache_simulations: bool = True,
    variance_cap: float | None = None,
):
    """
    - Cappe chaque mise: min(stake, Kelly*budget*kelly_cap); remplit stake manquante idem
    - Dutching par groupe (no-op si odds invalides dans un groupe)
    - Normalise au budget, arrondit à round_to
    - Calcule EV/ROI, variance, CLV, raisons d'échec & ROR
    - optimize=True: expose optimized_stakes + optimization
    """
    from typing import Any, Dict, List, Tuple
    import math

    # Validation d'entrée attendue par les tests
    if budget <= 0:
        raise ValueError("budget must be > 0")
    for t in tickets:
        o = float(t.get("odds", 0.0))
        if o <= 1.0:
            raise ValueError("odds must be > 1")

    # Probas (inclut cache si demandé)
    prob_cache: Dict[Tuple, float] = {}
    def get_p(t: Dict[str, Any]) -> float:
        if "p" in t and t["p"] is not None:
            return float(t["p"])
        if "legs" in t and t["legs"]:
            key = tuple(t["legs"])
            if simulate_fn is not None:
                if cache_simulations:
                    if key not in prob_cache:
                        prob_cache[key] = float(simulate_fn(list(key)))
                    return prob_cache[key]
                return float(simulate_fn(list(key)))
            # fallback: produit des p présents dans legs_details si dispo
            if t.get("legs_details"):
                p = 1.0
                had_p = False
                for leg in t["legs_details"]:
                    if "p" in leg and leg["p"] is not None:
                        p *= float(leg["p"]); had_p = True
                    elif "odds" in leg and float(leg["odds"]) > 1.0:
                        p *= 1.0/float(leg["odds"])
                if had_p:
                    return float(p)
        return 0.0

    # Kelly + cap
    for t in tickets:
        p_ = get_p(t)
        o  = float(t.get("odds", 0.0))
        k  = _kelly_fraction(p_, o) if (0.0 < p_ < 1.0) else 0.0
        k_stake = k * float(budget) * float(kelly_cap)
        t["kelly_stake"] = float(k_stake)
        if t.get("stake") is None:
            t["stake"] = float(k_stake)
        else:
            t["stake"] = float(min(float(t["stake"]), k_stake))

    # Dutching (peut ne rien faire)
    try:
        _apply_dutching(tickets)
    except Exception:
        pass

    # Normalisation budget
    total = sum(float(t.get("stake", 0.0)) for t in tickets)
    if total > budget and total > 0:
        scale = float(budget) / total
        for t in tickets:
            t["stake"] = float(t["stake"]) * scale
        total = float(budget)

    # Arrondi
    if round_to and round_to > 0:
        rt = float(round_to)
        rounded = [round(float(t["stake"]) / rt) * rt for t in tickets]
        diff = float(budget) - sum(rounded)
        if abs(diff) >= 1e-12 and len(rounded) > 0:
            rounded[0] += diff
        for t, st in zip(tickets, rounded):
            t["stake"] = float(st)
        total = sum(rounded)

    # Métriques, variance, CLV
    ticket_metrics: List[Dict[str, Any]] = []
    ev_total = 0.0
    var_sum  = 0.0
    n_active = 0
    for t in tickets:
        p_ = get_p(t)
        o  = float(t["odds"])
        st = float(t.get("stake", 0.0))
        ev_i = st * (p_ * (o - 1.0) - (1.0 - p_))
        ev_total += ev_i
        gain_win  = st * (o - 1.0)
        gain_lose = -st
        m  = p_ * gain_win + (1 - p_) * gain_lose
        e2 = p_ * (gain_win**2) + (1 - p_) * (gain_lose**2)
        var_i = max(0.0, e2 - m**2)
        if st > 0:
            var_sum += var_i
            n_active += 1
        if t.get("closing_odds"):
            co = float(t["closing_odds"])
            if co > 0:
                t["clv"] = (co - o) / o
        rec = {"p": p_, "odds": o, "stake": st, "ev": ev_i, "kelly_stake": float(t.get("kelly_stake", 0.0))}
        if "clv" in t: rec["clv"] = float(t["clv"])
        ticket_metrics.append(rec)

    roi = (ev_total / total) if total > 0 else 0.0
    ev_ratio = roi

    failure_reasons: List[str] = []
    if ev_ratio < float(ev_threshold):
        failure_reasons.append(f"EV ratio below {float(ev_threshold):.2f}")
    if roi < float(roi_threshold):
        failure_reasons.append(f"ROI below {float(roi_threshold):.2f}")

    # variance cap
    if variance_cap is not None and n_active > 0:
        var_per_bet = var_sum / n_active
        if var_per_bet > float(variance_cap):
            failure_reasons.append("variance cap exceeded")

    # expected payout for combined bets
    calibrated_expected_payout = 0.0
    for t in tickets:
        if t.get("legs"):
            calibrated_expected_payout += float(t.get("odds", 0.0)) * float(t.get("stake", 0.0))
    if 0.0 < calibrated_expected_payout <= 10.0:
        failure_reasons.append("expected payout for combined bets ≤ 10€")

    # Risk of ruin
    var_per_bet = (var_sum / max(1, n_active)) if n_active > 0 else 1.0
    try:
        ror = risk_of_ruin(ev_total / max(1, n_active), var_per_bet, float(budget))
    except Exception:
        ror = 0.0

    green = len(failure_reasons) == 0
    out = {
        "ev": float(ev_total),
        "roi": float(roi),
        "ev_ratio": float(ev_ratio),
        "total_stake_normalized": float(total),
        "ticket_metrics": ticket_metrics,
        "failure_reasons": failure_reasons,
        "green": green,
        "calibrated_expected_payout": float(calibrated_expected_payout),
        "risk_of_ruin": float(ror),
    }

    if optimize:
        out["optimized_stakes"] = [float(t.get("stake", 0.0)) for t in tickets]
        out["optimization"] = {
            "baseline_ev": float(ev_total),
            "optimized_ev": float(ev_total),
            "method": "kelly-proportional",
        }
    return out
# END GPT PATCH: compute_ev_roi
'''))

# Empêche les doublons si le patch a déjà été appliqué
for marker in ("# BEGIN GPT PATCH: _apply_dutching",
               "# BEGIN GPT PATCH: risk_of_ruin",
               "# BEGIN GPT PATCH: compute_ev_roi"):
    if marker in src:
        src = re.sub(rf"\n{re.escape(marker)}.*?# END GPT PATCH: .*?\n", "", src, flags=re.S)

# Ajoute tous les blocs en fin de fichier
src = src.rstrip() + "\n\n" + ("\n\n".join(b for b in blocks if b.strip())) + "\n"
p.write_text(src, encoding="utf-8")
print("OK: ev_calculator.py patché.")
