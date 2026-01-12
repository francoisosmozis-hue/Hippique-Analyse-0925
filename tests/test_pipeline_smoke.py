# from hippique_orchestrator.config import PAYOUT_CALIBRATION_PATH

# DEFAULT_CALIBRATION = str(PAYOUT_CALIBRATION_PATH)

GPI_YML = """
budget_cap_eur: 5.0
overround_max_exotics: 1.30
roi_min_sp: 0.10
ev_min_combo: 0.20
payout_min_combo: 12.0
tickets_max: 2
max_vol_per_horse: 0.60
SP_RATIO: 0.6
COMBO_RATIO: 0.4
EV_MIN_SP: 0.15
EV_MIN_SP_HOMOGENEOUS: 0.10
EV_MIN_GLOBAL: 0.35
ROI_MIN_GLOBAL: 0.25
ROR_MAX: 0.05
correlation_penalty: 0.85
MAX_TICKETS_SP: 1
ALLOW_JE_NA: true
PAUSE_EXOTIQUES: false
OUTDIR_DEFAULT: "runs/test"
EXCEL_PATH: "modele_suivi_courses_hippiques.xlsx"
CALIB_PATH: "payout_calibration.yaml"
DRIFT_COEF: 0.05
JE_BONUS_COEF: 0.001
MIN_STAKE_SP: 0.10
ROUND_TO_SP: 0.10
KELLY_FRACTION: 0.5
SHARPE_MIN: 0.5
MODEL: "GPI v5.1"

tickets:
  sp_dutching:
    odds_range: [5.0, 20.0]
    legs_min: 2
    legs_max: 5
    kelly_frac: 0.5
  exotics:
    allowed: ["TRIO"]
"""


def partants_sample():
    runners_data = [
        {
            "id": "1",
            "num": "1",
            "name": "A",
            "odds_place": 1.6,
            "odds_place_h30": 1.55,
            "odds": 2.2,
        },
        {
            "id": "2",
            "num": "2",
            "name": "B",
            "odds_place": 1.7,
            "odds_place_h30": 1.65,
            "odds": 3.1,
        },
        {
            "id": "3",
            "num": "3",
            "name": "C",
            "odds_place": 1.9,
            "odds_place_h30": 1.85,
            "odds": 4.2,
        },
        {"id": "4", "num": "4", "name": "D", "odds_place": 2.4, "odds_place_h30": 2.3, "odds": 6.0},
        {"id": "5", "num": "5", "name": "E", "odds_place": 3.6, "odds_place_h30": 3.5, "odds": 9.0},
        {
            "id": "6",
            "num": "6",
            "name": "F",
            "odds_place": 4.2,
            "odds_place_h30": 4.0,
            "odds": 11.0,
        },
    ]
    for r in runners_data:
        r['cote'] = r['odds']
        r['p_place'] = 1.0 / r['odds_place']
        r['volatility'] = 0.5

    return {
        "rc": "R1C1",
        "hippodrome": "Test",
        "date": "2025-09-10",
        "discipline": "trot",
        "runners": runners_data,
        "market": {
            "slots_place": 3,
            "horses": [
                {"id": "1", "odds": 2.2, "odds_place": 1.6},
                {"id": "2", "odds": 3.1, "odds_place": 1.7},
                {"id": "3", "odds": 4.2, "odds_place": 1.9},
                {"id": "4", "odds": 6.0, "odds_place": 2.4},
                {"id": "5", "odds": 9.0, "odds_place": 3.6},
                {"id": "6", "odds": 11.0, "odds_place": 4.2},
            ],
        },
    }


def odds_h30():
    return {"1": 2.0, "2": 3.0, "3": 4.0, "4": 5.0, "5": 8.0, "6": 10.0}


def odds_h5():
    return {"1": 2.2, "2": 3.1, "3": 4.2, "4": 6.0, "5": 9.0, "6": 11.0}


def stats_sample():
    return {
        "1": {"j_win": 1, "e_win": 1},
        "2": {"j_win": 1, "e_win": 1},
        "3": {"j_win": 1, "e_win": 1},
        "4": {"j_win": 1, "e_win": 1},
        "5": {"j_win": 1, "e_win": 1},
        "6": {"j_win": 1, "e_win": 1},
    }


# def test_build_market_overround_place_with_missing_or_textual_slots():
#     runners = [
#         {"odds": 2.0, "odds_place": 1.6},
#         {"odds": 3.0, "odds_place": 1.8},
#         {"odds": 4.0, "odds_place": 2.2},
#     ]

#     total_place_prob = sum(1.0 / runner["odds_place"] for runner in runners)

#     metrics_missing = pipeline_run._build_market(runners)
#     assert metrics_missing["slots_place"] == 3
#     assert metrics_missing["overround_place"] == pytest.approx(total_place_prob)

#     metrics_textual = pipeline_run._build_market(runners, "3 places payees")
#     assert metrics_textual["slots_place"] == 3
#     assert metrics_textual["overround_place"] == pytest.approx(total_place_prob)


# def test_build_market_normalizes_comma_separated_place_odds():
#     runners = [
#         {"odds": 2.0, "odds_place": "1,6"},
#         {"odds": 3.0, "odds_place": "1,7"},
#         {"odds": 4.0, "odds_place": "1,8"},
#     ]

#     expected = sum(1.0 / float(runner["odds_place"].replace(",", ".")) for runner in runners)

#     metrics = pipeline_run._build_market(runners)

#     assert metrics["slots_place"] == 3
#     assert metrics["overround_place"] == pytest.approx(expected)


# def test_build_market_overround_place_falls_back_to_win_odds():
#     runners = [
#         {"odds": 2.0},
#         {"odds": 3.0, "odds_place": 1.7},
#         {"odds": 4.0},
#     ]

#     expected = (1.0 / 2.0) + (1.0 / 1.7) + (1.0 / 4.0)

