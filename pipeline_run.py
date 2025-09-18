#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal pipeline for computing EV and exporting artefacts."""

import argparse
import copy
import datetime as dt
import json
import logging
from pathlib import Path

import os
import sys

from config.env_utils import get_env

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency
    def load_dotenv(*args, **kwargs):  # type: ignore
        return None
import yaml

from simulate_ev import allocate_dutching_sp, gate_ev, simulate_ev_batch
from tickets_builder import allow_combo, apply_ticket_policy
from validator_ev import validate_inputs
from logging_io import append_csv_line, append_json, CSV_HEADER

logger = logging.getLogger(__name__)
LOG_LEVEL_ENV_VAR = "PIPELINE_LOG_LEVEL"


def configure_logging(level: str | int | None = None) -> None:
    """Configure root logging based on CLI or environment settings."""

    resolved = level if level is not None else os.getenv(LOG_LEVEL_ENV_VAR, "INFO")
    numeric_level: int | None
    invalid_level = False

    if isinstance(resolved, int):
        numeric_level = resolved
    else:
        resolved_str = str(resolved).upper()
        if resolved_str.isdigit():
            numeric_level = int(resolved_str)
        else:
            numeric_level = getattr(logging, resolved_str, None)
            if not isinstance(numeric_level, int):
                numeric_level = logging.INFO
                invalid_level = True

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if invalid_level:
        logger.warning(
            "Invalid log level %r, defaulting to INFO", resolved
        )

load_dotenv()
        
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


METRIC_KEYS = {"kelly_stake", "ev", "roi", "variance", "clv"}


def simulate_with_metrics(tickets: list[dict], bankroll: float) -> dict:
    """Run :func:`simulate_ev_batch` on a copy and merge metrics into ``tickets``."""

    if not tickets:
        return {"ev": 0.0, "roi": 0.0}

    sim_input = [copy.deepcopy(t) for t in tickets]
    stats = simulate_ev_batch(sim_input, bankroll=bankroll)
    for original, simulated in zip(tickets, sim_input):
        for key in METRIC_KEYS:
            if key in simulated:
                original[key] = simulated[key]
    return stats


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    cfg.setdefault("REQUIRE_DRIFT_LOG", True)
    cfg.setdefault("REQUIRE_ODDS_WINDOWS", [30, 5])
    if "EXOTIC_MIN_PAYOUT" in cfg:
        cfg["MIN_PAYOUT_COMBOS"] = cfg["EXOTIC_MIN_PAYOUT"]
    else:
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
    cfg.setdefault("SNAPSHOTS", "H30,H5")
    cfg.setdefault("DRIFT_TOP_N", 5)
    cfg.setdefault("DRIFT_MIN_DELTA", 0.8)
    cfg["SNAPSHOTS"] = get_env("SNAPSHOTS", cfg.get("SNAPSHOTS"))
    cfg["DRIFT_TOP_N"] = get_env(
        "DRIFT_TOP_N", cfg.get("DRIFT_TOP_N"), cast=int
    )
    cfg["DRIFT_MIN_DELTA"] = get_env(
        "DRIFT_MIN_DELTA", cfg.get("DRIFT_MIN_DELTA"), cast=float
    )
    cfg["BUDGET_TOTAL"] = get_env("BUDGET_TOTAL", cfg.get("BUDGET_TOTAL"), cast=float)
    cfg["EV_MIN_SP"] = get_env("EV_MIN_SP", cfg.get("EV_MIN_SP"), cast=float)
    cfg["EV_MIN_GLOBAL"] = get_env("EV_MIN_GLOBAL", cfg.get("EV_MIN_GLOBAL"), cast=float)
    cfg["ROI_MIN_SP"] = get_env("ROI_MIN_SP", cfg.get("ROI_MIN_SP"), cast=float)
    cfg["ROI_MIN_GLOBAL"] = get_env("ROI_MIN_GLOBAL", cfg.get("ROI_MIN_GLOBAL"), cast=float)
    exotic_min = get_env("EXOTIC_MIN_PAYOUT", cfg.get("MIN_PAYOUT_COMBOS"), cast=float)
    cfg["MIN_PAYOUT_COMBOS"] = exotic_min
    cfg.setdefault("EXOTIC_MIN_PAYOUT", exotic_min)
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


