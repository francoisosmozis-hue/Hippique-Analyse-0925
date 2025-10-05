#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pmu_odds.py — Client léger pour endpoints JSON turfinfo.api.pmu.fr
- Programme du jour (liste des réunions/courses)
- Participants de chaque course
- Rapports définitifs (arrivées)
⚠️ Endpoints non documentés et susceptibles de changer. Respecte un rate-limit.
"""

from __future__ import annotations
import argparse, datetime as dt, csv, time, json
from pathlib import Path
import requests

ONLINE = "https://online.turfinfo.api.pmu.fr/rest/client"
OFFLINE = "https://offline.turfinfo.api.pmu.fr/rest/client"
UA = {"User-Agent": "pmu-open-client/0.1 (+roi-analyse)"}

def dmy(d: dt.date) -> str: return d.strftime("%d%m%Y")

def jget(url, retries=3, timeout=15):
    for i in range(retries):
        r = requests.get(url, headers=UA, timeout=timeout)
        if r.ok:
            return r.json()
        time.sleep(0.6*(i+1))
    raise RuntimeError(f"GET fail {url}")

def fetch_program(d): return jget(f"{OFFLINE}/7/programme/{dmy(d)}")

def iter_fr_courses(program_json: dict):
    prog = program_json.get("programme", {})
    for rn in (prog.get("reunions") or []):
        pays_obj = rn.get("pays", {})
        pays_code = pays_obj.get("code") if isinstance(pays_obj, dict) else pays_obj
        pays = (rn.get("codePays") or pays_code or rn.get("countryCode") or "").upper()
        if pays and "FR" not in pays:  # ne garder que FR
            continue
        hippo = rn.get("hippodrome", {}).get("libelleCourt") or rn.get("nomHippodrome")
        for c in (rn.get("courses") or []):
            r = c.get("numReunion") or rn.get("numReunion") or rn.get("numOfficiel")
            n = c.get("numOrdre") or c.get("numCourse")
            if r and n:
                yield int(r), int(n), hippo, c.get("heureDepart"), c.get("discipline")

def fetch_participants(d, r, c):
    return jget(f"{OFFLINE}/7/programme/{dmy(d)}/R{r}/C{c}/participants")

def odds_from_participant(p: dict) -> dict:
    # clés possibles suivant les flux
    val = {
        "cote": p.get("cote"),
        "coteDirect": p.get("coteDirect"),
        "coteProbable": p.get("coteProbable"),
        "coteReference": p.get("coteReference"),
        "rapportDirect": p.get("rapportDirect"),
        "rapportProbable": p.get("rapportProbable"),
    }
    
    # Check for odds in dernierRapportDirect
    dernier_rapport = p.get("dernierRapportDirect")
    if isinstance(dernier_rapport, dict):
        rapport = dernier_rapport.get("rapport")
        if rapport is not None:
            val["rapportDirect"] = rapport

    # parfois imbriqué dans un bloc "paris" ou par type
    paris = p.get("paris") or {}
    if isinstance(paris, dict):
        for k in ("simpleGagnant","simplePlace"):
            node = paris.get(k)
            if isinstance(node, dict):
                for kk in ("cote","rapportDirect","rapportProbable"):
                    v = node.get(kk)
                    if v is not None:
                        val[f"{k}_{kk}"] = v
    return {k: v for k, v in val.items() if v is not None}

def proba_from_rapport(x):
    try:
        v = float(x)
        return 1.0/v if v > 0 else None
    except: return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat(), help="YYYY-MM-DD")
    ap.add_argument("--out", default="data/pmu", help="dossier de sortie")
    ap.add_argument("--tag", default="", help="ex: h30, h5 (suffixe de fichier)")
    ap.add_argument("--sleep", type=float, default=0.4)
    args = ap.parse_args()

    d = dt.date.fromisoformat(args.date)
    outdir = Path(args.out) / args.date
    outdir.mkdir(parents=True, exist_ok=True)
    program = fetch_program(d)

    csv_path = outdir / f"odds{'_'+args.tag if args.tag else ''}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date","R","C","heure","hippodrome","discipline","num","cheval",
                    "cote","coteDirect","coteProbable","coteReference",
                    "rapportDirect","rapportProbable",
                    "simpleGagnant_cote","simpleGagnant_rapportDirect","simpleGagnant_rapportProbable",
                    "simplePlace_cote","simplePlace_rapportDirect","simplePlace_rapportProbable",
                    "p_win_from_rapportDirect","favori","tendance"])
        for R,C,hippo,heure,disc in iter_fr_courses(program):
            part = fetch_participants(d,R,C)
            for p in (part.get("participants") or []):
                num = p.get("numPmu") or p.get("numeroPmu") or p.get("numero")
                nom = p.get("nom") or (p.get("cheval") or {}).get("nom")
                fav = p.get("favori")
                trend = p.get("indicateurTendance") or p.get("tendance")
                od = odds_from_participant(p)
                pwin = proba_from_rapport(od.get("rapportDirect") or od.get("simpleGagnant_rapportDirect"))
                w.writerow([d.isoformat(),R,C,heure,hippo,disc,num,nom,
                            od.get("cote"),od.get("coteDirect"),od.get("coteProbable"),od.get("coteReference"),
                            od.get("rapportDirect"),od.get("rapportProbable"),
                            od.get("simpleGagnant_cote"),od.get("simpleGagnant_rapportDirect"),od.get("simpleGagnant_rapportProbable"),
                            od.get("simplePlace_cote"),od.get("simplePlace_rapportDirect"),od.get("simplePlace_rapportProbable"),
                            pwin,fav,trend])
            time.sleep(args.sleep)

    print(f"[✓] {csv_path} généré.")

if __name__ == "__main__":
    main()
