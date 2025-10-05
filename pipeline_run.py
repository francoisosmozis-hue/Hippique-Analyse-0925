#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal pipeline for computing EV and exporting artefacts."""

import argparse
import copy
import datetime as dt
import json
import logging

logger = logging.getLogger(__name__)
LOG_LEVEL_ENV_VAR = "PIPELINE_LOG_LEVEL"
import math
import re
from functools import partial
from pathlib import Path

import os
import sys

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


from logging_io import append_csv_line, CSV_HEADER, append_json
from simulate_ev import allocate_dutching_sp, gate_ev, simulate_ev_batch
from tickets_builder import apply_ticket_policy
from validator_ev import summarise_validation, validate_inputs
import simulate_wrapper as sw
from config.config_loader import load_config
from data_loader import load_json
from validator import validate_snapshot_data, validate_partants_data, validate_stats_je_data
from utils import (
    save_json,
    save_text,
    compute_drift_dict,
    summarize_sp_tickets,
    simulate_with_metrics,
    enforce_ror_threshold,
    export,
)


try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception: # pragma: no cover - optional dependency
    pass


METRIC_KEYS = {
    "kelly_stake",
    "ev",
    "roi",
    "variance",
    "clv",
    "stake",
    "max_stake",
    "optimized_stake",
    "expected_payout",
    "optimized_expected_payout",
    "sharpe",
    "optimized_sharpe",
}

def _heuristic_p_true(cfg, partants, odds_h5, odds_h30, stats_je) -> dict:
    weights = {}
    for p in partants:
        cid = str(p.get("id") or p.get("numPmu"))
        if cid not in odds_h5:
            continue
        o5 = float(odds_h5[cid])
        if o5 == 0.0:
            continue
        base = 1.0 / o5
        je = stats_je.get(cid, {})
        bonus = (je.get("j_win", 0) + je.get("e_win", 0)) * float(cfg["JE_BONUS_COEF"])
        drift = o5 - float(odds_h30.get(cid, o5))
        coef = float(cfg.get("DRIFT_COEF", 0.05))
        weight = base * (1.0 + bonus) * (1.0 - coef * drift)
        weights[cid] = max(weight, 0.0)
    total = sum(weights.values()) or 1.0
    return {cid: w / total for cid, w in weights.items()}


def build_p_true(cfg, partants, odds_h5, odds_h30, stats_je) -> dict:
    model = None
    try:
        model = load_p_true_model()
    except Exception as exc:  # pragma: no cover - corrupted file
        logger.warning("Impossible de charger le modèle p_true: %s", exc)
        model = None

    if model is not None:
        probs = {}
        for p in partants:
            cid = str(p.get("id"))
            if cid not in odds_h5:
                continue
            try:
                features = compute_runner_features(
                    float(odds_h5[cid]),
                    float(odds_h30.get(cid, odds_h5[cid])) if odds_h30 else None,
                    stats_je.get(cid) if stats_je else None,
                )
            except (ValueError, TypeError):
                continue
            prob = predict_probability(model, features)
            probs[cid] = prob

        total = sum(probs.values())
        if total > 0:
            return {cid: prob / total for cid, prob in probs.items()}
        logger.info("Calibration p_true indisponible, retour à l'heuristique")

    return _heuristic_p_true(cfg, partants, odds_h5, odds_h30, stats_je)


# ---------------------------------------------------------------------------
# Analyse helper
# ---------------------------------------------------------------------------