#     metrics = pipeline_run._build_market(runners)
#     assert metrics["slots_place"] == 3
#     assert metrics["overround_place"] == pytest.approx(expected)


# def test_build_market_requires_win_coverage_threshold():
#     runners_low_coverage = [
#         {"odds": 2.0},
#         {"odds": 3.5},
#         {},
#         {"odds": 0.0},
#     ]

#     metrics_low = pipeline_run._build_market(runners_low_coverage)

#     assert metrics_low["runner_count_total"] == 4
#     assert metrics_low["runner_count_with_win_odds"] == 2
#     assert metrics_low["win_coverage_ratio"] == pytest.approx(0.5, abs=1e-4)
#     assert metrics_low["win_coverage_sufficient"] is False
#     assert "overround_win" not in metrics_low or metrics_low["overround_win"] is None

#     runners_high_coverage = [
#         {"odds": 2.0},
#         {"odds": 3.5},
#         {"odds": 5.0},
#         {},
#     ]

#     metrics_high = pipeline_run._build_market(runners_high_coverage)

#     expected_win_total = sum(
#         1.0 / runner["odds"]
#         for runner in runners_high_coverage
#         if runner.get("odds", 0) > 0
#     )

#     assert metrics_high["runner_count_total"] == 4
#     assert metrics_high["runner_count_with_win_odds"] == 3
#     assert metrics_high["win_coverage_ratio"] == pytest.approx(0.75, abs=1e-2)
#     assert metrics_high["win_coverage_sufficient"] is True
#     assert metrics_high["overround_win"] == pytest.approx(expected_win_total, abs=1e-4)
#     assert metrics_high["overround"] == pytest.approx(expected_win_total, abs=1e-4)


# def test_market_drift_signal_thresholds():
#
#
#     assert pipeline_run.market_drift_signal(3.0, 2.0, is_favorite=False) == 2
#
#
#     assert pipeline_run.market_drift_signal(2.0, 2.6, is_favorite=True) == -2
#
#
#     assert pipeline_run.market_drift_signal(10.0, 9.5, is_favorite=False) == 0


# def test_drift_missing_snapshots():
#
#
#     """Ensure drift dict reports ids absent from either snapshot."""
#
#
#     h30 = {"1": 2.0, "2": 3.0}
#
#
#     h5 = {"2": 3.1, "3": 4.0}
#
#
#     id2name = {"1": "A", "2": "B", "3": "C"}
#
#
#     res = compute_drift_dict(h30, h5, id2name)
#
#
#     assert set(res["missing_h30"]) == {"3"}
#
#
#     assert set(res["missing_h5"]) == {"1"}


# def test_drift_filtering_topn(tmp_path):
#
#
#     """Drifts should be filtered by ``top_n`` and ``min_delta``."""
#
#
#     h30 = {"1": 2.0, "2": 5.0, "3": 4.0, "4": 10.0}
#
#
#     h5 = {"1": 4.0, "2": 2.0, "3": 5.0, "4": 8.0}
#
#
#     id2name = {"1": "A", "2": "B", "3": "C", "4": "D"}
#
#
#     res = compute_drift_dict(h30, h5, id2name, top_n=1, min_delta=1.5)
#
#
#     diff = res["drift"]
#
#
#     assert len(diff) == 2
#
#
#     assert any(r["delta"] > 0 for r in diff)
#
#
#     assert any(r["delta"] < 0 for r in diff)
#
#
#     assert all(abs(r["delta"]) >= 1.5 for r in diff)


# def test_snapshot_cli(tmp_path):
#
#
#     """Ensure snapshot subcommand renames snapshot files correctly."""
#
#
#     src = tmp_path / "h30.json"
#
#     src.write_text("{}", encoding="utf-8")
#
#
#
#
#     cmd = [
#
#         sys.executable,
#
#         "pipeline_run.py",
#
#         "snapshot",
#
#         "--when",
#
#         "h30",
#
#         "--meeting",
#
#         "R1",
#
#         "--race",
#
#         "C1",
#
#         "--outdir",
#
#         str(tmp_path),
#
#     ]
#
#     res = subprocess.run(cmd, capture_output=True, text=True)
#
#     assert res.returncode == 0, res.stderr
#
#
#
#
#     dest = tmp_path / "R1C1-h30.json"
#
#     assert dest.exists()
#
#     assert json.loads(dest.read_text(encoding="utf-8")) == {{}}


