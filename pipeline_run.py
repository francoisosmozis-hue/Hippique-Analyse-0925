#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, json, os, sys, math, datetime as dt
from pathlib import Path

try:
    import yaml  # PyYAML
except Exception as e:
    print("ERROR: PyYAML requis (pip install pyyaml).", file=sys.stderr); sys.exit(2)

# ==== Utils ================================================================

REQ_KEYS = [
    "BUDGET_TOTAL","SP_RATIO","COMBO_RATIO","EV_MIN_SP","EV_MIN_GLOBAL",
    "MAX_VOL_PAR_CHEVAL","ALLOW_JE_NA","PAUSE_EXOTIQUES","OUTDIR_DEFAULT",
    "EXCEL_PATH","CALIB_PATH","MODEL","REQUIRE_DRIFT_LOG",
    "REQUIRE_ODDS_WINDOWS","MIN_PAYOUT_COMBOS"
]

def load_yaml(path:str)->dict:
    with open(path,"r",encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("REQUIRE_DRIFT_LOG", True)
    cfg.setdefault("REQUIRE_ODDS_WINDOWS", [30, 5])
    cfg.setdefault("MIN_PAYOUT_COMBOS", 10.0)
    missing=[k for k in REQ_KEYS if k not in cfg]
    if missing:
        raise RuntimeError(f"Config incomplète: clés manquantes {missing}")
    return cfg

def load_json(path:str)->dict:
    with open(path,"r",encoding="utf-8") as f:
        return json.load(f)

def save_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path,"w",encoding="utf-8") as f:
        json.dump(obj,f,ensure_ascii=False,indent=2)

def save_text(path, txt:str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path,"w",encoding="utf-8") as f:
        f.write(txt)

# ==== DRIFT (H-30 vs H-5) ==================================================

def compute_drift(h30:dict, h5:dict)->dict:
    """Retourne diff_drift {cheval: {cote_h30, cote_h5, delta, rank_delta}}"""
    o30 = {x["id"]: float(x["odds"]) for x in h30.get("runners",[]) if "odds" in x}
    o05 = {x["id"]: float(x["odds"]) for x in h5.get("runners",[])  if "odds" in x}
    diff=[]
    for cid in set(o30.keys()) & set(o05.keys()):
        d = o30[cid]-o05[cid]   # positif => steam (cote baisse) si on prend delta négatif ? Clarifions:
        # convention: delta = cote_h5 - cote_h30 (négatif = baisse de cote = steam)
        delta = o05[cid] - o30[cid]
        diff.append({
            "id": cid,
            "name": h5["id2name"].get(cid, str(cid)) if "id2name" in h5 else str(cid),
            "cote_h30": o30[cid],
            "cote_h5": o05[cid],
            "delta": delta
        })
    # classements
    diff_sorted = sorted(diff, key=lambda r: r["delta"])  # plus négatif = plus gros steam
    for rank, row in enumerate(diff_sorted, start=1):
        row["rank_delta"]=rank
    return {"drift": diff_sorted}

# ==== VALIDATOR (bloquant) =================================================

def validator_blocking(h30:dict, h5:dict, allow_je_na:bool):
    # 1) cohérence partants
    ids30 = [x["id"] for x in h30.get("runners",[])]
    ids05 = [x["id"] for x in h5.get("runners",[])]
    if set(ids30) != set(ids05):
        raise ValueError("Partants incohérents entre H-30 et H-5.")
    if not ids05:
        raise ValueError("Aucun partant détecté.")

    # 2) cotes présentes
    for snap,label in [(h30,"H-30"),(h5,"H-5")]:
        for r in snap.get("runners",[]):
            if "odds" not in r or r["odds"] in (None,""):
                raise ValueError(f"Cotes manquantes ({label}) pour {r.get('name',r.get('id'))}.")
            try:
                if float(r["odds"]) <= 1.01:
                    raise ValueError(f"Cote invalide ({label}) pour {r.get('name',r.get('id'))}: {r['odds']}")
            except Exception:
                raise ValueError(f"Cote non numérique ({label}) pour {r.get('name',r.get('id'))}: {r.get('odds')}")

    # 3) Stats J/E (autoriser NA => neutre)
    if not allow_je_na:
        for r in h5.get("runners",[]):
            je=r.get("je_stats",{})
            if not je or ("j_win" not in je and "e_win" not in je):
                raise ValueError(f"Stats J/E manquantes pour {r.get('name',r.get('id'))}.")
    # OK
    return True

# ==== PROBAS / KELLY (SP Dutching) ========================================