def compute_drift_dict(
    h30: dict,
    h5: dict,
    id2name: dict,
    *,
    top_n: int | None = None,
    min_delta: float = 0.0,
) -> dict:
    """Compute odds drift between two snapshots.

    Parameters
    ----------
    h30, h5 : dict
        Mapping of ``id`` -> cote at H-30 and H-5 respectively.
    id2name : dict
        Mapping ``id`` -> human readable name.
    top_n : int, optional
        Number of top steams/drifts to retain on each side.
    min_delta : float
        Minimum absolute odds variation required to be kept.

    Returns
    -------
    dict
        A dictionary containing the per-runner drift as well as lists of
        identifiers missing from either snapshot.
    """

    diff = []
    for cid in set(h30) & set(h5):
        delta = float(h5[cid]) - float(h30[cid])
        if abs(delta) < float(min_delta):
            continue
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
    if top_n is not None:
        neg = [r for r in diff if r["delta"] < 0][: int(top_n)]
        pos = [r for r in reversed(diff) if r["delta"] > 0][: int(top_n)]
        diff = sorted(neg + pos, key=lambda r: r["delta"])
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
    variance: float,
    combined_payout: float,
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
                "variance": variance,
                "combined_expected_payout": combined_payout,
            },
        },
    )
    drift_out = dict(drift)
    drift_out["params"] = {
        "snapshots": cfg.get("SNAPSHOTS"),
        "top_n": cfg.get("DRIFT_TOP_N"),
        "min_delta": cfg.get("DRIFT_MIN_DELTA"),
    }
    save_json(outdir / "diff_drift.json", drift_out)
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
# Analyse helper
# ---------------------------------------------------------------------------


