import argparse
import json
import sys
from pathlib import Path

import pytest

import logging_io
import pipeline_run
import simulate_ev
import simulate_wrapper
import tickets_builder
import runner_chain
from test_pipeline_smoke import (
    GPI_YML,
    odds_h30,
    odds_h5,
    partants_sample,
    stats_sample,
)


def _with_exotics(partants: dict) -> dict:
    combos = {
        "CP": [
            {"id": "cp-alpha", "legs": ["5", "6"], "odds": 6.0, "stake": 1.0},
        ],
        "TRIO": [
            {"id": "trio-beta", "legs": ["1", "2", "3"], "odds": 15.0, "stake": 1.0},
        ],
    }
    enriched = dict(partants)
    enriched["exotics"] = combos
    return enriched


def _patch_simulation(monkeypatch, *, simulate_fn=None, gate_fn=None):
    pipeline_run._load_simulate_ev.cache_clear()
    if simulate_fn is not None:
        monkeypatch.setattr(simulate_ev, "simulate_ev_batch", simulate_fn)
    if gate_fn is not None:
        monkeypatch.setattr(simulate_ev, "gate_ev", gate_fn)
    pipeline_run._load_simulate_ev.cache_clear()
    return pipeline_run._load_simulate_ev.cache_clear
    

def _patch_combo_eval(monkeypatch, *, stats=None):
    default_stats = {
        "status": "ok",
        "ev_ratio": 0.6,
        "payout_expected": 25.0,
        "roi": 0.3,
        "sharpe": 0.5,
    }
    payload = dict(default_stats)
    if stats:
        payload.update(stats)

    def fake_eval(tickets, bankroll, calibration=None, allow_heuristic=False):
        result = dict(payload)
        result.setdefault("status", "ok")
        result.setdefault("ev_ratio", 0.0)
        result.setdefault("roi", 0.0)
        result.setdefault("payout_expected", 0.0)
        result.setdefault("sharpe", 0.0)
        return result

    monkeypatch.setattr(simulate_wrapper, "evaluate_combo", fake_eval)

def _write_inputs(
    tmp_path,
    partants,
    *,
    combo_ratio: float = 0.4,
    partants_filename: str = "partants.json",
):
    h30_path = tmp_path / "h30.json"
    h5_path = tmp_path / "h5.json"
    stats_path = tmp_path / "stats.json"
    partants_path = tmp_path / partants_filename
    gpi_path = tmp_path / "gpi.yml"
    diff_path = tmp_path / "diff.json"

    h30_path.write_text(json.dumps(odds_h30()), encoding="utf-8")
    h5_path.write_text(json.dumps(odds_h5()), encoding="utf-8")
    stats_path.write_text(json.dumps(stats_sample()), encoding="utf-8")
    partants_path.write_text(json.dumps(partants), encoding="utf-8")
        
    gpi_txt = (
        GPI_YML
        .replace("EV_MIN_GLOBAL: 0.35", "EV_MIN_GLOBAL: 0.0")
        .replace("EV_MIN_SP: 0.15", "EV_MIN_SP: 0.0")
        .replace("COMBO_RATIO: 0.4", f"COMBO_RATIO: {combo_ratio}")
        .replace("SHARPE_MIN: 0.5", "SHARPE_MIN: 0.0")
        + "MIN_PAYOUT_COMBOS: 0.0\nROR_MAX: 1.0\n"
    )
    gpi_path.write_text(gpi_txt, encoding="utf-8")
    diff_path.write_text("{}", encoding="utf-8")

    return {
        "h30": h30_path,
        "h5": h5_path,
        "stats": stats_path,
        "partants": partants_path,
        "gpi": gpi_path,
        "diff": diff_path,
    }


def _run_pipeline(tmp_path, inputs):
    outdir = tmp_path / "out"
    args = argparse.Namespace(
        h30=str(inputs["h30"]),
        h5=str(inputs["h5"]),
        stats_je=str(inputs["stats"]),
        partants=str(inputs["partants"]),
        gpi=str(inputs["gpi"]),
        outdir=str(outdir),
        diff=str(inputs["diff"]),
        budget=5,
        ev_global=0.0,
        roi_global=0.0,
        max_vol=0.60,
        allow_je_na=True,
        analyse=True,
    )
    pipeline_run.run_pipeline(**vars(args))
    return outdir


