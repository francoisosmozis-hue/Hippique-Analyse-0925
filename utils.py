#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Utility functions for the GPI v5.1 pipeline."""

import json
import math
from pathlib import Path
from typing import Any


from simulate_ev import simulate_ev_batch


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


def save_json(path: Path, obj: Any) -> None:
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
    """Compute odds drift between two snapshots."""
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


def summarize_sp_tickets(sp_tickets: list[dict]) -> tuple[float, float, float]:
    """Return EV, ROI and total stake for SP tickets using updated metrics."""
    total_stake = sum(float(t.get("stake", 0.0)) for t in sp_tickets)
    ev_sp = sum(float(t.get("ev", t.get("ev_ticket", 0.0))) for t in sp_tickets)
    roi_sp = ev_sp / total_stake if total_stake > 0 else 0.0
    return ev_sp, roi_sp, total_stake


def simulate_with_metrics(
    tickets: list[dict],
    bankroll: float,
    *,
    kelly_cap: float | None = None,
) -> dict:
    """Run :func:`simulate_ev_batch` on a copy and merge metrics into ``tickets``."""
    if not tickets:
        return {"ev": 0.0, "roi": 0.0}

    sim_input = [t.copy() for t in tickets]
    if kelly_cap is None:
        stats = simulate_ev_batch(sim_input, bankroll=bankroll)
    else:
        stats = simulate_ev_batch(sim_input, bankroll=bankroll, kelly_cap=kelly_cap)
    for original, simulated in zip(tickets, sim_input):
        for key in METRIC_KEYS:
            if key in simulated:
                original[key] = simulated[key]
    return stats


def _scale_ticket_metrics(ticket: dict, factor: float) -> None:
    """Scale stake-dependent metrics of ``ticket`` in-place."""
    if not math.isfinite(factor):
        return

    for key in (
        "stake",
        "kelly_stake",
        "max_stake",
        "optimized_stake",
        "ev",
        "ev_ticket",
    ):
        if key in ticket and ticket.get(key) is not None:
            ticket[key] = float(ticket[key]) * factor

    if "variance" in ticket and ticket.get("variance") is not None:
        ticket["variance"] = float(ticket["variance"]) * factor * factor


def _compute_scale_factor(
    ev: float,
    variance: float,
    target: float,
    bankroll: float,
) -> float | None:
    """Return the multiplicative factor required to reach ``target`` risk."""
    if bankroll <= 0 or ev <= 0 or variance <= 0 or not (0.0 < target < 1.0):
        return None

    ln_target = math.log(target)
    if not math.isfinite(ln_target) or ln_target >= 0.0:
        return None

    denominator = variance * ln_target
    if denominator == 0.0:
        return None

    factor = (-2.0 * ev * bankroll) / denominator
    if not math.isfinite(factor) or factor <= 0.0:
        return None

    return min(1.0, factor)


def _resolve_effective_cap(info: dict | None, cfg: dict) -> float:
    """Return the effective Kelly cap extracted from ``info`` or defaults."""
    cap_default = float(cfg.get("MAX_VOL_PAR_CHEVAL", 0.60))
    if not isinstance(info, dict):
        return cap_default

    for key in ("effective_cap", "max_vol_par_cheval", "initial_cap"):
        value = info.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)

    return cap_default


def _summarize_optimization(
    tickets: list[dict],
    bankroll: float,
    kelly_cap: float,
) -> dict | None:
    """Return a normalized summary of the optimization run for ``tickets``."""
    if not tickets or bankroll <= 0:
        return None

    pack = [t.copy() for t in tickets]
    stats_opt = simulate_ev_batch(
        pack,
        bankroll=bankroll,
        kelly_cap=kelly_cap,
        optimize=True,
    )

    if not isinstance(stats_opt, dict):
        return None

    optimized_stakes = [float(x) for x in stats_opt.get("optimized_stakes", [])]
    metrics_before = stats_opt.get("ticket_metrics_individual") or []
    stake_before_val = sum(float(m.get("stake", 0.0)) for m in metrics_before)
    if stake_before_val <= 0:
        stake_before_val = sum(float(t.get("stake", 0.0)) for t in tickets)
    stake_before = float(stake_before_val)
    stake_after_val = sum(optimized_stakes) if optimized_stakes else stake_before
    stake_after = float(stake_after_val)

    applied = False
    if optimized_stakes and metrics_before:
        for opt, metrics in zip(optimized_stakes, metrics_before):
            if abs(opt - float(metrics.get("stake", 0.0))) > 1e-6:
                applied = True
                break

    summary: dict[str, object] = {
        "applied": applied,
        "ev_before": float(stats_opt.get("ev_individual", stats_opt.get("ev", 0.0))),
        "ev_after": float(stats_opt.get("ev", stats_opt.get("ev_individual", 0.0))),
        "roi_before": float(stats_opt.get("roi_individual", stats_opt.get("roi", 0.0))),
        "roi_after": float(stats_opt.get("roi", stats_opt.get("roi_individual", 0.0))),
        "stake_before": stake_before,
        "stake_after": stake_after,
        "risk_after": float(stats_opt.get("risk_of_ruin", 0.0)),
        "green": bool(stats_opt.get("green", False)),
    }

    if optimized_stakes:
        summary["optimized_stakes"] = optimized_stakes

    failure_reasons = stats_opt.get("failure_reasons")
    if failure_reasons:
        summary["failure_reasons"] = list(failure_reasons)

    return summary