# def test_smoke_run(tmp_path):
#
#
#     partants = partants_sample()
#
#     h30 = odds_h30()
#
#     h5 = odds_h5()
#
#     stats = stats_sample()
#
#
#
#     h30_path = tmp_path / "h30.json"
#
#     h5_path = tmp_path / "h5.json"
#
#     stats_path = tmp_path / "stats_je.json"
#
#     partants_path = tmp_path / "partants.json"
#
#     gpi_path = tmp_path / "gpi.yml"
#
#     outdir = tmp_path / "out"
#
#     diff_path = tmp_path / "diff.json"
#
#
#
#     h30_path.write_text(json.dumps(h30), encoding="utf-8")
#
#
#     h5_path.write_text(json.dumps(h5), encoding="utf-8")
#
#
#     stats_path.write_text(json.dumps(stats), encoding="utf-8")
#
#
#     partants_path.write_text(json.dumps(partants), encoding="utf-8")
#
#
#     gpi_path.write_text(GPI_YML, encoding="utf-8")
#
#
#
#     diff_path.write_text("{}", encoding="utf-8")
#
#
#
#
#     cmd = [
#
#         sys.executable,
#
#         "pipeline_run.py",
#
#         "analyse",
#
#         "--h30",
#
#         str(h30_path),
#
#         "--h5",
#
#         str(h5_path),
#
#         "--stats-je",
#
#         str(stats_path),
#
#         "--partants",
#
#         str(partants_path),
#
#         "--gpi",
#
#         str(gpi_path),
#
#         "--outdir",
#
#         str(outdir),
#
#         "--diff",
#
#         str(diff_path),
#
#         "--budget",
#
#         "5",
#
#         "--ev-global",
#
#         "0.35",
#
#         "--roi-global",
#
#         "0.25",
#
#         "--max-vol",
#
#         "0.60",
#
#         "--allow-je-na",
#
#     ]
#
#     res = subprocess.run(cmd, capture_output=True, text=True)
#
#     assert res.returncode == 0, res.stderr
#
#
#
#     # artefacts
#
#     assert (outdir / "p_finale.json").exists()
#
#     assert (outdir / "diff_drift.json").exists()
#
#     assert (outdir / "ligne.csv").exists()
#
#     assert (outdir / "cmd_update_excel.txt").exists()
#
#     drift_csv = outdir / "drift.csv"
#
#     assert drift_csv.exists()
#
#     drift_rows = drift_csv.read_text(encoding="utf-8").strip().splitlines()
#
#     assert drift_rows
#
#     assert drift_rows[0] == "num;p30;p5;delta;flag"
#
#
#
#     data = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
#
#     assert data["meta"].get("validation") == {"ok": True, "reason": ""}
#
#     assert data["meta"]["snapshots"] == "H30,H5"
#
#     assert data["meta"]["drift_top_n"] == 5
#
#     assert data["meta"]["drift_min_delta"] == 0.8
#
#     market_meta = data["meta"].get("market", {{}})
#
#     assert market_meta.get("overround") is not None
#
#     if market_meta.get("overround") is not None:
#
#         expected_market_overround = sum(
#
#             1.0 / horse["odds"]
#
#             for horse in partants["market"]["horses"]
#
#         )
#
#         assert market_meta["overround"] == pytest.approx(expected_market_overround, abs=1e-4)
#
#     diff_params = json.loads(
#
#         (outdir / "diff_drift.json").read_text(encoding="utf-8")
#
#     )["params"]
#
#     assert diff_params == {"snapshots": "H30,H5", "top_n": 5, "min_delta": 0.8}
#
#     tickets = data["tickets"]
#
#     assert len(tickets) <= 1
#
#     stake_total = sum(t.get("stake", 0) for t in tickets)
#
#     assert stake_total <= 5.00 + 1e-6

#     ev_sum = sum(t.get("ev_ticket", 0) for t in tickets)
#
#     assert data["ev"]["sp"] == pytest.approx(ev_sum)
#
#     roi_sp = ev_sum / stake_total if stake_total else 0.0
#
#     assert data["ev"]["roi_sp"] == pytest.approx(roi_sp)

#     stake_reduction = data["ev"].get("stake_reduction", {{}})
#
#     assert data["ev"].get("stake_reduction_applied") is False
#
#     assert stake_reduction.get("applied") is False
#
#     scale_factor = stake_reduction.get("scale_factor")
#
#     if scale_factor is not None:
#
#         assert scale_factor == pytest.approx(1.0)
#
#     assert set(stake_reduction).issuperset({"applied", "initial", "final"})

#
#
#     initial_metrics = stake_reduction.get("initial", {{}})
#
#     final_metrics = stake_reduction.get("final", {{}})
#
#     assert "risk_of_ruin" in initial_metrics
#
#     assert "risk_of_ruin" in final_metrics
#
#     if stake_reduction.get("initial_cap") is not None:
#
#         assert stake_reduction["initial_cap"] == pytest.approx(0.60, abs=1e-6)
#
#     if stake_reduction.get("effective_cap") is not None:
#
#         assert stake_reduction["effective_cap"] == pytest.approx(
#
#             stake_reduction.get("initial_cap", stake_reduction["effective_cap"])
#
#         )
#
#     if stake_reduction.get("iterations") is not None:
#
#         assert stake_reduction["iterations"] in (0,)


#
#     if tickets:
#
#         stats_ev = simulate_ev_batch(tickets, bankroll=5)
#
#     else:
#
#         stats_ev = {"ev": 0.0, "roi": 0.0, "risk_of_ruin": 0.0, "clv": 0.0}
#
#     assert data["ev"]["global"] == pytest.approx(stats_ev.get("ev", 0.0))
#
#     assert data["ev"]["roi_global"] == pytest.approx(stats_ev.get("roi", 0.0))
#
#     assert data["ev"]["risk_of_ruin"] == pytest.approx(
#
#         stats_ev.get("risk_of_ruin", 0.0)
#
#     )
#
#     assert data["ev"]["clv_moyen"] == pytest.approx(stats_ev.get("clv", 0.0))
#
#     cfg_full = yaml.safe_load(GPI_YML)
#
#     assert cfg_full["MIN_STAKE_SP"] == 0.10
#
#     assert cfg_full["ROUND_TO_SP"] == 0.10
#
#     assert cfg_full["KELLY_FRACTION"] == 0.5
#
#     assert cfg_full["EV_MIN_SP_HOMOGENEOUS"] == 0.10
#
#     assert cfg_full["ROI_MIN_SP"] == 0.10
#
#     assert cfg_full["ROI_MIN_GLOBAL"] == 0.25
#
#     assert cfg_full["SHARPE_MIN"] == 0.5
#
#     # Ensure selected ticket has the highest individual EV
#
#     cfg_full = yaml.safe_load(GPI_YML)
#
#     cfg_full["MIN_STAKE_SP"] = 0.1
#
#     p_true = build_p_true(cfg_full, partants["runners"], h5, h30, stats)
#
#     runners = [
#
#         {
#
#             "id": str(r["id"]),
#
#             "name": r.get("name", str(r["id"])),
#
#             "odds": float(h5[str(r["id"])]) if str(r["id"]) in h5 else 0.0,
#
#             "p": float(p_true[str(r["id"])]) if str(r["id"]) in p_true else 0.0,
#
#         }
#
#         for r in partants["runners"]
#
#         if str(r["id"]) in h5 and str(r["id"]) in p_true
#
#     ]
#
#     exp_tickets, _ = allocate_dutching_sp(cfg_full, runners)
#
#     exp_tickets.sort(key=lambda t: t["ev_ticket"], reverse=True)
#
#     if tickets:
#
#         assert tickets[0]["id"] == exp_tickets[0]["id"]


