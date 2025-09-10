#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
from pathlib import Path

def _save_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def _save_text(path, txt):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(txt, encoding="utf-8")

def export(outdir:str, meta:dict, tickets:list, ev:dict, cfg:dict):
    out=Path(outdir); out.mkdir(parents=True, exist_ok=True)
    # 1) tickets.json
    _save_json(out/"tickets.json", {
        "meta":meta, "tickets":tickets, "ev":ev,
        "budget_total": cfg.get("BUDGET_TOTAL"), "ratios":{"sp":cfg.get("SP_RATIO"),"combo":cfg.get("COMBO_RATIO")}
    })
    # 2) ligne.csv
    total = sum(t.get("stake",0) for t in tickets)
    ligne = f'{meta.get("rc")};{meta.get("hippodrome","")};{meta.get("date","")};{meta.get("discipline","")};{total:.2f};{ev.get("global",0):.4f};{cfg.get("MODEL","")}\n'
    _save_text(out/"ligne.csv", "R/C;hippodrome;date;discipline;mises;EV_globale;model\n"+ligne)
    # 3) arrivee_placeholder.json
    _save_json(out/"arrivee_placeholder.json", {"rc":meta.get("rc"),"date":meta.get("date"),"result":[],"gains":0.0,"note":"placeholder"})
    # 4) cmd_update_excel.txt
    cmd = f'python update_excel_with_results.py --excel "{cfg.get("EXCEL_PATH","modele_suivi_courses_hippiques.xlsx")}" --arrivee "{out/"arrivee_officielle.json"}" --tickets "{out/"tickets.json"}"\n'
    _save_text(out/"cmd_update_excel.txt", cmd)
