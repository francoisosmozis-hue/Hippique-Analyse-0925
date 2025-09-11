#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal pipeline for computing EV and exporting artefacts."""

import argparse
import datetime as dt
import json
from pathlib import Path

import yaml

from simulate_ev import allocate_dutching_sp, gate_ev, simulate_ev_batch
from validator_ev import validate_inputs

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REQ_KEYS = [
    "BUDGET_TOTAL",
    "SP_RATIO",
    "COMBO_RATIO",
    "EV_MIN_SP",
    "EV_MIN_GLOBAL",
    "ROI_MIN_SP",
    "ROI_MIN_GLOBAL",
    "ROR_MAX",
    "MAX_VOL_PAR_CHEVAL",
    "ALLOW_JE_NA",
    "PAUSE_EXOTIQUES",
    "OUTDIR_DEFAULT",
    "EXCEL_PATH",
    "CALIB_PATH",
    "MODEL",
    "REQUIRE_DRIFT_LOG",
    "REQUIRE_ODDS_WINDOWS",
    "MIN_PAYOUT_COMBOS",
    "MAX_TICKETS_SP",
    "DRIFT_COEF",
    "JE_BONUS_COEF",
]


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    cfg.setdefault("REQUIRE_DRIFT_LOG", True)
    cfg.setdefault("REQUIRE_ODDS_WINDOWS", [30, 5])
    cfg.setdefault("MIN_PAYOUT_COMBOS", 10.0)
    cfg.setdefault("MAX_TICKETS_SP", 2)
    cfg.setdefault("DRIFT_COEF", 0.05)
    cfg.setdefault("JE_BONUS_COEF", 0.001)
    cfg.setdefault("ROI_MIN_SP", 0.0)
    cfg.setdefault("ROI_MIN_GLOBAL", 0.0)
    cfg.setdefault("ROR_MAX", 0.05)
    missing = [k for k in REQ_KEYS if k not in cfg]
    if missing:
        raise RuntimeError(f"Config incomplète: clés manquantes {missing}")
    if float(cfg["SP_RATIO"]) + float(cfg["COMBO_RATIO"]) > 1.0:
        raise RuntimeError("SP_RATIO + COMBO_RATIO doit être <= 1.0")
    return cfg


