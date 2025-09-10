#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse, json
from pathlib import Path

def save_json(p, obj):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p,"w",encoding="utf-8") as f: json.dump(obj,f,ensure_ascii=False,indent=2)

def compute_diff(h30, h5):
    o30={r["id"]:float(r["odds"]) for r in h30.get("runners",[]) if "odds" in r}
    o05={r["id"]:float(r["odds"]) for r in h5.get("runners",[]) if "odds" in r}
    rows=[]
    for cid in set(o30)&set(o05):
        delta=o05[cid]-o30[cid]
        rows.append({"id":cid,"cote_h30":o30[cid],"cote_h5":o05[cid],"delta":delta})
    rows=sorted(rows,key=lambda x:x["delta"])
    for i,r in enumerate(rows,1): r["rank_delta"]=i
    return {"drift":rows}

def main():
    ap=argparse.ArgumentParser(description="Snapshot ZEturf/Geny H-30 / H-5")
    ap.add_argument("--reunion", required=True)
    ap.add_argument("--course", required=True)
    ap.add_argument("--when", choices=["H30","H05"], required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--from-json", help="Option: injecter un JSON déjà prêt (debug/offline)")
    ap.add_argument("--pair", help="Option: autre snapshot pour produire directement diff_drift.json")
    args=ap.parse_args()

    if args.from_json:
        data=json.loads(Path(args.from_json).read_text(encoding="utf-8"))
    else:
        # ICI: branche ton fetch réel (scraper/API/driver headless).
        # On garde un format commun:
        # {
        #   "rc":"R4C7","hippodrome":"Cabourg","date":"2025-09-10","discipline":"trot",
        #   "runners":[{"id":"1","name":"Cheval A","odds":3.4,"je_stats":{"j_win":12,"e_win":16}}, ...],
        #   "id2name":{"1":"Cheval A", ...}
        # }
        raise SystemExit("Implémente le fetch réel ici ou fournis --from-json.")

    save_json(args.out, data)

    # si on a un pair opposé on calcule le diff immédiatement
    if args.pair:
        other=json.loads(Path(args.pair).read_text(encoding="utf-8"))
        out_path = Path(args.out).with_name("diff_drift.json")
        save_json(out_path, compute_diff(data, other) if args.when=="H05" else compute_diff(other, data))

if __name__=="__main__":
    main()