def cmd_analyse(args: argparse.Namespace) -> None:
    cfg = load_yaml(args.gpi)
    if args.budget is not None:
        cfg["BUDGET_TOTAL"] = args.budget
    if args.ev_global is not None:
        cfg["EV_MIN_GLOBAL"] = args.ev_global
    if args.roi_global is not None:
        cfg["ROI_MIN_GLOBAL"] = args.roi_global
    if args.max_vol is not None:
        cfg["MAX_VOL_PAR_CHEVAL"] = args.max_vol
    if args.min_payout is not None:
        cfg["MIN_PAYOUT_COMBOS"] = args.min_payout
    if args.allow_je_na:
        cfg["ALLOW_JE_NA"] = True

    outdir = Path(args.outdir or cfg["OUTDIR_DEFAULT"])

    odds_h30 = load_json(args.h30)
    odds_h5 = load_json(args.h5)
    stats_je = load_json(args.stats_je)
    partants_data = load_json(args.partants)

    partants = partants_data.get("runners", [])
    id2name = partants_data.get(
        "id2name", {str(p["id"]): p.get("name", str(p["id"])) for p in partants}
    )
    rc = partants_data.get("rc", "R?C?")
    if "C" in rc:
        reunion_part, course_part = rc.split("C", 1)
        reunion = reunion_part
        course = f"C{course_part}"
    else:
        reunion = rc
        course = ""
    meta = {
        "rc": rc,
        "reunion": reunion,
        "course": course,
        "hippodrome": partants_data.get("hippodrome", ""),
        "date": partants_data.get("date", dt.date.today().isoformat()),
        "discipline": partants_data.get("discipline", ""),
        "model": cfg.get("MODEL", ""),
        "snapshots": cfg.get("SNAPSHOTS"),
        "drift_top_n": cfg.get("DRIFT_TOP_N"),
        "drift_min_delta": cfg.get("DRIFT_MIN_DELTA"),
    }

    if not isinstance(stats_je, dict):
        stats_je = {}
    if "coverage" not in stats_je:
        runner_ids = {
            str(p.get("id"))
            for p in partants
            if p.get("id") is not None
        }
        stats_ids = {
            str(cid)
            for cid, payload in stats_je.items()
            if cid != "coverage" and isinstance(payload, dict)
        }
        total = len(runner_ids)
        matched = len(runner_ids & stats_ids)
        stats_je["coverage"] = round(100.0 * matched / total, 2) if total else 0.0

    # Validation
    validate_inputs(cfg, partants, odds_h5, stats_je)

    # Drift & p_true
    if args.diff:
        drift = load_json(args.diff)
    else:
        drift = compute_drift_dict(
            odds_h30,
            odds_h5,
            id2name,
            top_n=int(cfg.get("DRIFT_TOP_N", 0)),
            min_delta=float(cfg.get("DRIFT_MIN_DELTA", 0.0)),
        )
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

    sp_tickets, combo_templates, _combo_info = apply_ticket_policy(
        cfg,
        runners,
        combo_candidates=None,
        combos_source=partants_data,
    )

    ev_sp = sum(t.get("ev_ticket", 0.0) for t in sp_tickets)
    total_stake_sp = sum(t.get("stake", 0.0) for t in sp_tickets)
    roi_sp = ev_sp / total_stake_sp if total_stake_sp > 0 else 0.0

    combo_budget = float(cfg.get("BUDGET_TOTAL", 0.0)) * float(cfg.get("COMBO_RATIO", 0.0))
    combo_tickets: list[dict] = []
    if combo_templates and combo_budget > 0:
        weights = [max(float(t.get("stake", 0.0)), 0.0) for t in combo_templates]
        total_weight = sum(weights)
        if total_weight <= 0:
            weights = [1.0] * len(combo_templates)
            total_weight = float(len(combo_templates))
        for template, weight in zip(combo_templates, weights):
            ticket = dict(template)
            ticket["stake"] = combo_budget * (weight / total_weight)
            combo_tickets.append(ticket)

    proposed_pack = sp_tickets + combo_tickets
    bankroll = float(cfg.get("BUDGET_TOTAL", 0.0))
    stats_ev = simulate_with_metrics(proposed_pack, bankroll=bankroll)
    ev_global = float(stats_ev.get("ev", 0.0))
    roi_global = float(stats_ev.get("roi", 0.0))
    combined_payout = float(stats_ev.get("combined_expected_payout", 0.0))
    risk_of_ruin = float(stats_ev.get("risk_of_ruin", 0.0))
    ev_over_std = float(stats_ev.get("ev_over_std", 0.0))

    flags = gate_ev(
        cfg,
        ev_sp,
        ev_global,
        roi_sp,
        roi_global,
        combined_payout,
        risk_of_ruin,
        ev_over_std,
    )

    combos_allowed = bool(combo_tickets) and flags.get("sp") and flags.get("combo")
    if combos_allowed:
        combos_allowed = allow_combo(ev_global, roi_global, combined_payout)
        combos_allowed = allow_combo(
            ev_global,
            roi_global,
            combined_payout,
            cfg=cfg,
        )
        if not combos_allowed:
            flags.setdefault("reasons", {}).setdefault("combo", []).append("ALLOW_COMBO")

    final_combo_tickets = combo_tickets if combos_allowed else []

    combo_budget_reassign = bool(combo_tickets) and not final_combo_tickets
    no_combo_available = (
        not combo_tickets
        and flags.get("sp")
        and not flags.get("combo")
        and float(cfg.get("COMBO_RATIO", 0.0)) > 0.0
    )

    if not flags.get("sp"):
        sp_tickets = []
        final_combo_tickets = []
        ev_sp = 0.0
        roi_sp = 0.0
        stats_ev = {"ev": 0.0, "roi": 0.0}
        ev_global = 0.0
        roi_global = 0.0
        combined_payout = 0.0
        risk_of_ruin = 0.0
        ev_over_std = 0.0
    elif combo_budget_reassign or no_combo_available:
        cfg_sp = dict(cfg)
        cfg_sp["SP_RATIO"] = float(cfg.get("SP_RATIO", 0.0)) + float(cfg.get("COMBO_RATIO", 0.0))
        cfg_sp["COMBO_RATIO"] = 0.0
        sp_tickets, _ = allocate_dutching_sp(cfg_sp, runners)
        sp_tickets.sort(key=lambda t: t.get("ev_ticket", 0.0), reverse=True)
        sp_tickets = sp_tickets[: int(cfg_sp.get("MAX_TICKETS_SP", cfg.get("MAX_TICKETS_SP", len(sp_tickets))))]
        ev_sp = sum(t.get("ev_ticket", 0.0) for t in sp_tickets)
        total_stake_sp = sum(t.get("stake", 0.0) for t in sp_tickets)
        roi_sp = ev_sp / total_stake_sp if total_stake_sp > 0 else 0.0
        stats_ev = simulate_with_metrics(sp_tickets, bankroll=bankroll)
        ev_global = float(stats_ev.get("ev", 0.0))
        roi_global = float(stats_ev.get("roi", 0.0))
        combined_payout = float(stats_ev.get("combined_expected_payout", 0.0))
        risk_of_ruin = float(stats_ev.get("risk_of_ruin", 0.0))
        ev_over_std = float(stats_ev.get("ev_over_std", 0.0))        
        flags = gate_ev(
            cfg_sp,
            ev_sp,
            ev_global,
            roi_sp,
            roi_global,
            combined_payout,
            risk_of_ruin,
            ev_over_std,
        )
    elif proposed_pack != sp_tickets + final_combo_tickets:
        final_pack = sp_tickets + final_combo_tickets
        stats_ev = simulate_with_metrics(final_pack, bankroll=bankroll)
        ev_global = float(stats_ev.get("ev", 0.0))
        roi_global = float(stats_ev.get("roi", 0.0))
        combined_payout = float(stats_ev.get("combined_expected_payout", 0.0))
        risk_of_ruin = float(stats_ev.get("risk_of_ruin", 0.0))
        ev_over_std = float(stats_ev.get("ev_over_std", 0.0))

    tickets = sp_tickets + final_combo_tickets

    if flags.get("reasons", {}).get("sp"):
        logger.warning(
            "Blocage SP dû aux seuils: %s",
            ", ".join(flags["reasons"]["sp"]),
        )
    if flags.get("reasons", {}).get("combo"):
        combo_reasons = ", ".join(flags["reasons"]["combo"])
        message = f"Blocage combinés dû aux seuils: {combo_reasons}"
        logger.warning(message)
        print(message)
    if not flags.get("sp", False):
        tickets = []
        ev_sp = ev_global = 0.0
        roi_sp = roi_global = 0.0

    risk_of_ruin = float(stats_ev.get("risk_of_ruin", 0.0)) if tickets else 0.0
    clv_moyen = float(stats_ev.get("clv", 0.0)) if tickets else 0.0
    combined_payout = float(stats_ev.get("combined_expected_payout", 0.0)) if tickets else 0.0
    variance_total = float(stats_ev.get("variance", 0.0)) if tickets else 0.0

    # Hard budget stop
    total_stake = sum(t.get("stake", 0) for t in tickets)
    if total_stake > float(cfg.get("BUDGET_TOTAL", 0.0)) + 1e-6:
        raise RuntimeError("Budget dépassé")

    course_id = meta.get("rc", "")
    append_csv_line(
        "modele_suivi_courses_hippiques_clean.csv",
        {
            "reunion": meta.get("reunion", ""),
            "course": meta.get("course", ""),
            "hippodrome": meta.get("hippodrome", ""),
            "date": meta.get("date", ""),
            "discipline": meta.get("discipline", ""),
            "partants": len(partants),
            "nb_tickets": len(tickets),
            "total_stake": total_stake,
            "ev_sp": ev_sp,
            "ev_global": ev_global,
            "roi_sp": roi_sp,
            "roi_global": roi_global,
            "risk_of_ruin": risk_of_ruin,
            "clv_moyen": clv_moyen,
            "model": cfg.get("MODEL", ""),
        },
        CSV_HEADER,
    )
    append_json(
        f"journaux/{course_id}_pre.json",
        {"tickets": tickets, "ev": {"sp": ev_sp, "global": ev_global}},
    )


    outdir.mkdir(parents=True, exist_ok=True)    
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
        variance_total,
        combined_payout,
        p_true,
        drift,
        cfg,
    )
    logger.info("OK: analyse exportée dans %s", outdir)


