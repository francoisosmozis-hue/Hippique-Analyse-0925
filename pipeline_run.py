
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline_run.py — GPI v5.1 (cap 5 €)
Chaîne de décision complète (EV + budget + Kelly cap 60 %) intégrée.
Utilisation:
  python pipeline_run.py --budget 5 --ttl-seconds 21600 --candidates data/cands.json
  python pipeline_run.py --reunion R1 --course C3 --date 2025-09-07  # (nécessite un générateur réel)
Sorties:
  - Affiche la décision (tickets + stakes) ou l'abstention motivée.
  - Optionnel: écrit un JSON d'analyse si --analysis-out est précisé.
"""

from __future__ import annotations
import json
import sys
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

# === Imports du projet (déjà livrés dans l'environnement) ===
from simulate_wrapper import simulate_tickets_ev
from selection_utils import select_best_two, allocate_kelly_capped

# === Constantes verrouillées (projet) ===
BUDGET_CAP_EUR = 5.0
EV_MIN_COMBO = 0.40        # +40 % requis pour combinés
ROI_MIN_SP = 0.20          # +20 % mini pour panier SP
PAYOUT_MIN_COMBO = 10.0    # € attendu min pour autoriser un combiné
SP_SHARE, COMBO_SHARE = 0.60, 0.40
MAX_VOL_PER_HORSE = 0.60
MAX_TICKETS = 2

def _filter_ev(cands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ok = []
    for t in cands:
        kind = (t.get("type") or "").upper()
        ev = float(t.get("ev", 0.0))
        payout = float(t.get("expected_payout", 0.0))
        if kind == "SP":
            if ev >= ROI_MIN_SP:
                ok.append(t)
        else:
            if ev >= EV_MIN_COMBO and payout >= PAYOUT_MIN_COMBO:
                ok.append(t)

# Hiérarchie combinés : CP > TRIO > ZE4
if ok:
    cp = [t for t in ok if (t.get("type") or "").upper() in ("CP","COUPLE","COUPLE_PLACE")]
    trio = [t for t in ok if (t.get("type") or "").upper() == "TRIO"]
    ze4 = [t for t in ok if (t.get("type") or "").upper() in ("ZE4","ZE234")]
    if cp:
        return cp + [t for t in ok if t not in cp]
    elif trio:
        return trio + [t for t in ok if t not in trio]
    elif ze4:
        return ze4 + [t for t in ok if t not in ze4]
return ok


def decide_tickets(inputs: Dict[str, Any], candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    inputs: dict global (peut contenir 'market', 'calibration_path', etc.)
    candidates: tickets bruts (id, type, legs...)
    return: {'tickets': [...], 'stakes': [...], 'abstention': bool, 'reason': str|None}
    """
    market = inputs.get("market")
    calibration_path = inputs.get("calibration_path", "payout_calibration.yaml")

    # 1) Simulation EV/payout
    scored = simulate_tickets_ev(candidates, market=market, calibration_path=calibration_path)

    # 2) Filtre EV/payout
    filtered = _filter_ev(scored)
    if not filtered:
        return {"tickets": [], "stakes": [], "abstention": True, "reason": "EV global insuffisant ou payout combiné < 10€"}

    # 3) Sélection finale max 2
    final = select_best_two(filtered)

    # 4) Allocation mises (Kelly cap + split SP/Combinés)
    stakes = allocate_kelly_capped(final, budget_cap=BUDGET_CAP_EUR, sp_share=SP_SHARE,
                                   combo_share=COMBO_SHARE, cap_per_leg=MAX_VOL_PER_HORSE)

    # 5) Sanity check budget
    total = round(sum(s.get("stake_eur", 0.0) for s in stakes), 2)
    if total <= 0.0:
        return {"tickets": [], "stakes": [], "abstention": True, "reason": "Budget effectif nul après allocation"}
    if total > BUDGET_CAP_EUR + 1e-9:
        ratio = BUDGET_CAP_EUR / total
        for s in stakes:
            s["stake_eur"] = round(s["stake_eur"] * ratio, 2)

    return {"tickets": final, "stakes": stakes,
        "reporting": reporting, "abstention": False, "reason": None}


