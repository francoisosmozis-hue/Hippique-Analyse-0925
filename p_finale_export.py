
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
p_finale_export_v2.py — GPI v5.1 (+ Cheval Stats)
-------------------------------------------------
Ajoute des pondérations facultatives basées sur les stats cheval
chargées depuis je_stats.csv (colonnes additionnelles) :
  - h_place5 >= 60%  → ×1.04   (forme courte forte)
  - h_place5 <= 20%  → ×0.96   (forme courte faible)
  - h_place_career >= 50% → ×1.02 (régularité carrière)
  - h_place_career <= 25% → ×0.98 (faible régularité)
Les bonus/malus J/E d'origine sont conservés.

Entrées / sorties identiques à v1, compatible avec v1 si colonnes absentes.
"""

from __future__ import annotations
import argparse, csv, json
from pathlib import Path
from typing import Dict, Any, Optional
import simulate_ev

ALPHA_H5 = 0.65
ALPHA_H30 = 1.0 - ALPHA_H5

# Facteurs d'origine
F_CHRONO_OK = 1.04
F_JE_BONUS  = 1.06
F_JE_MALUS  = 0.94

# Nouveaux facteurs cheval
F_H_SHORT_GOOD = 1.04   # h_place5 >= 60%
F_H_SHORT_BAD  = 0.96   # h_place5 <= 20%
F_H_CAR_GOOD   = 1.02   # h_place_career >= 50%
F_H_CAR_BAD    = 0.98   # h_place_career <= 25%

def load_json(p: Optional[str]) -> Dict[str, Any]:
    if not p: return {}
    path = Path(p)
    if not path.exists(): return {}
    return json.loads(path.read_text(encoding="utf-8"))

def implied_p_place_from_snapshot(snap: Dict[str, Any]) -> Dict[str, float]:
    runners = snap.get("runners", []) or []
    if not runners: return {}
    p_place = simulate_ev.implied_probs_place_from_odds(runners)
    if not p_place:
        ids = [str(r.get("num")) for r in runners if r.get("num") is not None]
        if not ids: return {}
        base = 1.0 / max(1, len(ids))
        return {i: base for i in ids}
    return {str(k): float(v) for k, v in p_place.items()}

def load_chronos(csv_path: Optional[str]) -> Dict[str, int]:
    out = {}
    if not csv_path: return out
    p = Path(csv_path)
    if not p.exists(): return out
    with p.open("r", encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        for row in rd:
            num = str(row.get("num"))
            ok  = row.get("ok")
            if num:
                out[num] = 1 if str(ok).strip() in ("1","true","True","yes","YES") else 0
    return out

def _to_float(x):
    if x is None: return None
    s = str(x).strip().replace(",", ".")
    if s == "": return None
    try: return float(s)
    except Exception: return None

def load_je(csv_path: Optional[str]) -> Dict[str, Dict[str, Optional[float]]]:
    """
    Retourne {num: {"j": j_rate, "e": e_rate, "h_p5":%, "h_w5":%, "h_pc":%, "h_wc":%}}
    Valeurs en % ou None si absentes.
    """
    out = {}
    if not csv_path: return out
    p = Path(csv_path)
    if not p.exists(): return out
    with p.open("r", encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        for row in rd:
            num = str(row.get("num"))
            if not num: continue
            out[num] = {
                "j": _to_float(row.get("j_rate")),
                "e": _to_float(row.get("e_rate")),
                "h_w5": _to_float(row.get("h_win5")),
                "h_p5": _to_float(row.get("h_place5")),
                "h_wc": _to_float(row.get("h_win_career")),
                "h_pc": _to_float(row.get("h_place_career")),
            }
    return out

def je_factor(j: Optional[float], e: Optional[float]) -> float:
    if (j is not None and j >= 12.0) or (e is not None and e >= 15.0):
        return F_JE_BONUS
    if (j is not None and j < 6.0) or (e is not None and e < 8.0):
        return F_JE_MALUS
    return 1.0

def horse_factor(hp5: Optional[float], hpc: Optional[float]) -> float:
    f = 1.0
    if hp5 is not None:
        if hp5 >= 60.0: f *= F_H_SHORT_GOOD
        elif hp5 <= 20.0: f *= F_H_SHORT_BAD
    if hpc is not None:
        if hpc >= 50.0: f *= F_H_CAR_GOOD
        elif hpc <= 25.0: f *= F_H_CAR_BAD
    return f

def blend(p30, p5):
    if not p5 and not p30: return {}
    if not p30: return dict(p5)
    if not p5:  return dict(p30)
    keys = set(p30.keys()) | set(p5.keys())
    return {k: ALPHA_H30*float(p30.get(k,0.0)) + ALPHA_H5*float(p5.get(k,0.0)) for k in keys}

def place_slots(n: int) -> int:
    if n >= 8: return 3
    if n >= 4: return 2
    return 1

def renormalize_to_slots(p: Dict[str,float], n: int) -> Dict[str,float]:
    if not p: return {}
    slots = float(place_slots(n))
    clamped = {k: min(0.85, max(0.01, float(v))) for k, v in p.items()}
    s = sum(clamped.values())
    if s <= 0: return clamped
    scale = slots / s
    return {k: max(0.005, min(0.90, v*scale)) for k, v in clamped.items()}

def main():
    ap = argparse.ArgumentParser(description="Produit un *_p_finale.json avec facteurs J/E/Chronos + Cheval Stats")
    ap.add_argument("--h5", default=None)
    ap.add_argument("--h30", default=None)
    ap.add_argument("--input", default=None)
    ap.add_argument("--chrono", default=None)
    ap.add_argument("--je", default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--out-file", default=None)
    args = ap.parse_args()

    h5  = args.h5 or args.input
    h30 = args.h30
    snap5  = load_json(h5)
    snap30 = load_json(h30)

    p5  = implied_p_place_from_snapshot(snap5)  if snap5  else {}
    p30 = implied_p_place_from_snapshot(snap30) if snap30 else {}
    p   = blend(p30, p5) if (p30 and p5) else (p5 or p30)

    runners = (snap5 or snap30).get("runners", []) if (snap5 or snap30) else []
    n = len(runners)

    chronos = {}
    if args.chrono:
        chronos = load_chronos(args.chrono)
    je = {}
    if args.je:
        je = load_je(args.je)

    p_adj = {}
    for r in runners:
        num = str(r.get("num"))
        if num not in p:
            p[num] = 1.0 / max(1, n)
        val = float(p[num])

        # Chrono
        if chronos.get(num, 0) == 1:
            val *= F_CHRONO_OK

        # J/E
        je_inf = je.get(num, {})
        val *= je_factor(je_inf.get("j"), je_inf.get("e"))

        # Cheval stats
        val *= horse_factor(je_inf.get("h_p5"), je_inf.get("h_pc"))

        p_adj[num] = val

    if not p_adj:
        p_adj = dict(p)

    p_finale = renormalize_to_slots(p_adj, n)

    base_meta = (snap5 or snap30) if (snap5 or snap30) else {}
    meta = {
        "meeting": base_meta.get("meeting"),
        "date":    base_meta.get("date"),
        "r":       base_meta.get("r_label") or base_meta.get("reunion"),
        "c":       base_meta.get("c_label") or base_meta.get("course"),
        "partants": n,
        "blend": {"h30": bool(p30), "h5": bool(p5), "alpha_h30": ALPHA_H30, "alpha_h5": ALPHA_H5},
        "factors": {
            "chrono_ok": F_CHRONO_OK, "je_bonus": F_JE_BONUS, "je_malus": F_JE_MALUS,
            "horse_short_good": F_H_SHORT_GOOD, "horse_short_bad": F_H_SHORT_BAD,
            "horse_career_good": F_H_CAR_GOOD, "horse_career_bad": F_H_CAR_BAD
        }
    }

    out_obj = {"meta": meta, "p_place": {k: round(v, 6) for k, v in p_finale.items()}}

    if args.out_file:
        out_path = Path(args.out_file)
    else:
        base = Path(h5 or h30)
        stem = base.stem
        out_dir = Path(args.out_dir) if args.out_dir else base.parent
        out_path = out_dir / f"{stem}_p_finale.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] p_finale écrit → {out_path}")

if __name__ == "__main__":
    main()