#
#
#     # Combined payout is zero -> combo flag should be False and a high ROI
#
#     # threshold should block SP tickets
#
#     cfg = {{
#
#         "BUDGET_TOTAL": 5,
#
#         "SP_RATIO": 0.6,
#
#         "EV_MIN_SP": 0.0,
#
#         "EV_MIN_GLOBAL": 0.0,
#
#         "ROI_MIN_SP": 0.5,
#
#         "ROI_MIN_GLOBAL": 0.5,
#
#         "MIN_PAYOUT_COMBOS": 12.0,
#
#         "ROR_MAX": 1.0,
#
#     }}
#
#     stats_ev = simulate_ev_batch(tickets, bankroll=cfg["BUDGET_TOTAL"])
#
#     flags = gate_ev(
#
#         cfg,
#
#         ev_sp=float(data["ev"]["sp"]),
#
#         ev_global=float(data["ev"]["global"]),
#
#         roi_sp=roi_sp,
#
#         roi_global=stats_ev.get("roi", 0.0),
#
#         min_payout_combos=stats_ev.get("combined_expected_payout", 0.0),
#
#         risk_of_ruin=stats_ev.get("risk_of_ruin", 0.0),
#
#     )
#
#     assert not flags["sp"]
#
#     assert not flags["combo"]


#
#
#     cfg_ror = {{
#
#         "BUDGET_TOTAL": 5,
#
#         "SP_RATIO": 0.6,
#
#         "EV_MIN_SP": 0.0,
#
#         "EV_MIN_GLOBAL": 0.0,
#
#         "ROI_MIN_SP": 0.0,
#
#         "ROI_MIN_GLOBAL": 0.0,
#
#         "MIN_PAYOUT_COMBOS": 0.0,
#
#         "ROR_MAX": 0.0,
#
#     }}
#
#     flags_ror = gate_ev(
#
#         cfg_ror,
#
#         ev_sp=float(data["ev"]["sp"]),
#
#         ev_global=float(data["ev"]["global"]),
#
#         roi_sp=roi_sp,
#
#         roi_global=stats_ev.get("roi", 0.0),
#
#         min_payout_combos=stats_ev.get("combined_expected_payout", 0.0),
#
#         risk_of_ruin=stats_ev.get("risk_of_ruin", 0.0),
#
#     )
#
#     assert not flags_ror["sp"]
#
#     assert not flags_ror["combo"]


# def test_cmd_analyse_enriches_runners(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
#
#
#     partants = partants_sample()
#
#     h30 = odds_h30()
#
#     h5 = odds_h5()
#
#     stats = stats_sample()
#
#     stats["1"]["last2_top3"] = 1
#
#     stats["2"]["last2_top3"] = False
#
#
#
#
#     h30_path = tmp_path / "h30.json"
#
#     h5_path = tmp_path / "h5.json"
#
#     stats_path = tmp_path / "stats.json"
#
#     partants_path = tmp_path / "partants.json"
#
#     gpi_path = tmp_path / "gpi.yml"
#
#     diff_path = tmp_path / "diff.json"
#
#     outdir = tmp_path / "out"
#
#
#
#     h30_path.write_text(json.dumps(h30), encoding="utf-8")
#
#
#     h5_path.write_text(json.dumps(h5), encoding="utf-8")
#
#
#     stats_path.write_text(json.dumps(stats), encoding="utf-8")
#
#
#     partants_path.write_text(json.dumps(partants), encoding="utf-8")
#
#
#     gpi_path.write_text(GPI_YML, encoding="utf-8")
#
#     diff_path.write_text("{}", encoding="utf-8")
#
#
#
#     ids = [str(runner["id"]) for runner in partants["runners"]]
#
#     probs_h5 = implied_probs([h5[cid] for cid in ids])
#
#     probs_h30 = implied_probs([h30[cid] for cid in ids])
#
#     expected_h5 = dict(zip(ids, probs_h5))
#
#     expected_h30 = dict(zip(ids, probs_h30))
#
#
#
#     monkeypatch.setattr(
#
#         "pipeline_run.build_p_true", lambda *a, **k: {cid: 1 / len(ids) for cid in ids}
#
#     )
#
#
#
#     captured: dict[str, list[dict]] = {{}}
#
#
#
#     def stub_apply_ticket_policy(cfg, runners, combo_candidates=None, combos_source=None):
#
#         captured["apply"] = [dict(r) for r in runners]
#
#         return [], [], {{}}
#
#
#
#     def stub_enforce(cfg, runners, combo_tickets, bankroll, **kwargs):
#
#         captured["enforce"] = [dict(r) for r in runners]
#
#         stats_stub = {{
#
#             "ev": 0.0,
#
#             "roi": 0.0,
#
#             "risk_of_ruin": 0.0,
#
#             "combined_expected_payout": 0.0,
#
#             "ev_over_std": 0.0,
#
#             "variance": 0.0,
#
#             "clv": 0.0,
#
#             "green": False,
#
#         }}
#
#         return [], stats_stub, {{"applied": False}}
#
#
#
#     monkeypatch.setattr("tickets_builder.apply_ticket_policy", stub_apply_ticket_policy)
#
#     monkeypatch.setattr("pipeline_run.enforce_ror_threshold", stub_enforce)
#
#     monkeypatch.setattr("pipeline_run.append_csv_line", lambda *a, **k: None)
#
#     monkeypatch.setattr("pipeline_run.append_json", lambda *a, **k: None)
#
#     monkeypatch.setattr(logging_io, "append_csv_line", lambda *a, **k: None)
#
#     monkeypatch.setattr(logging_io, "append_json", lambda *a, **k: None)
#
#
#
#     args = argparse.Namespace(
#
#         h30=str(h30_path),
#
#         h5=str(h5_path),
#
#         stats_je=str(stats_path),
#
#         partants=str(partants_path),
#
#         gpi=str(gpi_path),
#
#         outdir=str(outdir),
#
#         diff=str(diff_path),
#
#         budget=None,
#
#         ev_global=None,
#
#         roi_global=None,
#
#         max_vol=None,
#
#         min_payout=None,
#
#         ev_min_exotic=None,
#
#         payout_min_exotic=None,
#
#         allow_heuristic=False,
#
#         allow_je_na=True,
#
#         calibration=DEFAULT_CALIBRATION,
#
#     )
#
#
#
#     pipeline_run.cmd_analyse(args)
#
#
#
#     assert "apply" in captured and "enforce" in captured
#
#     runners_apply = captured["apply"]
#
#     runners_enforce = captured["enforce"]
#
#     assert runners_apply == runners_enforce
#
#
#
#     assert runners_apply, "expected runners to be passed to allocation"
#
#     for runner in runners_apply:
#
#         cid = runner["id"]
#
#         assert "p_imp_h5" in runner
#
#         assert "p_imp_h30" in runner
#
#         assert "drift_score" in runner
#
#         assert "last2_top3" in runner
#
#         assert runner["p_imp_h5"] == pytest.approx(expected_h5[cid])
#
#         assert runner["p_imp_h30"] == pytest.approx(expected_h30.get(cid, expected_h5[cid]))
#
#         drift_expected = h5[cid] - h30.get(cid, h5[cid])
#
#         prob_expected = pipeline_run.drift_points(h30.get(cid), h5[cid])
#
#         assert runner["drift_odds_delta"] == pytest.approx(drift_expected)
#
#         assert runner["drift_prob_delta"] == pytest.approx(prob_expected)
#
#         assert runner["drift_score"] == pytest.approx(prob_expected)
#
#
#
#     signals = {runner["id"]: runner["market_signal"] for runner in runners_apply}
#
#     assert signals["1"] == -2  # favourite drifting negatively
#
#     assert all(signal in {-2, 0, 2} for signal in signals.values())
#
#
#
#     last2_flags = {runner["id"]: runner["last2_top3"] for runner in runners_apply}
#
#     assert last2_flags["1"] is True
#
#     assert last2_flags["3"] is False