# === Génération combinés GPI (favori + régulier + outsider/profil oublié) ===

def _try_pfinale_shortlist(inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Essaie d'obtenir une shortlist ordonnée depuis p_finale_export.py si disponible.
    On tente plusieurs noms de fonctions courants, sinon None/[].
    Retour attendu par cheval minimal: {"horse": "7", "p_place": 0.40, "odds_place": 3.5, "form": "3a-2a-4a", "cote_sp": 5.2}
    """
    try:
        import p_finale_export as pfinale
    except Exception:
        return []
    funcs = [
        "get_shortlist",
        "generate_shortlist",
        "rank_horses",
        "export_shortlist",
    ]
    for fn in funcs:
        f = getattr(pfinale, fn, None)
        if callable(f):
            try:
                res = f(inputs)  # tolère signature dict
                if isinstance(res, list) and res:
                    return res
            except Exception:
                continue
    return []

def _is_outsider_value(h: Dict[str, Any]) -> bool:
    # Outsider régulier: cote >= 8/1 et 2 dernières musiques ≤ 3e
    cote = float(h.get("cote_sp", h.get("odds_win", 0.0)) or 0.0)
    music = str(h.get("form", ""))
    last = [s.strip() for s in re.split(r"[-\s/]", music) if s.strip()]
    top2 = last[:2]
    def _rank_ok(x: str) -> bool:
        try:
            # accepte formats "1a", "2p", "3" etc.
            m = re.match(r"(\d+)", x)
            if not m: return False
            return int(m.group(1)) <= 3
        except Exception:
            return False
    cond_form = (len(top2) >= 2) and all(_rank_ok(x) for x in top2)
    return (cote >= 8.0) and cond_form

def _is_profil_oublie(h: Dict[str, Any]) -> bool:
    # Profil "oublié": régulier (≤4e sur 3 dernières) et peu cité (proxy: flag 'not_cited' ou odds ≥ 12)
    music = str(h.get("form", ""))
    parts = [s.strip() for s in re.split(r"[-\s/]", music) if s.strip()][:3]
    regular = True
    for x in parts:
        m = re.match(r"(\d+)", x or "")
        if not (m and int(m.group(1)) <= 4):
            regular = False
            break
    not_cited = bool(h.get("not_cited", False)) or float(h.get("cote_sp", h.get("odds_win", 0.0)) or 0.0) >= 12.0
    return regular and not_cited

def _pick_base_regular(shortlist: List[Dict[str, Any]]) -> Dict[str, Any]:
    # Choisit un favori régulier (score = p_place*(odds_place-1) avec bonus J/E s'il existe)
    def score(h):
        p = float(h.get("p_place", h.get("p", 0.0)) or 0.0)
        od = float(h.get("odds_place", h.get("odds", 1.0)) or 1.0)
        je_bonus = 0.02 if (h.get("j_rate", 0.0) >= 0.12 or h.get("e_rate", 0.0) >= 0.15) else 0.0
        return p * max(od-1.0, 0.0) + je_bonus
    return max(shortlist, key=score)

def _build_combo_from_shortlist(shortlist: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Construit jusqu'à 2 tickets:
      - SP Dutching sur 2-3 chevaux (top value)
      - 1 combiné (CP ou Trio) : base = favori régulier + 1 régulier + 1 outsider/profil oublié
    """
    if not shortlist:
        return []
    # Normaliser champs minimaux
    norm = []
    for h in shortlist:
        norm.append({
            "horse": str(h.get("horse") or h.get("num") or ""),
            "p_place": float(h.get("p_place", h.get("p", 0.0)) or 0.0),
            "odds_place": float(h.get("odds_place", h.get("odds", 1.0)) or 1.0),
            "form": h.get("form", ""),
            "cote_sp": float(h.get("cote_sp", h.get("odds_win", 0.0)) or 0.0),
            "j_rate": float(h.get("j_rate", 0.0) or 0.0),
            "e_rate": float(h.get("e_rate", 0.0) or 0.0),
            "not_cited": bool(h.get("not_cited", False))
        })
    # SP Dutching: top 2-3 par p*(odds-1)
    sp_legs = sorted(norm, key=lambda x: x["p_place"] * max(x["odds_place"]-1.0, 0.0), reverse=True)[:3]
    sp_ticket = {"id": "SP1", "type": "SP", "meta": {"label": "Dutching SP (GPI v5.1)", "source": "p_finale"}, "legs": [
        {"horse": h["horse"], "p": h["p_place"], "odds": h["odds_place"]} for h in sp_legs
    ]}
    # Combiné: base favori régulier + régulier silencieux + outsider/profil oublié
    base = _pick_base_regular(norm)
    # régulier silencieux (non base) = régulier sans cote très basse (<2.5)
    regs = [h for h in norm if h["horse"] != base["horse"]]
    regs = [h for h in regs if h["p_place"] >= 0.25 and h["odds_place"] >= 2.0]
    regs = sorted(regs, key=lambda x: x["p_place"], reverse=True)
    # outsider value / profil oublié
    outs = [h for h in norm if h["horse"] != base["horse"] and (_is_outsider_value(h) or _is_profil_oublie(h))]
    # fallback outsider plus simple si rien détecté
    if not outs:
        outs = sorted([h for h in norm if h["horse"] != base["horse"]], key=lambda x: (x["odds_place"], x["p_place"]), reverse=True)
    combo = None
    if regs:
        cand = [base, regs[0]]
        # ajouter outsider si possible
        if outs:
            cand.append(outs[0])
        else:
            # sinon top régulier suivant
            if len(regs) > 1:
                cand.append(regs[1])
        # priorité CP si 2 chevaux, sinon Trio si 3
        if len(cand) >= 3:
            combo = {"id": "TR1", "type": "TRIO", "meta": {"label": "Trio (base+régulier+value)", "source": "p_finale"},
                     "legs": [x["horse"] for x in cand[:3]]}
        else:
            combo = {"id": "CP1", "type": "CP", "meta": {"label": "Couplé Placé (base+reg)", "source": "p_finale"},
                     "legs": [x["horse"] for x in cand[:2]]}
    tickets = [sp_ticket]
    if combo:
        tickets.append(combo)
    return tickets

# === Génération des candidats ===============================================

def generate_candidates_gpi_v51(inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Générateur de candidats (SP + max 1 combiné). Ordre de préférence :
      A) Shortlist de p_finale_export (favori + régulier + outsider/profil oublié)
      B) --candidates <json> fournis
      C) --hints <json> → Dutching SP + Trio minimal
    """
    # A) p_finale_export → shortlist intelligente si dispo
    shortlist = _try_pfinale_shortlist(inputs)
    if shortlist:
        built = _build_combo_from_shortlist(shortlist)
        if built:
            return built

    # 1) Si fichier de candidats fourni
    """
    Générateur de candidats (SP + max 1 combiné). Trois voies possibles:
      1) --candidates <json> : charge les candidats fournis (recommandé pour tests).
      2) --hints <json> : liste de chevaux {horse, p_place, odds_place, ...} -> construit un Dutching SP.
      3) Placeholder vide → aucune proposition (abstention ensuite).
    """
    # 1) Si fichier de candidats fourni
    cpath = inputs.get("candidates_path")
    if cpath:
        p = Path(cpath)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and "candidates" in data:
                    return list(data["candidates"])
            except Exception as e:
                print(f"[WARN] Échec lecture candidats JSON: {e}", file=sys.stderr)

    # 2) Si hints (liste chevaux) → construire un Dutching SP + 1 combiné simple (optionnel)
    hints_path = inputs.get("hints_path")
    if hints_path:
        hp = Path(hints_path)
        if hp.exists():
            try:
                hints = json.loads(hp.read_text(encoding="utf-8"))
                if isinstance(hints, list) and len(hints) >= 2:
                    # Construit un ticket SP: 2-3 chevaux top p_place*value
                    legs_sp = []
                    for h in hints:
                        legs_sp.append({
                            "horse": str(h.get("horse")),
                            "p": float(h.get("p_place", h.get("p", 0.0))),
                            "odds": float(h.get("odds_place", h.get("odds", 1.0))),
                            "market": "place"
                        })
                    # tri par score simple
                    legs_sp = sorted(legs_sp, key=lambda x: x["p"]*(x["odds"]-1.0), reverse=True)[:3]
                    sp_ticket = {"id": "SP1", "type": "SP", "legs": legs_sp, "meta": {"label": "Dutching SP", "source": "GPI v5.1"}}
                    # Option combiné minimal si ≥3 legs disponibles
                    cmb = []
                    if len(legs_sp) >= 3:
                        cmb = [{"id": "TR1", "type": "TRIO", "legs": legs_sp[:3], "meta": {"label": "Trio base 3", "source": "GPI v5.1"}}]
                    return [sp_ticket] + cmb
            except Exception as e:
                print(f"[WARN] Échec lecture hints JSON: {e}", file=sys.stderr)
    # 3) Aucun candidat par défaut
    return []


# === Reporting EV/ROI (sécurisé) ============================================

def _compute_ticket_stake(stakes, ticket_id):
    return round(sum(s.get("stake_eur", 0.0) for s in stakes if s.get("ticket_id") == ticket_id), 2)

def _report_tickets(tickets: List[Dict[str, Any]], stakes: List[Dict[str, Any]]) -> Dict[str, Any]:
    details = []
    total_stake = round(sum(s.get("stake_eur", 0.0) for s in stakes), 2)
    ev_total = 0.0
    gross_ret_total = 0.0
    for t in tickets:
        tid = t.get("id")
        typ = (t.get("type") or "").upper()
        stake = _compute_ticket_stake(stakes, tid)
        # ev_ratio est le gain net par € misé (moyenne) — compat ascendante via 'ev'
        ev_ratio = t.get("ev_ratio", t.get("ev", 0.0))
        try:
            ev_ratio = float(ev_ratio)
        except Exception:
            ev_ratio = 0.0
        ev_eur = round(stake * ev_ratio, 4)
        gross_expected = round(stake + ev_eur, 4)  # retour brut attendu
        ev_total += ev_eur
        gross_ret_total += gross_expected
        d = {
            "ticket_id": tid,
            "type": typ,
            "stake_eur": stake,
            "ev_ratio": round(ev_ratio, 6),
            "ev_eur": ev_eur,
            "expected_gross_return_eur": gross_expected,
        }
        # SP: tenter un détail par legs
        if typ == "SP":
            legs = t.get("legs", [])
            # map stakes per leg
            leg_stakes = {}
            for s in stakes:
                if s.get("ticket_id") == tid and s.get("horse"):
                    leg_stakes[str(s.get("horse"))] = leg_stakes.get(str(s.get("horse")), 0.0) + float(s.get("stake_eur", 0.0))
            legs_rep = []
            for lg in legs:
                num = str(lg.get("horse") or lg.get("num") or "")
                p = float(lg.get("p", 0.0) or 0.0)
                od = float(lg.get("odds", 1.0) or 1.0)
                stake_leg = round(leg_stakes.get(num, 0.0), 2)
                # EV par euro unitaire = p*(od-1) - (1-p)
                ev_leg_ratio = p * max(od-1.0, 0.0) - (1.0 - p)
                ev_leg_eur = round(stake_leg * ev_leg_ratio, 4)
                legs_rep.append({
                    "horse": num,
                    "stake_eur": stake_leg,
                    "p_place": round(p, 4),
                    "odds_place": round(od, 4),
                    "ev_ratio": round(ev_leg_ratio, 6),
                    "ev_eur": ev_leg_eur
                })
            d["legs"] = legs_rep
        details.append(d)
    roi_est = round(ev_total / total_stake, 6) if total_stake > 0 else None
    return {
        "total_stake_eur": total_stake,
        "ev_total_eur": round(ev_total, 4),
        "roi_estimated": roi_est,
        "expected_gross_return_eur": round(gross_ret_total, 4),
        "tickets": details
    }

# === I/O & sortie ===========================================================

def output_tickets(tickets: List[Dict[str, Any]], stakes: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = {
        "status": "OK",
        "tickets": tickets,
        "stakes": stakes,
        "reporting": reporting,
        "budget_cap_eur": BUDGET_CAP_EUR,
        "rules": {
            "ev_min_combo": EV_MIN_COMBO,
            "roi_min_sp": ROI_MIN_SP,
            "payout_min_combo": PAYOUT_MIN_COMBO,
            "sp_share": SP_SHARE,
            "combo_share": COMBO_SHARE,
            "max_vol_per_horse": MAX_VOL_PER_HORSE,
            "max_tickets": MAX_TICKETS
        }
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return out

def output_abstention(reason: str) -> Dict[str, Any]:
    out = {"status": "ABSTAIN", "reason": reason}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return out

def write_analysis_json(analysis_path: Path, meta: Dict[str, Any], decision: Dict[str, Any]):
    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "meta": meta,
        "decision": decision
    }
    analysis_path.parent.mkdir(parents=True, exist_ok=True)
    analysis_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[INFO] Analyse écrite: {analysis_path}")

# === CLI ====================================================================

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pipeline GPI v5.1 — Décision EV + Kelly (budget 5€).")
    p.add_argument("--reunion", type=str, help="R1/R2/...", default=None)
    p.add_argument("--course", type=str, help="C1/C2/...", default=None)
    p.add_argument("--date", type=str, help="YYYY-MM-DD", default=None)
    p.add_argument("--url", type=str, help="URL ZEturf/Geny (optionnel)", default=None)
    p.add_argument("--ttl-seconds", type=int, default=21600, help="TTL du cache (par défaut 6h)")
    p.add_argument("--budget", type=float, default=5.0, help="Budget cap course (5€ par défaut)")
    p.add_argument("--market", type=str, default=None, help="Marché (ex: 'FR') pour simulateur")
    p.add_argument("--calibration-path", type=str, default="payout_calibration.yaml", help="Calibration payouts")
    p.add_argument("--candidates", dest="candidates_path", type=str, default=None, help="Chemin JSON candidats")
    p.add_argument("--hints", dest="hints_path", type=str, default=None, help="Chemin JSON hints chevaux")
    p.add_argument("--analysis-out", type=str, default=None, help="Chemin JSON d'analyse à écrire")
    return p.parse_args(argv)

def main(argv: Optional[List[str]] = None):
    args = parse_args(argv)
    # Noter que BUDGET_CAP_EUR est verrouillé à 5€ pour le projet — on ignore --budget pour la décision
    inputs: Dict[str, Any] = {
        "reunion": args.reunion,
        "course": args.course,
        "date": args.date,
        "url": args.url,
        "market": args.market,
        "calibration_path": args.calibration_path,
        "ttl_seconds": int(args.ttl_seconds),
        "candidates_path": args.candidates_path,
        "hints_path": args.hints_path
    }

    # Générer candidats
    candidates = generate_candidates_gpi_v51(inputs)
    if not candidates:
        decision = {"tickets": [], "stakes": [], "abstention": True, "reason": "Aucun candidat généré"}
        if args.analysis_out:
            write_analysis_json(Path(args.analysis_out), meta=vars(args), decision=decision)
        return output_abstention(decision["reason"])

    # Décider
    decision = decide_tickets(inputs, candidates)
    if args.analysis_out:
        write_analysis_json(Path(args.analysis_out), meta=vars(args), decision=decision)

    if decision.get("abstention"):
        return output_abstention(decision.get("reason") or "Non jouable selon filtres EV/payout")
    else:
        return output_tickets(decision["tickets"], decision["stakes"])

if __name__ == "__main__":
    sys.exit(0 if main() else 0)
