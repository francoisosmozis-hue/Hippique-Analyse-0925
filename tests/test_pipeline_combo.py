import json
import sys
from pathlib import Path

import pytest

import logging_io
import pipeline_run
import simulate_ev
import simulate_wrapper
import tickets_builder
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
    argv = [
        "pipeline_run.py",
        "analyse",
        "--h30",
        str(inputs["h30"]),
        "--h5",
        str(inputs["h5"]),
        "--stats-je",
        str(inputs["stats"]),
        "--partants",
        str(inputs["partants"]),
        "--gpi",
        str(inputs["gpi"]),
        "--outdir",
        str(outdir),
        "--diff",
        str(inputs["diff"]),
        "--budget",
        "5",
        "--ev-global",
        "0.0",
        "--roi-global",
        "0.0",
        "--max-vol",
        "0.60",
        "--allow-je-na",
    ]
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sys, "argv", argv)
    try:
        pipeline_run.main()
    finally:
        monkeypatch.undo()
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

    monkeypatch.setattr(pipeline_run, "append_csv_line", fake_append_csv_line)
    monkeypatch.setattr(pipeline_run, "append_json", fake_append_json)
    monkeypatch.setattr(logging_io, "append_csv_line", fake_append_csv_line)
    monkeypatch.setattr(logging_io, "append_json", fake_append_json)

    return tracking_path