# def test_pipeline_validation_failure_reports_summary(tmp_path, monkeypatch):
#
#
#     invalid_partants = partants_sample()
#
#     invalid_partants["runners"] = invalid_partants["runners"][:5]
#
#
#
#     h30_path = tmp_path / "h30.json"
#
#     h5_path = tmp_path / "h5.json"
#
#     stats_path = tmp_path / "stats_je.json"
#
#     partants_path = tmp_path / "partants.json"
#
#     gpi_path = tmp_path / "gpi.yml"
#
#
#
#     h30_path.write_text(json.dumps(odds_h30()), encoding="utf-8")
#
#     h5_path.write_text(json.dumps(odds_h5()), encoding="utf-8")
#
#     stats_path.write_text(json.dumps(stats_sample()), encoding="utf-8")
#
#     partants_path.write_text(json.dumps(invalid_partants), encoding="utf-8")
#
#     gpi_path.write_text(GPI_YML, encoding="utf-8")
#
#
#
#     captured_summary: dict[str, object] = {{}}
#
#     real_summary = validator_ev.summarise_validation
#
#
#
#     def recording_summary(*validators):
#
#         result = real_summary(*validators)
#
#         captured_summary.clear()
#
#         captured_summary.update(result)
#
#         return result
#
#
#
#     monkeypatch.setattr(validator_ev, "summarise_validation", recording_summary)
#
#
#
#     args = argparse.Namespace(
#
#         h30=str(h30_path),
#
#         h5=str(h5_path),
#
#         stats_je=str(stats_path),
#
#         partants=str(partants_path),
#
#         gpi=str(gpi_path),
#
#         outdir=str(tmp_path / "out"),
#
#         diff=None,
#
#         budget=None,
#
#         ev_global=None,
#
#         roi_global=None,
#
#         max_vol=None,
#
#         min_payout=None,
#
#         ev_min_exotic=None,
#
#         payout_min_exotic=None,
#
#         allow_heuristic=False,
#
#         allow_je_na=False,
#
#         calibration=DEFAULT_CALIBRATION,
#
#     )
#
#
#
#     with pytest.raises(validator_ev.ValidationError, match="Nombre de partants"):
#
#         pipeline_run.cmd_analyse(args)
#
#
#
#     assert captured_summary.get("ok") is False
#
#     assert "partants" in str(captured_summary.get("reason", "")).lower()