def _mock_tracking_outputs(tmp_path, monkeypatch):
    tracking_path = tmp_path / "modele_suivi_courses_hippiques_clean.csv"

    original_append_csv_line = logging_io.append_csv_line
    original_append_json = logging_io.append_json
    
    def fake_append_csv_line(path, data, header=logging_io.CSV_HEADER):
        return original_append_csv_line(tracking_path, data, header=header)

    def fake_append_json(path, data):
        target = Path(path)
        if target.is_absolute():
            target = target.relative_to(target.anchor)
        target_path = tmp_path / target
        return original_append_json(target_path, data)

    monkeypatch.setattr(logging_io, "append_csv_line", fake_append_csv_line)
    monkeypatch.setattr(logging_io, "append_json", fake_append_json)

    return tracking_path

def _test_filter_sp_and_cp_tickets_apply_cp_threshold():
    runners = [
        {"id": "1", "odds": 2.2},
        {"id": "2", "odds": 3.1},
        {"id": "3", "odds": 3.2},
        {"id": "4", "odds": 3.2},
    ]
    partants = {"runners": runners}

    sp_ticket = {"type": "SP", "id": "5", "odds": 9.0, "stake": 1.0}
    sp_ticket_alt = {"type": "SP", "id": "6", "odds": 6.0, "stake": 1.0}
    combo_low = {"type": "CP", "legs": ["1", "2"], "stake": 1.0}
    combo_threshold = {"type": "CP", "legs": ["3", "4"], "stake": 1.0}

    sp_filtered, combo_filtered, notes = pipeline_run._filter_sp_and_cp_tickets(
        [sp_ticket, sp_ticket_alt],
        [combo_low, combo_threshold],
        runners,
        partants,
    )

    assert any(ticket["id"] == "5" for ticket in sp_filtered)
    assert combo_filtered == [combo_threshold]
    assert any("CP retiré" in str(note) for note in notes)


def _test_filter_sp_tickets_apply_sp_threshold():
    runners = [
        {"id": "1", "odds": 3.5},
        {"id": "2", "odds": 4.0},
    ]
    partants = {"runners": runners}

    sp_low = {"type": "SP", "id": "1", "odds": 3.9, "stake": 1.0}
    sp_threshold = {"type": "SP", "id": "2", "odds": 5.0, "stake": 1.0}
    sp_high = {"type": "SP", "id": "3", "odds": 6.0, "stake": 1.0}

    sp_filtered, combo_filtered, notes = pipeline_run._filter_sp_and_cp_tickets(
        [sp_low, sp_threshold, sp_high],
        [],
        runners,
        partants,
    )

    assert combo_filtered == []
    assert sorted(ticket["id"] for ticket in sp_filtered) == ["2", "3"]
    assert any("4/1" in str(note) for note in notes)

