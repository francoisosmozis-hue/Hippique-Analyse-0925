#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal pipeline for computing EV and exporting artefacts."""

import logging

logger = logging.getLogger(__name__)
LOG_LEVEL_ENV_VAR = "PIPELINE_LOG_LEVEL"
DEFAULT_OUTPUT_DIR = "out/hminus5"

PLACE_FEE = 0.15

def build_p_true(cfg, partants, odds_h5, odds_h30, stats_je):
    return {}

def compute_drift_dict(h30, h5, id2name, top_n=5, min_delta=0.8):
    return {"missing_h30": [], "missing_h5": [], "drift": []}

def load_yaml(path):
    return {}

def _build_market(runners, slots_place_str=None):
    return {"slots_place": 3, "overround_place": 1.0, "runner_count_total": len(runners), "runner_count_with_win_odds": len(runners), "win_coverage_ratio": 1.0, "win_coverage_sufficient": True, "overround_win": 1.0, "overround": 1.0}

def _ensure_place_odds(runners, market):
    pass

def enforce_ror_threshold(cfg, runners, combo_tickets, bankroll, **kwargs):
    return [], {}, {"applied": False}

def market_drift_signal(odds1, odds2, is_favorite):
    return 0

def cmd_analyse(args):
    outdir = args.outdir
    print(f"[dummy cmd_analyse] outdir: {outdir}")
    if outdir:
        import json
        from pathlib import Path
        p_finale_path = Path(outdir) / "p_finale.json"
        data = {
            "meta": {
                "rc": "R1C1"
            }
        }
        print(f"[dummy cmd_analyse] writing to {p_finale_path} with data: {data}")
        p_finale_path.write_text(json.dumps(data))
