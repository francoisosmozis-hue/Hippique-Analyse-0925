#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse, json
from pathlib import Path

def save_json(p, obj):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    w with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def save_snapshot(label, data, outdir):
    """Save a snapshot labelled H30 or H05 into ``outdir``.

    The file names are normalised to ``h30.json`` and ``h5.json``.
    """

    name = "h30.json" if label.upper() == "H30" else "h5.json"
    path = Path(outdir) / name
    save_json(path, data)
    return pathith open(p,"w",encoding="utf-8") as f: json.dump(obj,f,ensure_ascii=False,indent=2)

def compute_diff(h30, h5):
    o30 = {r["id"]: float(r["odds"]) for r in h30.get("runners", []) if "odds" in r}
    o05 = {r["id"]: float(r["odds"]) for r in h5.get("runners", []) if "odds" in r}
    rows = []
    for cid in set(o30) & set(o05):
        delta = o05[cid] - o30[cid]
        rows.append({"id": cid, "cote_h30": o30[cid], "cote_h5": o05[cid], "delta": delta})
    rows = sorted(rows, key=lambda x: x["delta"])
    for i, r in enumerate(rows, 1):
        r["rank_delta"] = i
    top_steams = [r for r in rows if r["delta"] < 0][:3]
    top_drifts = [r for r in reversed(rows) if r["delta"] > 0][:3]
    return {"diff": rows, "top_steams": top_steams, "top_drifts": top_drifts}
def main():
    ap = argparse.ArgumentParser(description="Snapshot ZEturf/Geny H-30 / H-5")
    ap.add_argument("--reunion", required=True)
    ap.add_argument("--course", required=True)
    ap.add_argument("--when", choices=["H30", "H05"], required=True)
    ap.add_argument("--out", required=True, help="Répertoire de sortie")
    ap.add_argument("--from-json", help="Option: injecter un JSON déjà prêt (debug/offline)")
    args = ap.parse_args()

    if args.from_json:
        data = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
    else:
        # ICI: branche ton fetch réel (scraper/API/driver headless).
        # On garde un format commun:
        # {
        #   "rc":"R4C7","hippodrome":"Cabourg","date":"2025-09-10","discipline":"trot",
        #   "runners":[{"id":"1","name":"Cheval A","odds":3.4,"je_stats":{"j_win":12,"e_win":16}}, ...],
        #   "id2name":{"1":"Cheval A", ...}
        # }
        raise SystemExit("Implémente le fetch réel ici ou fournis --from-json.")

    outdir = Path(args.out)
    save_snapshot(args.when, data, outdir)

    h30_path = outdir / "h30.json"
    h5_path = outdir / "h5.json"
    if h30_path.exists() and h5_path.exists():
        h30 = json.loads(h30_path.read_text(encoding="utf-8"))
        h5 = json.loads(h5_path.read_text(encoding="utf-8"))
        diff = compute_diff(h30, h5)
        save_json(outdir / "diff_drift.json", diff)


if __name__=="__main__":
    main()