def _test_pipeline_respects_p_finale_override(tmp_path, monkeypatch):
    partants = partants_sample()
    market_payload = partants.get("market")
    if isinstance(market_payload, dict):
        for key in (
            "slots_place",
            "places_payees",
            "places_payees_h5",
            "paid_places",
            "paid_slots",
        ):
            market_payload.pop(key, None)
    inputs = _write_inputs(
        tmp_path,
        partants,
        partants_filename="R1C1_partants.json",
    )

    paid_places = 3.0
    p_true_override = {
        "1": 0.04,
        "2": 0.06,
        "3": 0.10,
        "4": 0.15,
        "5": 0.25,
        "6": 0.40,
    }
    p_place_raw = {
        "1": 0.05,
        "2": 0.10,
        "3": 0.20,
        "4": 0.30,
        "5": 0.15,
        "6": 0.20,
    }
    override_payload = {
        "p_true": p_true_override,
        "p_place": p_place_raw,
        "meta": {"market": {"slots_place": paid_places}},
    }
    override_path = inputs["partants"].with_name("R1C1_p_finale.json")
    override_path.write_text(json.dumps(override_payload), encoding="utf-8")

    _mock_tracking_outputs(tmp_path, monkeypatch)

    captured_pre: list[list[dict]] = []
    captured_post: list[list[dict]] = []

    def fake_allocate(cfg_local, runners):
        return [], 0.0

    def fake_simulate(tickets, bankroll, **kwargs):
        return {
            "ev": 0.0,
            "roi": 0.0,
            "combined_expected_payout": 0.0,
            "risk_of_ruin": 0.0,
            "variance": 0.0,
            "clv": 0.0,
        }

    def fake_gate(
        cfg,
        ev_sp,
        ev_global,
        roi_sp,
        roi_global,
        min_payout_combos,
        risk_of_ruin=0.0,
        ev_over_std=0.0,
        homogeneous_field=False,
    ):
        return {"sp": True, "combo": False, "reasons": {"sp": [], "combo": []}}

    original_ensure = pipeline_run._ensure_place_odds

    def capture_ensure(runners):
        captured_pre.append([dict(r) for r in runners])
        ensured = original_ensure(runners)
        captured_post.append([dict(r) for r in ensured])
        return ensured

    pipeline_run._load_simulate_ev.cache_clear()
    monkeypatch.setattr(simulate_ev, "allocate_dutching_sp", fake_allocate)
    monkeypatch.setattr(pipeline_run, "_ensure_place_odds", capture_ensure)
    cleanup = _patch_simulation(monkeypatch, simulate_fn=fake_simulate, gate_fn=fake_gate)
    try:
        outdir = _run_pipeline(tmp_path, inputs)
    finally:
        cleanup()

    assert captured_pre, "pre-ensure runners should be captured"
    pre_runners = captured_pre[0]
    assert pre_runners, "expected at least one runner"
    pre_by_id = {runner["id"]: runner for runner in pre_runners}

    scale = paid_places / sum(p_place_raw.values())
    total_place = 0.0
    for cid, raw in p_place_raw.items():
        expected_place = raw * scale
        runner = pre_by_id[cid]
        assert runner["p"] == pytest.approx(p_true_override[cid])
        assert runner["p_place"] == pytest.approx(expected_place)
        probabilities = runner.get("probabilities", {})
        assert probabilities.get("p_place") == pytest.approx(expected_place)
        total_place += runner["p_place"]
    assert total_place == pytest.approx(paid_places)

    assert captured_post, "post-ensure runners should be captured"
    post_runners = captured_post[0]
    assert post_runners, "expected at least one sanitized runner"
    post_by_id = {runner["id"]: runner for runner in post_runners}
    total_post_place = 0.0
    for cid, raw in p_place_raw.items():
        expected_place = raw * scale
        sanitized_runner = post_by_id[cid]
        assert sanitized_runner["p_place"] == pytest.approx(expected_place)
        total_post_place += sanitized_runner["p_place"]
    assert total_post_place == pytest.approx(paid_places)

    saved = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
    for cid, expected in p_true_override.items():
        assert saved["p_true"][cid] == pytest.approx(expected)
    metrics_market = (
        saved.get("meta", {})
        .get("exotics", {})
        .get("metrics", {})
        .get("market", {})
    )
    assert metrics_market.get("slots_place") == pytest.approx(paid_places)

def test_filter_combos_strict_handles_missing_metrics(monkeypatch):
    def fake_evaluate_combo(combo, bankroll, calibration=None, allow_heuristic=False):
        return {
            "status": "insufficient_data",
            "ev_ratio": 1.0,
            "payout_expected": 100.0,
            "roi": None,
            "sharpe": None,
        }
    monkeypatch.setattr(simulate_wrapper, "evaluate_combo", fake_evaluate_combo)

    templates = [[{"id": "combo", "stake": 1.0, "legs": ["1", "2"], "type": "CP", "odds": 10.0}]]
    
    # Create a dummy calibration file
    dummy_calibration = Path("dummy_calibration.yaml")
    dummy_calibration.write_text("dummy_data")

    kept, info = runner_chain.validate_exotics_with_simwrapper(
        templates,
        bankroll=100.0,
        calibration=dummy_calibration,
    )

    assert kept == []
    assert "status_insufficient_data" in info["flags"]["reasons"]["combo"]
    
    # Clean up the dummy file
    dummy_calibration.unlink()