def cmd_snapshot(args: argparse.Namespace) -> None:
    """Write a race-specific snapshot file."""

    base = Path(args.outdir)
    src = base / f"{args.when}.json"
    data = load_json(str(src))
    rc = f"{args.meeting}{args.race}"
    dest = base / f"{rc}-{args.when}.json"
    save_json(dest, data)
    logger.info("Snapshot écrit: %s", dest)


def main() -> None:
    parser = argparse.ArgumentParser(description="GPI v5.1 pipeline")
    parser.add_argument(
        "--log-level",
        default=None,
        help=(
            "Logging level (DEBUG, INFO, WARNING, ERROR). "
            f"Can also be set via {LOG_LEVEL_ENV_VAR}."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    snap = sub.add_parser("snapshot", help="Renommer un snapshot h30/h5")
    snap.add_argument("--when", choices=["h30", "h5"], required=True)
    snap.add_argument("--meeting", required=True)
    snap.add_argument("--race", required=True)
    snap.add_argument("--outdir", required=True)
    snap.set_defaults(func=cmd_snapshot)

    ana = sub.add_parser("analyse", help="Analyser une course")
    ana.add_argument("--h30", required=True)
    ana.add_argument("--h5", required=True)
    ana.add_argument("--stats-je", required=True)
    ana.add_argument("--partants", required=True)
    ana.add_argument("--gpi", required=True)
    ana.add_argument("--outdir", default=None)
    ana.add_argument("--diff", default=None)
    ana.add_argument("--budget", type=float)
    ana.add_argument("--ev-global", dest="ev_global", type=float)
    ana.add_argument("--roi-global", dest="roi_global", type=float)
    ana.add_argument("--max-vol", dest="max_vol", type=float)
    ana.add_argument("--min-payout", dest="min_payout", type=float)
    ana.add_argument("--allow-je-na", dest="allow_je_na", action="store_true")
    ana.set_defaults(func=cmd_analyse)

    args = parser.parse_args()
    
    configure_logging(args.log_level)
    
    args.func(args)


if __name__ == "__main__":
    main()