def implied_probabilities(runners):
    raw=[1.0/float(r["odds"]) for r in runners]
    s=sum(raw)
    if s<=0: return [0]*len(raw)
    return [x/s for x in raw]  # dévig simple

def kelly_fraction(b, p):
    # f* = (bp - (1-p))/b
    return max(0.0, (b*p - (1.0-p))/b) if b>0 else 0.0

def build_sp_dutching(runners, cfg):
    # Filtre cotes 2.5–7.0, prendre 2–3 chevaux au meilleur score (proba implicite * bonus J/E/chrono si fournis)
    cand=[r for r in runners if 2.5 <= float(r["odds"]) <= 7.0]
    if not cand:
        return [], 0.0

    # Score simple (peut être remplacé par ton score pro)
    ps=implied_probabilities(cand)
    for r,p in zip(cand,ps):
        bonus = 0.0
        je=r.get("je_stats",{})
        if je:
            if je.get("j_win",0)>=12 or je.get("e_win",0)>=15: bonus+=0.02
            if je.get("j_win",0)<6 or je.get("e_win",0)<8: bonus-=0.02
        r["_score"]=p+bonus

    cand=sorted(cand,key=lambda x: x["_score"], reverse=True)[:3]  # 2–3 selon dispo
    # Kelly fractionné avec cap 60%/cheval
    budget=cfg["BUDGET_TOTAL"]*cfg["SP_RATIO"]
    alloc=[]
    # proba re-calculée pour les candidats retenus
    ps=implied_probabilities(cand)
    prob_map={r["id"]:p for r,p in zip(cand,ps)}
    kellys=[]
    for r,p in zip(cand,ps):
        b=float(r["odds"])-1.0
        k=kelly_fraction(b,p)
        kellys.append(k)
    sk=sum(kellys) or 1.0
    for r,k in zip(cand,kellys):
        f=min(cfg["MAX_VOL_PAR_CHEVAL"], k/sk)  # normalisation + cap
        stake=round(budget*float(f),2)
        if stake>0:
            alloc.append({"type":"SP","id":r["id"],"name":r.get("name",r["id"]),
                          "odds":float(r["odds"]),"stake":stake})
    ev_sp = sum(a["stake"]*(prob_map[a["id"]]*(a["odds"]-1.0) - (1.0-prob_map[a["id"]]))
                for a in alloc) if alloc else 0.0
    return alloc, ev_sp

# ==== COMBINÉ (placeholder safe) ==========================================

def build_combo_placeholder(runners, cfg, pause_exotiques:bool):
    """Construit AU PLUS UN combiné si non ‘pause’. Ici on met un placeholder CP value minimaliste.
       Dans ton repo, tu peux brancher simulate_ev.py/simulate_wrapper.py à cet endroit."""
    if pause_exotiques:
        return [], 0.0, None

    # heuristique simple: choisir 2 chevaux value 4–10/1 pour Couplé Placé
    cand=[r for r in runners if 4.0<=float(r["odds"])<=10.0]
    cand=sorted(cand, key=lambda r: float(r["odds"]))
    if len(cand)<2:
        return [], 0.0, None
    a,b=cand[0], cand[1]
    stake= round(cfg["BUDGET_TOTAL"]*cfg["COMBO_RATIO"],2)
    ticket=[{"type":"CP","pair":[a["id"],b["id"]],
             "names":[a.get("name",a["id"]), b.get("name",b["id"])],
             "stake": stake}]
    # EV simulée -> branche ton simulateur ici ; on met une hypothèse prudente
    ev_combo = 0.40 * stake * 0.10  # placeholder: 10% edge sur 40% du budget => 4% du budget
    return ticket, ev_combo, {"note":"combo_placeholder"}

# ==== EXPORT standardisé ===================================================