def enforce_ror_threshold(
    cfg: dict,
    runners: list[dict],
    combo_tickets: list[dict],
    bankroll: float,
    *,
    max_iterations: int = 48,
) -> tuple[list[dict], dict, dict]:
    """Return SP tickets and EV metrics after enforcing the ROR threshold."""
    from simulate_ev import allocate_dutching_sp

    try:
        max_iterations = max(1, int(max_iterations))
    except (TypeError, ValueError):
        max_iterations = 1

    cfg_iter = dict(cfg)
    target = float(cfg_iter.get("ROR_MAX", 0.0))
    cap = float(cfg_iter.get("MAX_VOL_PAR_CHEVAL", 0.60))

    sp_tickets, _ = allocate_dutching_sp(cfg_iter, runners)
    sp_tickets.sort(key=lambda t: t.get("ev_ticket", 0.0), reverse=True)
    try:
        max_count = int(cfg_iter.get("MAX_TICKETS_SP", len(sp_tickets)))
    except (TypeError, ValueError):
        max_count = len(sp_tickets)
    if max_count >= 0:
        sp_tickets = sp_tickets[:max_count]

    pack = sp_tickets + combo_tickets
    if not pack:
        stats_ev = {"ev": 0.0, "roi": 0.0, "risk_of_ruin": 0.0, "variance": 0.0}
        info = {
            "applied": False,
            "initial_ror": 0.0,
            "final_ror": 0.0,
            "target": target,
            "scale_factor": 1.0,
            "initial_ev": 0.0,
            "final_ev": 0.0,
            "initial_variance": 0.0,
            "final_variance": 0.0,
            "initial_total_stake": 0.0,
            "final_total_stake": 0.0,
        }
        return sp_tickets, stats_ev, info

    stats_ev = simulate_with_metrics(pack, bankroll=bankroll, kelly_cap=cap)

    initial_risk = float(stats_ev.get("risk_of_ruin", 0.0))
    initial_ev = float(stats_ev.get("ev", 0.0))
    initial_variance = float(stats_ev.get("variance", 0.0))
    initial_total_stake = sum(float(t.get("stake", 0.0)) for t in pack)

    reduction_applied = False
    scale_factor_total = 1.0
    stats_current = stats_ev
    effective_cap = cap

    iterations = 0
    if initial_risk > target and bankroll > 0:
        while iterations < max_iterations:
            current_risk = float(stats_current.get("risk_of_ruin", 0.0))
            if current_risk <= target + 1e-9:
                break

            factor = _compute_scale_factor(
                float(stats_current.get("ev", 0.0)),
                float(stats_current.get("variance", 0.0)),
                target,
                bankroll,
            )
            if factor is None or factor >= 1.0 - 1e-9:
                break

            reduction_applied = True
            scale_factor_total *= factor
            effective_cap = cap * scale_factor_total
            for ticket in pack:
                _scale_ticket_metrics(ticket, factor)

            stats_current = simulate_with_metrics(
                pack,
                bankroll=bankroll,
                kelly_cap=effective_cap,
            )

            iterations += 1
            if factor <= 1e-6:
                break

        stats_ev = stats_current

    final_risk = float(stats_ev.get("risk_of_ruin", initial_risk))
    final_ev = float(stats_ev.get("ev", initial_ev))
    final_variance = float(stats_ev.get("variance", initial_variance))
    final_total_stake = sum(float(t.get("stake", 0.0)) for t in pack)

    info = {
        "applied": reduction_applied,
        "initial_ror": float(initial_risk),
        "final_ror": float(final_risk),
        "target": target,
        "scale_factor": scale_factor_total,
        "initial_ev": initial_ev,
        "final_ev": final_ev,
        "initial_variance": initial_variance,
        "final_variance": final_variance,
        "initial_total_stake": initial_total_stake,
        "final_total_stake": final_total_stake,
        "initial_cap": cap,
        "effective_cap": effective_cap,
        "iterations": iterations,
    }

    return sp_tickets, stats_ev, info


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
    *,
    stake_reduction_applied: bool = False,
    stake_reduction_details: dict | None = None,
    optimization_details: dict | None = None,
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
                "stake_reduction_applied": bool(stake_reduction_applied),
                "stake_reduction": {
                    "applied": bool(stake_reduction_applied),
                    "scale_factor": (
                        stake_reduction_details.get("scale_factor")
                        if stake_reduction_details
                        else None
                    ),
                    "target": (
                        stake_reduction_details.get("target")
                        if stake_reduction_details
                        else None
                    ),
                    "initial_cap": (
                        stake_reduction_details.get("initial_cap")
                        if stake_reduction_details
                        else None
                    ),
                    "effective_cap": (
                        stake_reduction_details.get("effective_cap")
                        if stake_reduction_details
                        else None
                    ),
                    "iterations": (
                        stake_reduction_details.get("iterations")
                        if stake_reduction_details
                        else None
                    ),
                    "initial": (
                        stake_reduction_details.get("initial")
                        if stake_reduction_details
                        else {}
                    ),
                    "final": (
                        stake_reduction_details.get("final")
                        if stake_reduction_details
                        else {}
                    ),
                },
                "optimization": optimization_details,
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
        f"python update_excel_with_results.py "
        f'--excel "{cfg.get("EXCEL_PATH")}" '
        f'--arrivee "{outdir / "arrivee_officielle.json"}" '
        f'--tickets "{outdir / "p_finale.json"}"\n'
    )
    save_text(outdir / "cmd_update_excel.txt", cmd)