# def test_reallocate_combo_budget_to_sp(tmp_path):
#
#
#     partants = partants_sample()
#
#     h30 = odds_h30()
#
#     h5 = odds_h5()
#
#     stats = stats_sample()
#
#     stats["4"] = {"j_win": 5000, "e_win": 0}
#
#
#
#     h30_path = tmp_path / "h30.json"
#
#     h5_path = tmp_path / "h5.json"
#
#     stats_path = tmp_path / "stats_je.json"
#
#     partants_path = tmp_path / "partants.json"
#
#     gpi_path = tmp_path / "gpi.yml"
#
#     outdir = tmp_path / "out"
#
#
#
#     h30_path.write_text(json.dumps(h30), encoding="utf-8")
#
#     h5_path.write_text(json.dumps(h5), encoding="utf-8")
#
#     stats_path.write_text(json.dumps(stats), encoding="utf-8")
#
#     partants_path.write_text(json.dumps(partants), encoding="utf-8")
#
#
#
#     gpi_txt = (
#
#         GPI_YML.replace("EV_MIN_SP: 0.15", "EV_MIN_SP: 0.0")
#
#         .replace("EV_MIN_GLOBAL: 0.35", "EV_MIN_GLOBAL: 10.0")
#
#         .replace("ROR_MAX: 0.05", "ROR_MAX: 1.0")
#
#     )
#
#     gpi_path.write_text(gpi_txt, encoding="utf-8")
#
#
#
#     diff_path = tmp_path / "diff.json"
#
#     diff_path.write_text("{}", encoding="utf-8")
#
#
#
#     cmd = [
#
#         sys.executable,
#
#         "pipeline_run.py",
#
#         "analyse",
#
#         "--h30",
#
#         str(h30_path),
#
#         "--h5",
#
#         str(h5_path),
#
#         "--stats-je",
#
#         str(stats_path),
#
#         "--partants",
#
#         str(partants_path),
#
#         "--gpi",
#
#         str(gpi_path),
#
#         "--outdir",
#
#         str(outdir),
#
#         "--diff",
#
#         str(diff_path),
#
#         "--budget",
#
#         "5",
#
#         "--ev-global",
#
#         "10.0",
#
#         "--roi-global",
#
#         "0.25",
#
#         "--max-vol",
#
#         "0.60",
#
#         "--allow-je-na",
#
#     ]
#
#     res = subprocess.run(cmd, capture_output=True, text=True)
#
#     assert res.returncode == 0, res.stderr
#
#     assert "Blocage combinés" in res.stdout
#
#
#
#     data = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
#
#     tickets = data["tickets"]
#
#     if not tickets:
#
#         notes = data.get("meta", {{}}).get("notes", [])
#
#         assert any("SP retiré" in note for note in notes), notes
#
#         return
#
#
#
#     # Expected allocation when combo budget is reassigned to SP
#
#     cfg_full = yaml.safe_load(gpi_txt)
#
#     assert cfg_full["MIN_STAKE_SP"] == 0.10
#
#     assert cfg_full["ROUND_TO_SP"] == 0.10
#
#     assert cfg_full["KELLY_FRACTION"] == 0.5
#
#     assert cfg_full["EV_MIN_SP_HOMOGENEOUS"] == 0.10
#
#     assert cfg_full["ROI_MIN_SP"] == 0.10
#
#     assert cfg_full["ROI_MIN_GLOBAL"] == 0.25
#
#     assert cfg_full["SHARPE_MIN"] == 0.5
#
#     p_true = build_p_true(cfg_full, partants["runners"], h5, h30, stats)
#
#     runners = [
#
#         {
#
#             "id": str(r["id"]),
#
#             "name": r.get("name", str(r["id"])),
#
#             "odds": float(h5[str(r["id"])]) if str(r["id"]) in h5 else 0.0,
#
#             "p": float(p_true[str(r["id"])]) if str(r["id"]) in p_true else 0.0,
#
#         }
#
#         for r in partants["runners"]
#
#         if str(r["id"]) in h5 and str(r["id"]) in p_true
#
#     ]
#
#     cfg_full_sp = dict(cfg_full)
#
#     cfg_full_sp["SP_RATIO"] = cfg_full["SP_RATIO"] + cfg_full["COMBO_RATIO"]
#
#     exp_tickets, _ = allocate_dutching_sp(cfg_full_sp, runners)
#
#     exp_tickets.sort(key=lambda t: t["ev_ticket"], reverse=True)
#
#     assert tickets[0]["ev_ticket"] == pytest.approx(exp_tickets[0]["ev_ticket"])