def cmd_analyse(args: argparse.Namespace) -> None:
    cfg = load_config(args.gpi)
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

    sw.set_correlation_penalty(cfg.get("CORRELATION_PENALTY"))

    outdir = Path(args.outdir or cfg["OUTDIR_DEFAULT"])

    h30_data = load_json(args.h30)
    validate_snapshot_data(h30_data, args.h30)
    h5_data = load_json(args.h5)
    validate_snapshot_data(h5_data, args.h5)
    odds_h30 = {runner['id']: runner['odds'] for runner in h30_data.get('runners', [])}
    odds_h5 = {runner['id']: runner['odds'] for runner in h5_data.get('runners', [])}
    
    stats_je = load_json(args.stats_je)
    validate_stats_je_data(stats_je, args.stats_je)
    partants_data = load_json(args.partants)
    validate_partants_data(partants_data, args.partants)

    partants = partants_data.get("runners", [])
    if not partants:
        partants = partants_data.get("participants", [])

    id2name = partants_data.get(
        "id2name", {str(p.get("id") or p.get("numPmu")): p.get("name", str(p.get("id") or p.get("numPmu"))) for p in partants}
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
    validate_inputs_call = partial(validate_inputs, cfg, partants, odds_h5, stats_je)
    validation_summary = summarise_validation(validate_inputs_call)
    meta["validation"] = dict(validation_summary)
    if not validation_summary["ok"]:
        logger.error("Validation failed: %s", validation_summary["reason"])
        validate_inputs_call()

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
        cid = str(p.get("id") or p.get("numPmu"))
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

    ev_sp = 0.0
    total_stake_sp = 0.0
    roi_sp = 0.0

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

    bankroll = float(cfg.get("BUDGET_TOTAL", 0.0))
    
    def log_reduction(info: dict) -> None:
        logger.warning(
            (
                "Risk of ruin %.2f%% > %.2f%%: réduction globale s=%.3f "
                "(mise %.2f→%.2f, variance %.2f→%.2f, cap %.2f→%.2f, "
                "risque final %.2f%%, %d itérations)"
            ),
            info.get("initial_ror", 0.0) * 100.0,
            info.get("target", 0.0) * 100.0,
            info.get("scale_factor", 1.0),
            info.get("initial_total_stake", 0.0),
            info.get("final_total_stake", 0.0),
            info.get("initial_variance", 0.0),
            info.get("final_variance", 0.0),
            info.get("initial_cap", 0.0),
            info.get("effective_cap", 0.0),
            info.get("final_ror", 0.0) * 100.0,
            int(info.get("iterations", 0)),
        )

    def adjust_pack(cfg_local: dict, combos_local: list[dict]) -> tuple[list[dict], dict, dict]:
        sp_adj, stats_local, info_local = enforce_ror_threshold(
            cfg_local,
            runners,
            combos_local,
            bankroll=bankroll,
        )
        if info_local.get("applied"):
            log_reduction(info_local)
        return sp_adj, stats_local, info_local

    sp_tickets, stats_ev, reduction_info = adjust_pack(cfg, combo_tickets)
    last_reduction_info = reduction_info

    ev_sp, roi_sp, total_stake_sp = summarize_sp_tickets(sp_tickets)
    ev_global = float(stats_ev.get("ev", 0.0))
    roi_global = float(stats_ev.get("roi", 0.0))
    combined_payout = float(stats_ev.get("combined_expected_payout", 0.0))
    risk_of_ruin = float(stats_ev.get("risk_of_ruin", 0.0))
    ev_over_std = float(stats_ev.get("ev_over_std", 0.0))

    proposed_pack = sp_tickets + combo_tickets

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
        total_stake_sp = 0.0
        last_reduction_info = {
            "applied": False,
            "scale_factor": 1.0,
            "initial_ror": 0.0,
            "final_ror": 0.0,
            "target": float(cfg.get("ROR_MAX", 0.0)),
            "initial_ev": 0.0,
            "final_ev": 0.0,
            "initial_variance": 0.0,
            "final_variance": 0.0,
            "initial_total_stake": 0.0,
            "final_total_stake": 0.0,
        }
    elif combo_budget_reassign or no_combo_available:
        cfg_sp = dict(cfg)
        cfg_sp["SP_RATIO"] = float(cfg.get("SP_RATIO", 0.0)) + float(cfg.get("COMBO_RATIO", 0.0))
        cfg_sp["COMBO_RATIO"] = 0.0
        sp_tickets, _ = allocate_dutching_sp(cfg_sp, runners)
        sp_tickets, stats_ev, reduction_info = adjust_pack(cfg_sp, [])
        last_reduction_info = reduction_info
        ev_sp, roi_sp, total_stake_sp = summarize_sp_tickets(sp_tickets)
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
        current_cap = _resolve_effective_cap(last_reduction_info, cfg)
        stats_ev = simulate_with_metrics(
            final_pack,
            bankroll=bankroll,
            kelly_cap=current_cap,
        )
        ev_sp, roi_sp, total_stake_sp = summarize_sp_tickets(sp_tickets)
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

    optimization_summary = None
    if tickets:
        effective_cap = _resolve_effective_cap(last_reduction_info, cfg)
        optimization_summary = _summarize_optimization(
            tickets,
            bankroll=bankroll,
            kelly_cap=effective_cap,
        )

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
            "total_optimized_stake": (
                optimization_summary.get("stake_after")
                if optimization_summary
                else total_stake
            ),
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
    stake_reduction_info = last_reduction_info or {}
    stake_reduction_flag = bool(stake_reduction_info.get("applied"))
    stake_reduction_details = {
        "scale_factor": stake_reduction_info.get("scale_factor", 1.0),
        "target": stake_reduction_info.get("target"),
        "initial_cap": stake_reduction_info.get("initial_cap"),
        "effective_cap": stake_reduction_info.get("effective_cap"),
        "iterations": stake_reduction_info.get("iterations"),
        "initial": {
            "risk_of_ruin": stake_reduction_info.get("initial_ror"),
            "ev": stake_reduction_info.get("initial_ev"),
            "variance": stake_reduction_info.get("initial_variance"),
            "total_stake": stake_reduction_info.get("initial_total_stake"),
        },
        "final": {
            "risk_of_ruin": stake_reduction_info.get("final_ror"),
            "ev": stake_reduction_info.get("final_ev"),
            "variance": stake_reduction_info.get("final_variance"),
            "total_stake": stake_reduction_info.get("final_total_stake"),
        },
    }    
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
        stake_reduction_applied=stake_reduction_flag,
        stake_reduction_details=stake_reduction_details,
        optimization_details=optimization_summary,
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

# ==== TEST-COMPAT helpers: export_optimization + try_trim_sp_by_ror ====
def _export_with_optimization(base: dict, ev_result: dict) -> dict:
    """Injecte un résumé d'optimisation si présent."""
    out = dict(base)
    ev_block = dict(out.get("ev", {}))
    if "optimization" in ev_result:
        ev_block["optimization"] = ev_result["optimization"]
    out["ev"] = ev_block
    return out

def _try_trim_sp_by_ror(cfg, runners, sp_tickets, *, bankroll: float):
    """
    Si ROR trop élevé, applique enforce_ror_threshold et renvoie (tickets, stats, info).
    Sinon, renvoie (tickets, stats, {"applied": False, ...})
    """
    from ev_calculator import enforce_ror_threshold, compute_ev_roi
    k_cap = float(cfg.get("MAX_VOL_PAR_CHEVAL", 0.60))
    rnd = float(cfg.get("ROUND_TO_SP", 0.10))
    stats0 = compute_ev_roi([dict(t) for t in sp_tickets], budget=float(bankroll), kelly_cap=k_cap, round_to=rnd)
    r0 = float(stats0.get("risk_of_ruin", 1.0))
    if r0 <= float(cfg.get("ROR_MAX", 1.0)):
        return sp_tickets, stats0, {"applied": False, "initial_ror": r0, "final_ror": r0, "target": float(cfg.get("ROR_MAX", 1.0))}
    return enforce_ror_threshold(cfg, runners, sp_tickets, bankroll=bankroll)