def test_pipeline_allocates_combo_budget(tmp_path, monkeypatch):
    partants = _with_exotics(partants_sample())
    inputs = _write_inputs(tmp_path, partants)

    original_append_csv_line = logging_io.append_csv_line
    original_append_json = logging_io.append_json

    def fake_append_csv(path, data, header=logging_io.CSV_HEADER):
        return original_append_csv_line(tmp_path / "tracking.csv", data, header=header)

    def fake_append_json(path, data):
        target = Path(path)
        if target.is_absolute():
            target = target.relative_to(target.anchor)
        target_path = tmp_path / target
        return original_append_json(target_path, data)

    monkeypatch.setattr(pipeline_run, "append_csv_line", fake_append_csv)
    monkeypatch.setattr(pipeline_run, "append_json", fake_append_json)
    monkeypatch.setattr(logging_io, "append_csv_line", fake_append_csv)
    monkeypatch.setattr(logging_io, "append_json", fake_append_json)

    def fake_allocate(cfg_local, runners):
        tickets = [
            {
                "type": "SP",
                "id": "5",
                "odds": 9.0,
                "stake": 2.0,
                "ev_ticket": 0.3,
            },
            {
                "type": "SP",
                "id": "6",
                "odds": 11.0,
                "stake": 1.0,
                "ev_ticket": 0.2,
            },
        ]
        return [dict(ticket) for ticket in tickets], 0.5

    monkeypatch.setattr(pipeline_run, "allocate_dutching_sp", fake_allocate)

    original_filter = pipeline_run._filter_sp_and_cp_tickets
    captured = {}

    def wrapped_filter(sp_tickets, combo_tickets, runners, partants):
        result = original_filter(sp_tickets, combo_tickets, runners, partants)
        captured["result"] = result
        return result

    monkeypatch.setattr(pipeline_run, "_filter_sp_and_cp_tickets", wrapped_filter)

    def fake_validate(candidates, bankroll, **kwargs):
        if not candidates:
            return [], {"notes": [], "flags": {"combo": False}}
        tickets = []
        for candidate in candidates:
            base = dict(candidate[0])
            ticket = {
                "id": base.get("id", "combo-1"),
                "type": base.get("type", "CP"),
                "legs": list(base.get("legs", [])),
                "stake": float(base.get("stake", 1.0)),
                "ev_check": {
                    "ev_ratio": 0.6,
                    "roi": 0.55,
                    "payout_expected": 40.0,
                    "sharpe": 0.7,
                },
            }
            tickets.append(ticket)
        return tickets, {"notes": [], "flags": {"combo": True}}

    monkeypatch.setattr(tickets_builder, "validate_exotics_with_simwrapper", fake_validate)    

    calls = []

    def fake_simulate(tickets, bankroll, **kwargs):
        calls.append([dict(t) for t in tickets])
        total = sum(t.get("stake", 0.0) for t in tickets)
        return {
            "ev": total * 0.2,
            "roi": 0.2,
            "combined_expected_payout": total * 8.0,
            "risk_of_ruin": 0.1,
            "ev_over_std": 0.5,
            "variance": 1.2,
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
        return {"sp": True, "combo": True, "reasons": {"sp": [], "combo": []}}

    monkeypatch.setattr(pipeline_run, "compute_overround_cap", lambda *a, **k: 2.0)
    _patch_combo_eval(monkeypatch)
    cleanup = _patch_simulation(monkeypatch, simulate_fn=fake_simulate, gate_fn=fake_gate)
    try:
        outdir = _run_pipeline(tmp_path, inputs)
    finally:
        cleanup()

    assert calls, "simulate_ev_batch should be called"
    final_call = calls[-1]
    combo_types = [t.get("type") for t in final_call if t.get("type") in {"CP", "TRIO", "ZE4"}]
    filtered = captured.get("result")
    if filtered:
        _, combo_filtered, notes = filtered
        assert any(t.get("type") == "CP" for t in combo_filtered), f"CP filtered unexpectedly: {combo_filtered}, notes={notes}"
    combo_stakes = [t["stake"] for t in final_call if t.get("type") in {"CP", "TRIO", "ZE4"}]
    assert len(combo_stakes) == 1, f"combo types={combo_types}, stakes={combo_stakes}"
    combo_budget = 5 * 0.4
    assert combo_stakes[0] == pytest.approx(combo_budget)

    data = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
    combo_ids = [t["id"] for t in data["tickets"] if t.get("type") in {"CP", "TRIO"}]
    assert combo_ids and {"cp-alpha", "trio-beta"}.issuperset(set(combo_ids))
    assert data["ev"]["global"] == pytest.approx(sum(t["stake"] for t in final_call) * 0.2)
    assert data["ev"]["variance"] == pytest.approx(1.2)
    assert data["ev"]["combined_expected_payout"] == pytest.approx(sum(t["stake"] for t in final_call) * 8.0)


def test_pipeline_recomputes_after_combo_rejection(tmp_path, monkeypatch):
    partants = _with_exotics(partants_sample())
    inputs = _write_inputs(tmp_path, partants)

    _mock_tracking_outputs(tmp_path, monkeypatch)

    def fake_allocate(cfg_local, runners):
        tickets = [
            {
                "type": "SP",
                "id": "5",
                "odds": 9.0,
                "stake": 2.0,
                "ev_ticket": 0.3,
            },
            {
                "type": "SP",
                "id": "6",
                "odds": 11.0,
                "stake": 1.0,
                "ev_ticket": 0.2,
            },
        ]
        return [dict(ticket) for ticket in tickets], 0.5

    monkeypatch.setattr(pipeline_run, "allocate_dutching_sp", fake_allocate)
    
    def fake_validate(candidates, bankroll, **kwargs):
        if not candidates:
            return [], {"notes": [], "flags": {"combo": False}}
            
        tickets = []
        for candidate in candidates:
            base = dict(candidate[0])
            ticket = {
                "id": base.get("id", "combo-1"),
                "type": base.get("type", "CP"),
                "legs": list(base.get("legs", [])),
                "stake": float(base.get("stake", 1.0)),
                "ev_check": {
                    "ev_ratio": 0.6,
                    "roi": 0.55,
                    "payout_expected": 40.0,
                    "sharpe": 0.7,
                },
            }
            tickets.append(ticket)
        return tickets, {"notes": [], "flags": {"combo": True}}

    monkeypatch.setattr(tickets_builder, "validate_exotics_with_simwrapper", fake_validate)    

    calls = []

    def fake_simulate(tickets, bankroll, **kwargs):
        calls.append([dict(t) for t in tickets])
        total = sum(t.get("stake", 0.0) for t in tickets)
        return {
            "ev": total * 0.1,
            "roi": 0.1,
            "combined_expected_payout": total * 2.0,
            "risk_of_ruin": 0.05,
            "ev_over_std": 0.4,
            "variance": 0.8,
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
        return {"sp": True, "combo": False, "reasons": {"sp": [], "combo": ["ROI_MIN_GLOBAL"]}}

    _patch_combo_eval(monkeypatch)
    cleanup = _patch_simulation(monkeypatch, simulate_fn=fake_simulate, gate_fn=fake_gate)
    try:
        outdir = _run_pipeline(tmp_path, inputs)
    finally:
        cleanup()

    assert calls, "simulate_ev_batch should be called at least once"
    data = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
    combo_tickets = [t for t in data["tickets"] if t.get("type") != "SP"]
    assert not combo_tickets
    final_total = sum(t.get("stake", 0.0) for t in data["tickets"])
    assert data["ev"]["global"] == pytest.approx(final_total * 0.1)
    assert data["ev"]["combined_expected_payout"] == pytest.approx(final_total * 2.0)

def test_filter_sp_and_cp_tickets_apply_cp_threshold():
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


def test_filter_sp_tickets_apply_sp_threshold():
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

def test_pipeline_uses_capped_stake_in_exports(tmp_path, monkeypatch):
    partants = partants_sample()
    inputs = _write_inputs(tmp_path, partants, combo_ratio=0.0)

    tracking_path = _mock_tracking_outputs(tmp_path, monkeypatch)

    base_ticket = {
        "type": "SP",
        "id": "sp-1",
        "stake": 4.0,
        "ev_ticket": 0.8,
        "odds": 6.0,
        "p": 0.55,
    }

    monkeypatch.setattr(
        pipeline_run,
        "apply_ticket_policy",
        lambda *args, **kwargs: ([dict(base_ticket)], [], None),
    )
    monkeypatch.setattr(pipeline_run, "allow_combo", lambda *args, **kwargs: False)

    capped: dict[str, float] = {}

    def fake_simulate(tickets, bankroll, **kwargs):
        if kwargs.get("optimize"):
            capped_stake = capped.get("capped", 0.0)
            original = capped.get("original", capped_stake)
            return {
                "ev_individual": capped_stake * 0.2,
                "ev": capped_stake * 0.2,
                "roi_individual": 0.2 if capped_stake else 0.0,
                "roi": 0.2 if capped_stake else 0.0,
                "risk_of_ruin": 0.05,
                "optimized_stakes": [capped_stake],
                "ticket_metrics_individual": [
                    {
                        "stake": original,
                        "kelly_stake": original,
                        "ev": capped_stake * 0.2,
                        "roi": 0.2 if capped_stake else 0.0,
                        "variance": 0.5,
                        "clv": 0.0,
                    }
                ],
                "green": True,
            }

        total = 0.0
        for ticket in tickets:
            original = float(ticket.get("stake", 0.0))
            capped_stake = original * 0.5
            capped["original"] = original
            capped["capped"] = capped_stake
            ticket["kelly_stake"] = original
            ticket["stake"] = capped_stake
            ticket["ev"] = capped_stake * 0.2
            ticket["roi"] = 0.2 if capped_stake else 0.0
            ticket["variance"] = 0.5
            ticket["clv"] = 0.0
            total += capped_stake

        return {
            "ev": total * 0.2,
            "roi": 0.2 if total else 0.0,
            "combined_expected_payout": total * 8.0,
            "risk_of_ruin": 0.05,
            "ev_over_std": 0.4,
            "variance": 0.5,
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

    cleanup = _patch_simulation(monkeypatch, simulate_fn=fake_simulate, gate_fn=fake_gate)

    try:
        outdir = _run_pipeline(tmp_path, inputs)
    finally:
        cleanup()

    assert capped, "fake_simulate should adjust at least one stake"

    data = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
    tickets = data["tickets"]
    assert tickets, "pipeline should export at least one ticket"
    capped_ticket = tickets[0]
    assert capped_ticket["stake"] == pytest.approx(capped["capped"])
    assert capped_ticket["kelly_stake"] == pytest.approx(capped["original"])

    tracking_lines = tracking_path.read_text(encoding="utf-8").strip().splitlines()
    header = tracking_lines[0].split(";")
    values = tracking_lines[-1].split(";")
    tracking = dict(zip(header, values))
    assert float(tracking["total_stake"]) == pytest.approx(capped["capped"])
    
def test_pipeline_optimization_preserves_ev_and_budget(tmp_path, monkeypatch):
    partants = partants_sample()
    inputs = _write_inputs(tmp_path, partants, combo_ratio=0.0)

    tracking_path = _mock_tracking_outputs(tmp_path, monkeypatch)
    
    base_tickets = [
        {
            "type": "SP",
            "id": "sp-a",
            "stake": 2.0,
            "odds": 6.0,
            "p": 0.55,
        },
        {
            "type": "SP",
            "id": "sp-b",
            "stake": 1.5,
            "odds": 7.0,
            "p": 0.38,
        },
    ]

    monkeypatch.setattr(
        pipeline_run,
        "apply_ticket_policy",
        lambda *args, **kwargs: ([dict(t) for t in base_tickets], [], None),
    )
    monkeypatch.setattr(pipeline_run, "allow_combo", lambda *args, **kwargs: False)
    
    outdir = _run_pipeline(tmp_path, inputs)

    data = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
    ev_info = data["ev"]
    optimization = ev_info.get("optimization")
    assert optimization, "optimization summary should be exported"
    assert ev_info["global"] >= optimization.get("ev_before", 0.0) - 1e-9
    total_stake = sum(float(t.get("stake", 0.0)) for t in data["tickets"])
    assert total_stake <= 5.0 + 1e-9

    tracking_lines = tracking_path.read_text(encoding="utf-8").strip().splitlines()
    header = tracking_lines[0].split(";")
    values = tracking_lines[-1].split(";")
    tracking = dict(zip(header, values))
    assert float(tracking["total_optimized_stake"]) >= 0.0

    capped: dict[str, object] = {}

    base_ticket = {
        "type": "SP",
        "id": "sp-1",
        "stake": 4.0,
        "ev_ticket": 0.8,
        "odds": 6.0,
        "p": 0.6,
    }

    monkeypatch.setattr(
        pipeline_run,
        "apply_ticket_policy",
        lambda *args, **kwargs: ([dict(base_ticket)], [], None),
    )

    def fake_simulate(tickets, bankroll, **kwargs):
        total = 0.0
        capped_id = capped.get("id")
        desired = capped.get("capped")
        for ticket in tickets:
            stake = float(ticket.get("stake", 0.0))
            ticket["kelly_stake"] = stake
            if ticket.get("type") == "SP":
                if capped_id is None:
                    capped_id = ticket.get("id")
                    desired = stake / 2
                    capped["id"] = capped_id
                    capped["original"] = stake
                    capped["capped"] = desired
                if ticket.get("id") == capped_id and desired is not None:
                    stake = min(stake, float(desired))
                    ticket["stake"] = stake
            else:
                ticket["stake"] = stake
            total += stake
            ticket["ev"] = stake * 0.2
            ticket["roi"] = 0.2 if stake else 0.0
            ticket["variance"] = 0.0
            ticket["clv"] = 0.0
        roi_total = 0.2 if total else 0.0
        return {
            "ev": total * 0.2,
            "roi": roi_total,
            "combined_expected_payout": total * 8.0,
            "risk_of_ruin": 0.05,
            "ev_over_std": 0.4,
            "variance": 0.5,
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
        return {"sp": True, "combo": True, "reasons": {"sp": [], "combo": []}}

    cleanup = _patch_simulation(monkeypatch, simulate_fn=fake_simulate, gate_fn=fake_gate)

    try:
        outdir = _run_pipeline(tmp_path, inputs)
    finally:
        cleanup()

    assert capped, "fake_simulate should adjust at least one stake"
    data = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
    tickets = data["tickets"]
    capped_ticket = next(t for t in tickets if t.get("id") == capped["id"])
    assert capped_ticket["stake"] == pytest.approx(capped["capped"])

    total_stake = sum(float(t.get("stake", 0.0)) for t in tickets)
    sp_tickets = [t for t in tickets if t.get("type") == "SP"]
    sp_stake = sum(float(t.get("stake", 0.0)) for t in sp_tickets)
    sp_ev = sum(float(t.get("ev", 0.0)) for t in sp_tickets)

    assert data["ev"]["global"] == pytest.approx(total_stake * 0.2)
    assert data["ev"]["sp"] == pytest.approx(sp_ev)
    if sp_stake:
        assert data["ev"]["roi_sp"] == pytest.approx(sp_ev / sp_stake)
    else:
        assert data["ev"]["roi_sp"] == 0.0

    tracking_lines = tracking_path.read_text(encoding="utf-8").strip().splitlines()
    header = tracking_lines[0].split(";")
    values = tracking_lines[-1].split(";")
    tracking = dict(zip(header, values))

    assert float(tracking["total_stake"]) == pytest.approx(total_stake)
    assert float(tracking["roi_sp"]) == pytest.approx(data["ev"]["roi_sp"])
    assert float(tracking["roi_global"]) == pytest.approx(data["ev"]["roi_global"])   


def test_pipeline_respects_p_finale_override(tmp_path, monkeypatch):
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

def test_filter_combos_strict_handles_missing_metrics():
    class DummyWrapper:
        def evaluate_combo(self, combo, bankroll, calibration=None, allow_heuristic=False):
            return {
                "status": "insufficient_data",
                "ev_ratio": None,
                "payout_expected": None,
                "roi": None,
                "sharpe": None,
            }

    templates = [{"id": "combo", "stake": 1.0}]
    kept, reasons = pipeline_run.filter_combos_strict(
        templates,
        sim_wrapper=DummyWrapper(),
        bankroll_lookup=lambda _template: 5.0,
        ev_min=0.40,
        payout_min=10.0,
        allow_heuristic=False,
    )

    assert kept == []
    assert "status_insufficient_data" in reasons