def load_json(path: str):    
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def save_text(path: Path, txt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(txt, encoding="utf-8")


def compute_drift_dict(h30: dict, h5: dict, id2name: dict) -> dict:
    diff = []
    for cid in set(h30) & set(h5):
        delta = float(h5[cid]) - float(h30[cid])
        diff.append(
            {
                "id": cid,
                "name": id2name.get(cid, cid),
                "cote_h30": float(h30[cid]),
                "cote_h5": float(h5[cid]),
                "delta": delta,
            }
        )
    diff.sort(key=lambda r: r["delta"])
    for rank, row in enumerate(diff, start=1):
        row["rank_delta"] = rank
    return {"drift": diff}


def build_p_true(cfg, partants, odds_h5, odds_h30, stats_je) -> dict:
    weights = {}
    for p in partants:
        cid = str(p["id"])
        if cid not in odds_h5:
            continue
        o5 = float(odds_h5[cid])
        base = 1.0 / o5
        je = stats_je.get(cid, {})
        bonus = (je.get("j_win", 0) + je.get("e_win", 0)) * float(cfg["JE_BONUS_COEF"])
        drift = o5 - float(odds_h30.get(cid, o5))
        coef = float(cfg.get("DRIFT_COEF", 0.05))
        weight = base * (1.0 + bonus) * (1.0 - coef * drift)
        weights[cid] = max(weight, 0.0)
    total = sum(weights.values()) or 1.0
    return {cid: w / total for cid, w in weights.items()}


def export(outdir: Path, meta: dict, tickets: list, ev_sp: float, ev_global: float, p_true: dict, drift: dict, cfg: dict) -> None:
    save_json(outdir / "p_finale.json", {
        "meta": meta,
        "p_true": p_true,
        "tickets": tickets,
        "ev": {"sp": ev_sp, "global": ev_global},
    })
    save_json(outdir / "diff_drift.json", drift)
    total = sum(t.get("stake", 0) for t in tickets)
    ligne = (
        f'{meta.get("rc", "R?C?")};{meta.get("hippodrome", "")};'
        f'{meta.get("date", "")};{meta.get("discipline", "")};'
        f'{total:.2f};{ev_global:.4f};{cfg.get("MODEL", "")}'
    )
    save_text(outdir / "ligne.csv", "R/C;hippodrome;date;discipline;mises;EV_globale;model\n" + ligne + "\n")
    cmd = (
        f'python update_excel_with_results.py '
         f'--excel "{cfg.get("EXCEL_PATH")}" '
        f'--arrivee "{outdir / "arrivee_officielle.json"}" '
        f'--tickets "{outdir / "p_finale.json"}"\n'
    )
    save_text(outdir / "cmd_update_excel.txt", cmd)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="GPI v5.1 pipeline")
    ap.add_argument("--h30", required=True)
    ap.add_argument("--h5", required=True)
    ap.add_argument("--stats-je", required=True)
    ap.add_argument("--partants", required=True)
    ap.add_argument("--gpi", required=True)
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args()

    cfg = load_yaml(args.gpi)
    outdir = Path(args.outdir or cfg["OUTDIR_DEFAULT"])


    odds_h30 = load_json(args.h30)
    odds_h5 = load_json(args.h5)
    stats_je = load_json(args.stats_je)
    partants_data = load_json(args.partants)

    partants = partants_data.get("runners", [])
    id2name = partants_data.get("id2name", {str(p["id"]): p.get("name", str(p["id"])) for p in partants})
    meta = {
        "rc": partants_data.get("rc", "R?C?"),
        "hippodrome": partants_data.get("hippodrome", ""),
        "date": partants_data.get("date", dt.date.today().isoformat()),
        "discipline": partants_data.get("discipline", ""),
        "model": cfg.get("MODEL", ""),
    }

    # Validation
    validate_inputs(cfg, partants, odds_h30, odds_h5, stats_je)

    # Drift & p_true
    drift = compute_drift_dict(odds_h30, odds_h5, id2name)
    p_true = build_p_true(cfg, partants, odds_h5, odds_h30, stats_je)

    # Tickets allocation
    runners = []
    for p in partants:
        cid = str(p["id"])
        if cid in odds_h5 and cid in p_true:
            runners.append({
                "id": cid,
                "name": p.get("name", cid),
                "odds": float(odds_h5[cid]),
                "p": float(p_true[cid]),
            })

    tickets, ev_sp = allocate_dutching_sp(cfg, runners)
    
    # Prioritize tickets by individual EV before truncating
    tickets.sort(key=lambda t: t.get("ev_ticket", 0), reverse=True)
    
    # Limit number of tickets
    tickets = tickets[: int(cfg["MAX_TICKETS_SP"])]

    # Recompute EV/ROI after truncation
    ev_sp = sum(t.get("ev_ticket", 0.0) for t in tickets)
    total_stake_sp = sum(t.get("stake", 0.0) for t in tickets)
    roi_sp = ev_sp / total_stake_sp if total_stake_sp > 0 else 0.0

    # Global EV/ROI using simulations
    stats_ev = simulate_ev_batch(tickets, bankroll=float(cfg.get("BUDGET_TOTAL", 0.0))) if tickets else {"ev": 0.0}
    ev_global = float(stats_ev.get("ev", 0.0))
    roi_global = float(stats_ev.get("roi", 0.0))

    # Gating before emitting tickets
    flags = gate_ev(
        cfg,
        ev_sp,
        ev_global,
        roi_sp,
        roi_global,
        stats_ev.get("combined_expected_payout", 0.0),
        stats_ev.get("risk_of_ruin", 0.0),
    )
    if not flags.get("sp", False):
        tickets = []
        ev_sp = ev_global = 0.0

    # Hard budget stop
    total_stake = sum(t.get("stake", 0) for t in tickets)
    if total_stake > float(cfg.get("BUDGET_TOTAL", 0.0)) + 1e-6:
        raise RuntimeError("Budget dépassé")

    outdir.mkdir(parents=True, exist_ok=True)
    export(outdir, meta, tickets, ev_sp, ev_global, p_true, drift, cfg)
    print(f"OK: analyse exportée dans {outdir}")


if __name__ == "__main__":
    main()