def export_all(outdir, meta, tickets, ev_sp, ev_combo, ev_global, cfg):
    Path(outdir).mkdir(parents=True, exist_ok=True)
    # tickets.json
    save_json(Path(outdir,"tickets.json"), {
        "meta": meta, "tickets": tickets,
        "ev": {"sp": ev_sp, "combo": ev_combo, "global": ev_global},
        "budget_total": cfg["BUDGET_TOTAL"],
        "ratios": {"sp": cfg["SP_RATIO"], "combo": cfg["COMBO_RATIO"]},
    })
    # ligne.csv (une ligne)
    ligne = (
        f'{meta.get("rc","R?C?")};{meta.get("hippodrome","")};'
        f'{meta.get("date","")};{meta.get("discipline","")};'
        f'{sum(t.get("stake",0) for t in tickets):.2f};'
        f'{ev_global:.4f};{cfg["MODEL"]}\n'
    )
    save_text(Path(outdir,"ligne.csv"), "R/C;hippodrome;date;discipline;mises;EV_globale;model\n"+ligne)
    # arrivee_placeholder.json
    save_json(Path(outdir,"arrivee_placeholder.json"), {
        "rc": meta.get("rc"), "date": meta.get("date"),
        "result": [], "gains": 0.0, "note":"placeholder en attente d’arrivée officielle"
    })
    # cmd_update_excel.txt
    cmd = (
        f'python update_excel_with_results.py '
        f'--excel "{cfg["EXCEL_PATH"]}" '
        f'--arrivee "{Path(outdir,"arrivee_officielle.json")}" '
        f'--tickets "{Path(outdir,"tickets.json")}"\n'
    )
    save_text(Path(outdir,"cmd_update_excel.txt"), cmd)

# ==== MAIN =================================================================

def main():
    ap=argparse.ArgumentParser(description="GPI v5.1 pipeline — run unique H-30/H-5 -> tickets/exports")
    ap.add_argument("--h30", required=True)
    ap.add_argument("--h5", required=True)
    ap.add_argument("--gpi", required=True, help="Chemin gpi_v51.yml")
    ap.add_argument("--outdir", default=None)
    args=ap.parse_args()

    cfg=load_yaml(args.gpi)
    # optional calibration flag
    try:
        with open(cfg["CALIB_PATH"],"r",encoding="utf-8") as f:
            cal=yaml.safe_load(f) or {}
        if isinstance(cal,dict) and "PAUSE_EXOTIQUES" in cal:
            cfg["PAUSE_EXOTIQUES"]=bool(cal["PAUSE_EXOTIQUES"])
    except Exception:
        pass

    outdir = args.outdir or cfg["OUTDIR_DEFAULT"]

    h30=load_json(args.h30)
    h5 =load_json(args.h5)

    # Validator bloquant
    validator_blocking(h30,h5, bool(cfg["ALLOW_JE_NA"]))

    # Drift
    drift=compute_drift(h30,h5)
    if "outdir" in args and args.outdir:
        save_json(Path(outdir,"diff_drift.json"), drift)

    # Sélection + Mises
    runners = h5.get("runners",[])
    meta = {
        "rc": h5.get("rc","R?C?"),
        "hippodrome": h5.get("hippodrome",""),
        "date": h5.get("date", dt.date.today().isoformat()),
        "discipline": h5.get("discipline",""),
        "model": cfg["MODEL"]
    }

    # SP
    sp_tickets, ev_sp = build_sp_dutching(runners, cfg)

    # Exotiques (UN seul)
    combo_tickets, ev_combo, combo_meta = build_combo_placeholder(runners, cfg, bool(cfg["PAUSE_EXOTIQUES"]))

    # EV / ROI / Seuils
    total_stake = sum(t.get("stake",0) for t in sp_tickets) + sum(t.get("stake",0) for t in combo_tickets)
    # sécurité budget dur
    if round(total_stake,2) > float(cfg["BUDGET_TOTAL"])+1e-6:
        raise RuntimeError(f"Budget dépassé ({total_stake} € > {cfg['BUDGET_TOTAL']} €).")

    ev_global = (ev_sp + ev_combo) if (sp_tickets or combo_tickets) else 0.0
    # Seuils d’activation
    if sp_tickets and ev_sp < float(cfg["EV_MIN_SP"])*sum(t["stake"] for t in sp_tickets):
        # SP jugé non EV+
        sp_tickets=[]; ev_sp=0.0
    # Combo activé seulement si EV globale >= EV_MIN_GLOBAL
    if combo_tickets:
        if (ev_sp + ev_combo) < float(cfg["EV_MIN_GLOBAL"])*float(cfg["BUDGET_TOTAL"]):
            # on annule le combiné
            combo_tickets=[]; ev_combo=0.0
    # Si rien d’EV+, on peut annuler tout
    if not sp_tickets and not combo_tickets:
        # Export vide mais traçable
        export_all(outdir, meta, [], 0.0, 0.0, 0.0, cfg)
        print("ABSTENTION: aucun ticket EV+ sous les seuils.")
        return

    tickets = sp_tickets + combo_tickets
    export_all(outdir, meta, tickets, ev_sp, ev_combo, ev_global, cfg)
    print(f"OK: tickets exportés dans {outdir}")

if __name__=="__main__":
    main()
