import argparse
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import pytest

import logging_io
import pipeline_run
import simulate_ev
import simulate_wrapper
import tickets_builder
import validator_ev
from test_pipeline_smoke import (
    GPI_YML,
    odds_h30,
    odds_h5,
    partants_sample,
    stats_sample,
)


def _write_inputs(
    tmp_path: Path, *, partants_override: Mapping[str, Any] | None = None
) -> dict[str, Path]:
    h30_path = tmp_path / "h30.json"
    h5_path = tmp_path / "h5.json"
    stats_path = tmp_path / "stats.json"
    partants_path = tmp_path / "partants.json"
    gpi_path = tmp_path / "gpi.yml"
    diff_path = tmp_path / "diff.json"

    h30_path.write_text(json.dumps(odds_h30()), encoding="utf-8")
    h5_path.write_text(json.dumps(odds_h5()), encoding="utf-8")
    stats_path.write_text(json.dumps(stats_sample()), encoding="utf-8")
    
    partants_payload = partants_sample()
    if partants_override:
        partants_payload.update(partants_override)
    partants_path.write_text(json.dumps(partants_payload), encoding="utf-8")
    gpi_path.write_text(GPI_YML, encoding="utf-8")
    diff_path.write_text("{}", encoding="utf-8")

    return {
        "h30": h30_path,
        "h5": h5_path,
        "stats": stats_path,
        "partants": partants_path,
        "gpi": gpi_path,
        "diff": diff_path,
    }