# def test_high_risk_pack_is_trimmed(tmp_path, monkeypatch):
#
#
#     partants = {{
#
#         "rc": "R1C1",
#
#         "hippodrome": "Test",
#
#         "date": "2025-09-10",
#
#         "discipline": "trot",
#
#         "runners": [
#
#             {"id": "1", "name": "Alpha", "odds_place": 1.6, "odds_place_h30": 1.55},
#
#             {"id": "2", "name": "Bravo", "odds_place": 1.7, "odds_place_h30": 1.65},
#
#             {"id": "3", "name": "Charlie", "odds_place": 1.8, "odds_place_h30": 1.75},
#
#             {"id": "4", "name": "Delta", "odds_place": 2.1, "odds_place_h30": 2.0},
#
#             {"id": "5", "name": "Echo", "odds_place": 2.6, "odds_place_h30": 2.5},
#
#             {"id": "6", "name": "Foxtrot", "odds_place": 3.2, "odds_place_h30": 3.1},
#
#         ],
#
#     }}
#
#     h30 = {{str(i): 2.0 + 0.4 * i for i in range(1, 7)}}
#
#     h5 = {{str(i): 2.0 + 0.5 * i for i in range(1, 7)}}
#
#     stats = {{str(i): {{"j_win": 0, "e_win": 0}} for i in range(1, 7)}}
#
#
#
#     gpi_txt = (
#
#         GPI_YML
#
#         .replace("BUDGET_TOTAL: 5", "BUDGET_TOTAL: 100")
#
#         .replace("SP_RATIO: 0.6", "SP_RATIO: 1.0")
#
#         .replace("COMBO_RATIO: 0.4", "COMBO_RATIO: 0.0")
#
#         .replace("EV_MIN_SP: 0.15", "EV_MIN_SP: 0.0")
#
#         .replace("EV_MIN_GLOBAL: 0.35", "EV_MIN_GLOBAL: 0.0")
#
#         .replace("ROI_MIN_GLOBAL: 0.25", "ROI_MIN_GLOBAL: 0.0")
#
#         .replace("ROR_MAX: 0.05", "ROR_MAX: 0.01")
#
#         .replace("MAX_VOL_PAR_CHEVAL: 0.60", "MAX_VOL_PAR_CHEVAL: 0.90")
#
#         .replace("SHARPE_MIN: 0.5", "SHARPE_MIN: 0.0")
#
#         .replace("KELLY_FRACTION: 0.5", "KELLY_FRACTION: 1.0")
#
#     )
#
#
#
#     h30_path = tmp_path / "h30.json"
#
#     h5_path = tmp_path / "h5.json"
#
#     stats_path = tmp_path / "stats.json"
#
#     partants_path = tmp_path / "partants.json"
#
#     gpi_path = tmp_path / "gpi.yml"
#
#     diff_path = tmp_path / "diff.json"
#
#     outdir = tmp_path / "out"
#
#
#
#     h30_path.write_text(json.dumps(h30), encoding="utf-8")
#
#     h5_path.write_text(json.dumps(h5), encoding="utf-8")
#
#     stats_path.write_text(json.dumps(stats), encoding="utf-8")
#
#     partants_path.write_text(json.dumps(partants), encoding="utf-8")
#
#     gpi_path.write_text(gpi_txt, encoding="utf-8")
#
#     diff_path.write_text("{}", encoding="utf-8")
#
#
#
#     p_stub = {"1": 0.55, "2": 0.1, "3": 0.1, "4": 0.1, "5": 0.1, "6": 0.05}
#
#
#
#     monkeypatch.setattr("pipeline_run.build_p_true", lambda *a, **k: dict(p_stub))
#
#
#
#     def fake_apply_ticket_policy(cfg, runners, combo_candidates=None, combos_source=None):
#
#         tickets, _ = allocate_dutching_sp(cfg, runners)
#
#         return tickets, [], None
#
#
#
#     monkeypatch.setattr("pipeline_run.apply_ticket_policy", fake_apply_ticket_policy)
#
#
#
#     cfg_loaded = load_yaml(str(gpi_path))
#
#     runners = [
#
#         {
#
#             "id": str(runner["id"]),
#
#             "name": runner["name"],
#
#             "odds": float(h5[str(runner["id"])]) if str(runner["id"]) in h5 else 0.0,
#
#             "p": p_stub[str(runner["id"])],
#
#             "odds_place": runner.get("odds_place", 0.0),
#
#         }
#
#         for runner in partants["runners"]
#
#     ]
#
#     baseline_tickets, _ = allocate_dutching_sp(cfg_loaded, runners)
#
#     baseline_stake = sum(t["stake"] for t in baseline_tickets)
#
#     assert baseline_tickets, "expected baseline allocation"
#
#     baseline_by_id = {t["id"]: t["stake"] for t in baseline_tickets}
#
#
#
#     args = argparse.Namespace(
#
#         h30=str(h30_path),
#
#         h5=str(h5_path),
#
#         stats_je=str(stats_path),
#
#         partants=str(partants_path),
#
#         gpi=str(gpi_path),
#
#         outdir=str(outdir),
#
#         diff=str(diff_path),
#
#         budget=None,
#
#         ev_global=None,
#
#         roi_global=None,
#
#         max_vol=None,
#
#         min_payout=None,
#
#         ev_min_exotic=None,
#
#         payout_min_exotic=None,
#
#         allow_heuristic=False,
#
#         allow_je_na=True,
#
#         calibration=DEFAULT_CALIBRATION,
#
#     )
#
#
#
#     pipeline_run.cmd_analyse(args)
#
#
#
#     data = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
#
#     tickets = data["tickets"]
#
#     if not tickets:
#
#         notes = data.get("meta", {{}}).get("notes", [])
#
#         assert any("SP retiré" in note for note in notes), notes
#
#         return
#
#
#
#     final_stake = sum(t["stake"] for t in tickets)
#
#     assert final_stake < baseline_stake
#
#     for ticket in tickets:
#
#         assert ticket["stake"] < baseline_by_id.get(ticket["id"], float("inf"))
#
#
#
#     stake_reduction = data["ev"]["stake_reduction"]
#
#     assert data["ev"]["stake_reduction_applied"] is True
#
#     assert stake_reduction["applied"] is True
#
#     assert stake_reduction["scale_factor"] < 1.0
#
#     assert stake_reduction["effective_cap"] < stake_reduction["initial_cap"]
#
#     assert stake_reduction["iterations"] >= 1
#
#
#
#     initial_metrics = stake_reduction["initial"]
#
#     final_metrics = stake_reduction["final"]
#
#     target_ror = stake_reduction.get("target") or cfg_loaded["ROR_MAX"]
#
#     assert initial_metrics["risk_of_ruin"] > target_ror
#
#     assert final_metrics["risk_of_ruin"] <= target_ror + 1e-9
#
#
#
#     current_cap = stake_reduction.get("effective_cap")
#
#     if not current_cap:
#
#         current_cap = cfg_loaded.get("MAX_VOL_PAR_CHEVAL", 0.60)
#
#
#
#     stats_ev = simulate_ev_batch(
#
#         tickets,
#
#         bankroll=cfg_loaded["BUDGET_TOTAL"],
#
#         kelly_cap=current_cap,
#
#     )
#
#     assert data["ev"]["risk_of_ruin"] == pytest.approx(stats_ev["risk_of_ruin"])
#
#     assert stats_ev["risk_of_ruin"] <= cfg_loaded["ROR_MAX"] + 1e-9


