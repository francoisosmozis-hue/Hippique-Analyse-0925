#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal pipeline for computing EV and exporting artefacts."""

import argparse
import datetime as dt
import json
from pathlib import Path

import os
import sys

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency
    def load_dotenv(*args, **kwargs):  # type: ignore
        return None
import yaml

from simulate_ev import allocate_dutching_sp, gate_ev, simulate_ev_batch
from tickets_builder import allow_combo
from validator_ev import validate_inputs

load_dotenv()

REQ_VARS = [
    "BUDGET_TOTAL",
    "SP_RATIO",
    "COMBO_RATIO",
    "EV_MIN_SP",
    "EV_MIN_GLOBAL",
    "MAX_VOL_PAR_CHEVAL",
]

if __name__ == "__main__":
    missing_env = [v for v in REQ_VARS if os.getenv(v) is None]
    if missing_env:
        print(
            f"Variables d'environnement manquantes ignorées: {missing_env}",
            file=sys.stderr,
        )
        
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
    "SHARPE_MIN",
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
    "MIN_STAKE_SP",
    "DRIFT_COEF",
    "ROUND_TO_SP",
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
    cfg.setdefault("KELLY_FRACTION", 0.5)
    cfg.setdefault("MIN_STAKE_SP", 0.1)
    cfg.setdefault("ROUND_TO_SP", 0.10)
    cfg.setdefault("ROI_MIN_SP", 0.0)
    cfg.setdefault("ROI_MIN_GLOBAL", 0.0)
    cfg.setdefault("ROR_MAX", 0.05)
    cfg.setdefault("SHARPE_MIN", 0.0)
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
    """Compute odds drift between two snapshots.

    Parameters
    ----------
    h30, h5 : dict
        Mapping of ``id`` -> cote at H-30 and H-5 respectively.
    id2name : dict
        Mapping ``id`` -> human readable name.

    Returns
    -------
    dict
        A dictionary containing the per-runner drift as well as lists of
        identifiers missing from either snapshot.
    """

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
        
    missing_h30 = sorted(set(h5) - set(h30))
    missing_h5 = sorted(set(h30) - set(h5))

    return {"drift": diff, "missing_h30": missing_h30, "missing_h5": missing_h5}


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


def export(
    outdir: Path,
    meta: dict,
    tickets: list,
    ev_sp: float,
    ev_global: float,
    roi_sp: float,
    roi_global: float,
    risk_of_ruin: float,
    clv_moyen: float,
    p_true: dict,
    drift: dict,
    cfg: dict,
) -> None:
    save_json(
        outdir / "p_finale.json",
        {
            "meta": meta,
            "p_true": p_true,
            "tickets": tickets,
            "ev": {
                "sp": ev_sp,
                "global": ev_global,
                "roi_sp": roi_sp,
                "roi_global": roi_global,
                "risk_of_ruin": risk_of_ruin,
                "clv_moyen": clv_moyen,
            },
        },
    )
    save_json(outdir / "diff_drift.json", drift)
    total = sum(t.get("stake", 0) for t in tickets)
    ligne = (
        f'{meta.get("rc", "R?C?")};{meta.get("hippodrome", "")};'
        f'{meta.get("date", "")};{meta.get("discipline", "")};'
        f'{total:.2f};{ev_global:.4f};{cfg.get("MODEL", "")}'
    )
    save_text(
        outdir / "ligne.csv",
        "R/C;hippodrome;date;discipline;mises;EV_globale;model\n" + ligne + "\n",
    )
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
    validate_inputs(cfg, partants, odds_h5, stats_je)

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
        stats_ev.get("ev_over_std", 0.0),
    )

    # If combinés are blocked but SP is valid, reallocate the combo budget to SP
    if flags.get("sp") and not flags.get("combo"):
        cfg_sp = dict(cfg)
        cfg_sp["SP_RATIO"] = float(cfg.get("SP_RATIO", 0.0)) + float(
            cfg.get("COMBO_RATIO", 0.0)
        )
        tickets, ev_sp = allocate_dutching_sp(cfg_sp, runners)
        tickets.sort(key=lambda t: t.get("ev_ticket", 0), reverse=True)
        tickets = tickets[: int(cfg["MAX_TICKETS_SP"])]
        ev_sp = sum(t.get("ev_ticket", 0.0) for t in tickets)
        total_stake_sp = sum(t.get("stake", 0.0) for t in tickets)
        roi_sp = ev_sp / total_stake_sp if total_stake_sp > 0 else 0.0
        stats_ev = (
            simulate_ev_batch(tickets, bankroll=float(cfg.get("BUDGET_TOTAL", 0.0)))
            if tickets
            else {"ev": 0.0}
        )
        ev_global = float(stats_ev.get("ev", 0.0))
        roi_global = float(stats_ev.get("roi", 0.0))
        flags = gate_ev(
            cfg_sp,
            ev_sp,
            ev_global,
            roi_sp,
            roi_global,
            stats_ev.get("combined_expected_payout", 0.0),
            stats_ev.get("risk_of_ruin", 0.0),
            stats_ev.get("ev_over_std", 0.0),
        )
    combo = None
    if flags.get("sp") and flags.get("combo") and allow_combo(
        ev_global, stats_ev.get("combined_expected_payout", 0.0)
    ):
        combo = {
            "id": "CP1",
            "type": "CP",
            "legs": [t.get("id") for t in tickets],
            "ev_check": {
                "ev_ratio": ev_global,
                "payout_expected": stats_ev.get(
                    "combined_expected_payout", 0.0
                ),
            },
        }
        tickets.append(combo)

    if flags.get("reasons", {}).get("sp"):
        print(
            "Blocage SP dû aux seuils: "
            + ", ".join(flags["reasons"]["sp"])
        )
    if flags.get("reasons", {}).get("combo"):
        print(
            "Blocage combinés dû aux seuils: "
            + ", ".join(flags["reasons"]["combo"])
        )
    if not flags.get("sp", False):
        tickets = []
        ev_sp = ev_global = 0.0

    # Hard budget stop
    total_stake = sum(t.get("stake", 0) for t in tickets)
    if total_stake > float(cfg.get("BUDGET_TOTAL", 0.0)) + 1e-6:
        raise RuntimeError("Budget dépassé")

    outdir.mkdir(parents=True, exist_ok=True)
    risk_of_ruin = float(stats_ev.get("risk_of_ruin", 0.0))
    clv_moyen = float(stats_ev.get("clv", 0.0))
    export(
        outdir,
        meta,
        tickets,
        ev_sp,
        ev_global,
        roi_sp,
        roi_global,
        risk_of_ruin,
        clv_moyen,
        p_true,
        drift,
        cfg,
    )
    print(f"OK: analyse exportée dans {outdir}")


if __name__ == "__main__":
    main()