def _prepare_stubs(
    monkeypatch: pytest.MonkeyPatch,
    eval_stats: dict[str, float | str],
    *,
    overround_cap: float = 5.0,
    market_overround: float | None = None,
    compute_cap_stub: Callable[..., float] | None = None,
):
    pipeline_run._load_simulate_ev.cache_clear()

    def fake_allocate(cfg, runners):
        return [], {}

    def fake_gate(*_args, **_kwargs):
        return {"sp": True, "combo": True, "reasons": {"sp": [], "combo": []}}

    def fake_implied_prob(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        if number <= 0:
            return 0.0
        return 1.0 / number

    def fake_implied_probs(values):
        return [fake_implied_prob(v) for v in values]

    def fake_simulate_ev_batch(*_args, **_kwargs):
        return {
            "ev": 0.0,
            "roi": 0.0,
            "combined_expected_payout": 0.0,
            "risk_of_ruin": 0.0,
            "ev_over_std": 0.0,
            "variance": 0.0,
            "clv": 0.0,
        }

    monkeypatch.setattr(simulate_ev, "allocate_dutching_sp", fake_allocate)
    monkeypatch.setattr(simulate_ev, "gate_ev", fake_gate)
    monkeypatch.setattr(simulate_ev, "implied_prob", fake_implied_prob)
    monkeypatch.setattr(simulate_ev, "implied_probs", fake_implied_probs)
    monkeypatch.setattr(simulate_ev, "simulate_ev_batch", fake_simulate_ev_batch)
    pipeline_run._load_simulate_ev.cache_clear()

    monkeypatch.setattr(
        tickets_builder,
        "allow_combo",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        validator_ev,
        "combos_allowed",
        lambda *_args, **_kwargs: overround_cap,
    )
    if compute_cap_stub is None:
        compute_cap_stub = lambda *_args, **_kwargs: overround_cap
        
    monkeypatch.setattr(
        pipeline_run,
        "compute_overround_cap",
        compute_cap_stub,
    )
    
    if market_overround is not None:
        monkeypatch.setattr(
            pipeline_run,
            "_compute_market_overround",
            lambda *_args, **_kwargs: market_overround,
        )
        
    def fake_enforce(cfg_local, runners_local, combos_local, bankroll, **_kwargs):
        stats = {
            "ev": 12.0,
            "roi": 0.5,
            "risk_of_ruin": 0.01,
            "combined_expected_payout": 30.0,
            "ev_over_std": 0.8,
            "variance": 1.0,
            "clv": 0.0,
        }
        return [], stats, {"applied": False}

    monkeypatch.setattr(pipeline_run, "enforce_ror_threshold", fake_enforce)

    def fake_filter(sp_tickets, combo_tickets, *_args, **_kwargs):
        return list(sp_tickets), list(combo_tickets), []

    monkeypatch.setattr(pipeline_run, "_filter_sp_and_cp_tickets", fake_filter)
    monkeypatch.setattr(pipeline_run, "build_p_true", lambda *a, **k: {})
    monkeypatch.setattr(pipeline_run, "compute_drift_dict", lambda *a, **k: {})
    monkeypatch.setattr(pipeline_run, "_summarize_optimization", lambda *a, **k: None)

    monkeypatch.setattr(logging_io, "append_csv_line", lambda *a, **k: None)

    captured_log: list[dict] = []

    def fake_append_json(_path, payload):
        captured_log.append(payload)

    monkeypatch.setattr(logging_io, "append_json", fake_append_json)

    combo_template = {
        "id": "CP1",
        "type": "CP",
        "legs": ["1", "2"],
        "stake": 1.0,
    }

    def fake_apply(cfg, runners, combo_candidates=None, combos_source=None, **_kwargs):
        info = {"notes": ["seed_info"], "flags": {"combo": True}, "decision": "accept"}
        return [], [dict(combo_template)], info

    monkeypatch.setattr(tickets_builder, "apply_ticket_policy", fake_apply)

    eval_calls: list[dict] = []

    def fake_evaluate(tickets, bankroll, allow_heuristic=False):
        eval_calls.append(
            {"tickets": [dict(t) for t in tickets], "bankroll": bankroll, "allow_heuristic": allow_heuristic}
        )
        result = dict(eval_stats)
        result.setdefault("status", "ok")
        result.setdefault("ev_ratio", 0.0)
        result.setdefault("roi", 0.0)
        result.setdefault("payout_expected", 0.0)
        result.setdefault("sharpe", 0.0)
        return result

    monkeypatch.setattr(simulate_wrapper, "evaluate_combo", fake_evaluate)

    return captured_log, eval_calls


def _run_analysis(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    eval_stats: dict[str, float | str],
    *,
    overround_cap: float = 5.0,
    market_overround: float | None = None,
    partants_override: Mapping[str, Any] | None = None,
    compute_cap_stub: Callable[..., float] | None = None,
):
    inputs = _write_inputs(tmp_path, partants_override=partants_override)
    captured_log, eval_calls = _prepare_stubs(
        monkeypatch,
        eval_stats,
        overround_cap=overround_cap,
        market_overround=market_overround,
        compute_cap_stub=compute_cap_stub,
    )

    outdir = tmp_path / "out"

    args = argparse.Namespace(
        h30=str(inputs["h30"]),
        h5=str(inputs["h5"]),
        stats_je=str(inputs["stats"]),
        partants=str(inputs["partants"]),
        gpi=str(inputs["gpi"]),
        outdir=str(outdir),
        diff=str(inputs["diff"]),
        budget=None,
        ev_global=None,
        roi_global=None,
        max_vol=None,
        min_payout=None,
        ev_min_exotic=0.40,
        payout_min_exotic=10.0,
        allow_heuristic=False,
        allow_je_na=False,
    )

    pipeline_run.cmd_analyse(args)

    data = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
    meta = data["meta"]
    assert captured_log, "expected journaux append_json call"
    log_entry = captured_log[-1]

    return meta, log_entry, eval_calls


def test_exotics_accept_keeps_combo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eval_stats = {
        "status": "ok",
        "ev_ratio": 0.6,
        "payout_expected": 20.0,
        "roi": 0.3,
        "sharpe": 0.5,
    }

    meta, log_entry, eval_calls = _run_analysis(monkeypatch, tmp_path, eval_stats)

    assert eval_calls, "evaluate_combo should be called"
    assert all(call["allow_heuristic"] is False for call in eval_calls)

    exotics_meta = meta.get("exotics")
    assert exotics_meta["decision"] == "accept"
    assert exotics_meta["available"] is True
    assert exotics_meta["thresholds"]["ev_min"] == pytest.approx(0.40)
    assert exotics_meta["thresholds"]["payout_min"] == pytest.approx(10.0)

    assert log_entry.get("exotics", {}).get("decision") == "accept"


def test_exotics_rejects_low_ev(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eval_stats = {
        "status": "ok",
        "ev_ratio": 0.25,
        "payout_expected": 25.0,
        "roi": 0.1,
        "sharpe": 0.2,
    }

    meta, log_entry, _ = _run_analysis(monkeypatch, tmp_path, eval_stats)

    exotics_meta = meta.get("exotics")
    assert exotics_meta["decision"].startswith("reject:"), exotics_meta
    reasons = exotics_meta["flags"]["reasons"]["combo"]
    assert "ev_ratio_below_pipeline_threshold" in reasons
    assert exotics_meta["available"] is False

    log_decision = log_entry.get("exotics", {}).get("decision")
    assert isinstance(log_decision, str)
    assert log_decision.startswith("reject")


def test_exotics_rejects_on_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    eval_stats = {
        "status": "insufficient_data",
        "ev_ratio": 0.55,
        "payout_expected": 18.0,
        "roi": 0.15,
        "sharpe": 0.25,
    }

    meta, log_entry, _ = _run_analysis(monkeypatch, tmp_path, eval_stats)

    exotics_meta = meta.get("exotics")
    assert exotics_meta["available"] is False
    reasons = exotics_meta["flags"]["reasons"]["combo"]
    assert "status_insufficient_data" in reasons
    assert exotics_meta["decision"].startswith("reject:"), exotics_meta

    log_decision = log_entry.get("exotics", {}).get("decision")
    assert isinstance(log_decision, str)
    assert log_decision.startswith("reject:status_insufficient_data")


def test_filter_combos_strict_disables_heuristics_by_default() -> None:
    """Default combo evaluation must run with heuristics disabled."""

    class DummyWrapper:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def evaluate_combo(self, tickets, bankroll, *, allow_heuristic=False):  # type: ignore[override]
            self.calls.append(
                {
                    "tickets": [dict(t) for t in tickets],
                    "bankroll": bankroll,
                    "allow_heuristic": allow_heuristic,
                }
            )
            return {
                "status": "ok",
                "ev_ratio": 0.55,
                "payout_expected": 15.0,
                "roi": 0.25,
                "sharpe": 0.4,
            }

    wrapper = DummyWrapper()

    kept, reasons = pipeline_run.filter_combos_strict(
        [
            {
                "type": "CP",
                "stake": 1.0,
                "legs": ["1", "2"],
            }
        ],
        sim_wrapper=wrapper,
        bankroll_lookup=lambda _template: 5.0,
        ev_min=0.40,
        payout_min=10.0,
    )

    assert kept, "expected the combo to be retained"
    assert reasons == []
    assert wrapper.calls, "evaluate_combo should have been invoked"
    assert wrapper.calls[0]["allow_heuristic"] is False


def test_filter_combos_strict_limits_to_best_combo() -> None:
    """Only the best-valued combo should be retained when several pass guards."""

    class DummyWrapper:
        def __init__(self, responses: Mapping[str, Mapping[str, Any]]) -> None:
            self._responses = responses
            self.calls: list[str] = []

        def evaluate_combo(self, tickets, bankroll, *, allow_heuristic=False):  # type: ignore[override]
            assert len(tickets) == 1
            identifier = str(tickets[0].get("id") or tickets[0].get("type"))
            self.calls.append(identifier)
            return dict(self._responses[identifier])

    templates = [
        {"id": "combo_a", "stake": 1.0},
        {"id": "combo_b", "stake": 1.0},
    ]

    responses: Mapping[str, Mapping[str, Any]] = {
        "combo_a": {
            "status": "ok",
            "ev_ratio": 0.48,
            "payout_expected": 14.0,
            "roi": 0.18,
            "sharpe": 0.28,
        },
        "combo_b": {
            "status": "ok",
            "ev_ratio": 0.55,
            "payout_expected": 18.0,
            "roi": 0.24,
            "sharpe": 0.32,
        },
    }

    wrapper = DummyWrapper(responses)

    kept, reasons = pipeline_run.filter_combos_strict(
        templates,
        sim_wrapper=wrapper,
        bankroll_lookup=lambda _template: 5.0,
        ev_min=0.40,
        payout_min=10.0,
    )

    assert wrapper.calls == ["combo_a", "combo_b"]
    assert len(kept) == 1
    assert kept[0]["id"] == "combo_b"
    assert "combo_limit_enforced" in reasons


def test_exotics_rejects_low_payout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Combos with sub-10€ payout should be rejected systematically."""

    eval_stats = {
        "status": "ok",
        "ev_ratio": 0.55,
        "payout_expected": 8.5,
        "roi": 0.18,
        "sharpe": 0.3,
    }

    meta, log_entry, _ = _run_analysis(monkeypatch, tmp_path, eval_stats)

    exotics_meta = meta.get("exotics")
    assert exotics_meta["available"] is False
    reasons = exotics_meta["flags"]["reasons"]["combo"]
    assert "payout_expected_below_accept_threshold" in reasons
    assert "payout_below_pipeline_threshold" in reasons

    decision = exotics_meta["decision"]
    assert isinstance(decision, str)
    assert decision.startswith("reject:"), decision

    log_decision = log_entry.get("exotics", {}).get("decision")
    assert isinstance(log_decision, str)
    assert "payout_expected_below_accept_threshold" in log_decision


def test_exotics_rejects_when_overround_exceeds_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """High overround markets should block combinés before evaluation."""

    eval_stats = {
        "status": "ok",
        "ev_ratio": 0.65,
        "payout_expected": 25.0,
        "roi": 0.2,
        "sharpe": 0.4,
    }

    meta, log_entry, eval_calls = _run_analysis(
        monkeypatch,
        tmp_path,
        eval_stats,
        overround_cap=1.25,
        market_overround=1.33,
    )

    assert not eval_calls, "evaluation should be skipped when overround is too high"

    exotics_meta = meta.get("exotics")
    assert exotics_meta["available"] is False
    reasons = exotics_meta["flags"]["reasons"]["combo"]
    assert "overround_above_threshold" in reasons
    assert exotics_meta["decision"].startswith("reject:"), exotics_meta

    log_decision = log_entry.get("exotics", {}).get("decision")
    assert isinstance(log_decision, str)
    assert "overround_above_threshold" in log_decision


def test_overround_cap_uses_metadata_fallbacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pipeline should fall back to course metadata when meta fields are blank."""

    eval_stats = {
        "status": "ok",
        "ev_ratio": 0.6,
        "payout_expected": 20.0,
        "roi": 0.3,
        "sharpe": 0.5,
    }

    calls: list[dict[str, Any]] = []

    def record_cap(discipline, partants, *, default_cap, course_label):
        calls.append(
            {
                "discipline": discipline,
                "partants": partants,
                "default_cap": default_cap,
                "course_label": course_label,
            }
        )
        return 1.30

    runners_override = [
        {"id": str(idx), "name": f"Runner {idx}"}
        for idx in range(1, 15)
    ]
    partants_override = {
        "discipline": "",
        "type_course": "Handicap de plat",
        "course_label": "Handicap de plat - test",
        "runners": runners_override,
    }

    _run_analysis(
        monkeypatch,
        tmp_path,
        eval_stats,
        partants_override=partants_override,
        compute_cap_stub=record_cap,
    )

    assert calls, "compute_overround_cap should have been invoked"
    last_call = calls[-1]
    assert isinstance(last_call["discipline"], str)
    assert "handicap" in last_call["discipline"].lower()
    assert int(last_call["partants"]) == 14
    assert last_call["default_cap"] == pytest.approx(1.30)