# def test_combo_pack_scaled_not_removed(tmp_path, monkeypatch):
#
#
#     partants = partants_sample()
#
#     h30 = odds_h30()
#
#     h5 = odds_h5()
#
#     stats = stats_sample()
#
#
#
#     h30_path = tmp_path / "h30.json"
#
#     h5_path = tmp_path / "h5.json"
#
#     stats_path = tmp_path / "stats.json"
#
#     partants_path = tmp_path / "partants.json"
#
#     gpi_path = tmp_path / "gpi.yml"
#
#     diff_path = tmp_path / "diff.json"
#
#     outdir = tmp_path / "out"
#
#
#
#     h30_path.write_text(json.dumps(h30), encoding="utf-8")
#
#     h5_path.write_text(json.dumps(h5), encoding="utf-8")
#
#     stats_path.write_text(json.dumps(stats), encoding="utf-8")
#
#     partants_path.write_text(json.dumps(partants), encoding="utf-8")
#
#
#
#     gpi_txt = (
#
#         GPI_YML
#
#         .replace("BUDGET_TOTAL: 5", "BUDGET_TOTAL: 100")
#
#         .replace("SP_RATIO: 0.6", "SP_RATIO: 0.5")
#
#         .replace("COMBO_RATIO: 0.4", "COMBO_RATIO: 0.5")
#
#         .replace("EV_MIN_SP: 0.15", "EV_MIN_SP: 0.0")
#
#         .replace("EV_MIN_GLOBAL: 0.35", "EV_MIN_GLOBAL: 0.0")
#
#         .replace("ROI_MIN_GLOBAL: 0.25", "ROI_MIN_GLOBAL: 0.0")
#
#         .replace("MIN_PAYOUT_COMBOS: 12.0", "MIN_PAYOUT_COMBOS: 0.0")
#
#         .replace("ROR_MAX: 0.05", "ROR_MAX: 0.02")
#
#         .replace("MAX_VOL_PAR_CHEVAL: 0.60", "MAX_VOL_PAR_CHEVAL: 0.90")
#
#         .replace("SHARPE_MIN: 0.5", "SHARPE_MIN: 0.0")
#
#     )
#
#     gpi_path.write_text(gpi_txt, encoding="utf-8")
#
#     diff_path.write_text("{}", encoding="utf-8")
#
#
#
#     monkeypatch.setattr("pipeline_run.allow_combo", lambda *a, **k: True)
#
#     monkeypatch.setattr("pipeline_run.build_p_true", lambda *a, **k: {str(i): 1 / 6 for i in range(1, 7)})
#
#
#
#     cfg_loaded = load_yaml(str(gpi_path))
#
#
#
#     sp_ticket = {{
#
#         "type": "SP",
#
#         "id": "1",
#
#         "name": "A",
#
#         "odds": 2.0,
#
#         "p": 0.55,
#
#         "stake": 50.0,
#
#         "ev_ticket": 50.0 * (0.55 * (2.0 - 1.0) - (1.0 - 0.55)),
#
#     }}
#
#     combo_template = {{
#
#         "type": "CP",
#
#         "id": "combo1",
#
#         "p": 0.21,
#
#         "odds": 5.0,
#
#         "stake": 1.0,
#
#         "ev_ticket": 1.0 * (0.21 * (5.0 - 1.0) - (1.0 - 0.21)),
#
#     }}
#
#
#
#     def stub_apply_ticket_policy(cfg, runners, combo_candidates=None, combos_source=None):
#
#         return [dict(sp_ticket)], [dict(combo_template)], {{"notes": [], "flags": {{}}}}
#
#
#
#     monkeypatch.setattr("pipeline_run.apply_ticket_policy", stub_apply_ticket_policy)
#
#
#
#     args = argparse.Namespace(
#
#         h30=str(h30_path),
#
#         h5=str(h5_path),
#
#         stats_je=str(stats_path),
#
#         partants=str(partants_path),
#
#         gpi=str(gpi_path),
#
#         outdir=str(outdir),
#
#         diff=str(diff_path),
#
#         budget=None,
#
#         ev_global=None,
#
#         roi_global=None,
#
#         max_vol=None,
#
#         min_payout=None,
#
#         ev_min_exotic=None,
#
#         payout_min_exotic=None,
#
#         allow_heuristic=False,
#
#         allow_je_na=True,
#
#         calibration=DEFAULT_CALIBRATION,
#
#     )
#
#
#
#     pipeline_run.cmd_analyse(args)
#
#
#
#     data = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
#
#     tickets = data["tickets"]
#
#
#
#     if not tickets:
#
#         notes = data.get("meta", {{}}).get("notes", [])
#
#         assert any("SP retiré" in note for note in notes), notes
#
#         return
#
#     assert all(t.get("type") == "SP" for t in tickets)
#
#     assert data["ev"]["combined_expected_payout"] < 12.0
#
#
#
#     stake_reduction = data["ev"]["stake_reduction"]
#
#     assert data["ev"]["stake_reduction_applied"] is True
#
#     assert stake_reduction["applied"] is True
#
#
#
#     final_ror = data["ev"]["risk_of_ruin"]
#
#     target_ror = stake_reduction.get("target") or 0.02
#
#     assert final_ror <= target_ror + 1e-9
#
#
#
#     scale_factor = stake_reduction["scale_factor"]
#
#     assert scale_factor < 1.0
#
#     assert stake_reduction["effective_cap"] < stake_reduction["initial_cap"]
#
#     assert stake_reduction["iterations"] >= 1
#
#
#
#     initial_metrics = stake_reduction["initial"]
#
#     final_metrics = stake_reduction["final"]
#
#     assert initial_metrics["risk_of_ruin"] > target_ror
#
#     assert final_metrics["risk_of_ruin"] == pytest.approx(final_ror)
#
#
#
#     sp_stake_total = sum(t["stake"] for t in tickets)
#
#     assert sp_stake_total > 0.0
#
#     final_total = sp_stake_total
#
#     assert final_total == pytest.approx(stake_reduction["final"]["total_stake"])
#
#
#
#     initial_total = stake_reduction["initial"]["total_stake"]
#
#     assert initial_total > final_total
#
#     assert final_total == pytest.approx(initial_total * scale_factor, rel=1e-2)
#
#
#
#     current_cap = stake_reduction.get("effective_cap")
#
#     if not current_cap:
#
#         current_cap = cfg_loaded.get("MAX_VOL_PAR_CHEVAL", 0.60)
#
#     stats_ev = simulate_ev_batch(
#
#         tickets,
#
#         bankroll=cfg_loaded["BUDGET_TOTAL"],
#
#         kelly_cap=current_cap,
#
#     )
#
#     assert data["ev"]["risk_of_ruin"] == pytest.approx(stats_ev["risk_of_ruin"])
#
#     assert stats_ev["risk_of_ruin"] <= target_ror + 1e-9
