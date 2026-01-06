# tests/scripts/test_simulate_ev_script.py

import math
import pytest
from hippique_orchestrator.scripts.simulate_ev import (
    implied_prob,
    normalize_overround,
    implied_probs,
    allocate_dutching_sp,
    gate_ev,
    simulate_ev_batch,
)


# Test pour implied_prob
def test_implied_prob_valid():
    assert implied_prob(2.0) == 0.5
    assert implied_prob(4.0) == 0.25
    assert implied_prob(1.01) == 1 / 1.01


def test_implied_prob_invalid():
    assert implied_prob(1.0) == 0.0
    assert implied_prob(0.5) == 0.0
    assert implied_prob(0) == 0.0
    assert implied_prob(-10.0) == 0.0
    assert implied_prob(None) == 0.0
    assert implied_prob("abc") == 0.0
    assert implied_prob(float('inf')) == 0.0
    assert implied_prob(float('-inf')) == 0.0
    assert implied_prob(float('nan')) == 0.0


# Test pour normalize_overround
def test_normalize_overround_basic():
    probs = {"a": 0.5, "b": 0.5, "c": 0.2}  # Total = 1.2
    normalized = normalize_overround(probs)
    assert math.isclose(sum(normalized.values()), 1.0)
    assert normalized["a"] == 0.5 / 1.2


def test_normalize_overround_with_invalids():
    probs = {"a": 0.5, "b": "invalid", "c": -0.2, "d": 0.3}
    normalized = normalize_overround(probs)
    assert normalized["b"] == 0.0
    assert normalized["c"] == 0.0
    assert math.isclose(sum(normalized.values()), 1.0)
    assert normalized["a"] == 0.5 / 0.8
    assert normalized["d"] == 0.3 / 0.8


def test_normalize_overround_zero_total():
    probs = {"a": 0.0, "b": 0.0}
    normalized = normalize_overround(probs)
    assert normalized["a"] == 0.0
    assert normalized["b"] == 0.0


def test_normalize_overround_empty():
    assert normalize_overround({}) == {}


# Test pour implied_probs
def test_implied_probs_list():
    odds = [2.0, 4.0]
    probs = implied_probs(odds)
    total_prob = 1 / 2.0 + 1 / 4.0
    assert len(probs) == 2
    assert math.isclose(probs[0], (1 / 2.0) / total_prob)
    assert math.isclose(probs[1], (1 / 4.0) / total_prob)
    assert math.isclose(sum(probs), 1.0)


def test_implied_probs_with_invalid_odds():
    odds = [2.0, 1.0, 4.0, "abc"]
    probs = implied_probs(odds)
    total_prob = 1 / 2.0 + 1 / 4.0
    assert len(probs) == 4
    assert math.isclose(probs[0], (1 / 2.0) / total_prob)
    assert probs[1] == 0.0
    assert math.isclose(probs[2], (1 / 4.0) / total_prob)
    assert probs[3] == 0.0
    assert math.isclose(sum(probs), 1.0)


@pytest.fixture
def base_cfg():
    """Fournit une configuration de base pour les tests."""
    return {
        "BUDGET_TOTAL": 100.0,
        "SP_RATIO": 0.5,  # 50€ pour SP
        "MAX_VOL_PAR_CHEVAL": 0.6,
        "KELLY_FRACTION": 0.5,
        "ROUND_TO_SP": 0.1,
        "MIN_STAKE_SP": 0.5,
        "EV_MIN_SP": 0.05,
        "ROI_MIN_SP": 0.1,
        "EV_MIN_GLOBAL": 0.1,
        "ROI_MIN_GLOBAL": 0.15,
        "MIN_PAYOUT_COMBOS": 10.0,
        "ROR_MAX": 0.2,
        "SHARPE_MIN": 0.5,
    }


def test_allocate_dutching_sp_ideal(base_cfg):
    runners = [
        {"id": 1, "odds": 3.0, "p": 0.4},
        {"id": 2, "odds": 5.0, "p": 0.25},
    ]
    tickets, ev_sp = allocate_dutching_sp(base_cfg, runners)
    assert len(tickets) == 2
    assert ev_sp > 0
    total_stake = sum(t["stake"] for t in tickets)
    # Vérifie que le total misé est proche du budget alloué par Kelly
    assert total_stake == pytest.approx(25.0, 0.1)


def test_allocate_dutching_sp_fallback_prob(base_cfg):
    runners = [
        {"id": 1, "odds": 3.0},  # Doit utiliser implied_prob
        {"id": 2, "odds": 5.0, "p_imp": 0.22},  # Doit utiliser p_imp
    ]
    tickets, ev_sp = allocate_dutching_sp(base_cfg, runners)
    assert len(tickets) == 2
    # La probabilité pour le cheval 1 doit être issue de la cote normalisée
    p1_expected = (1 / 3.0) / (1 / 3.0 + 0.22)
    assert math.isclose(tickets[0]['p'], p1_expected, rel_tol=1e-2)
    assert math.isclose(tickets[1]['p'], 1 - p1_expected, rel_tol=1e-2)


def test_allocate_dutching_sp_stake_capping(base_cfg):
    # Un cheval très probable qui devrait dépasser le cap
    runners = [{"id": 1, "odds": 1.5, "p": 0.7}]
    base_cfg["MAX_VOL_PAR_CHEVAL"] = 0.1  # Plafond à 10% du budget SP (5€)

    tickets, _ = allocate_dutching_sp(base_cfg, runners)

    assert len(tickets) == 1
    assert tickets[0]["stake"] <= 50.0 * 0.1  # Budget SP * cap


def test_allocate_dutching_sp_min_stake_filter(base_cfg):
    runners = [{"id": 1, "odds": 100.0, "p": 0.01}]  # Kelly très faible
    base_cfg["MIN_STAKE_SP"] = 2.0

    tickets, _ = allocate_dutching_sp(base_cfg, runners)

    assert len(tickets) == 0  # Doit être filtré car la mise est trop faible


def test_allocate_dutching_sp_no_valid_runners(base_cfg):
    runners = [
        {"id": 1, "odds": 1.0, "p": 0.9},  # Cote invalide
        {"id": 2, "odds": 5.0, "p": 1.1},  # Proba invalide
    ]
    tickets, ev_sp = allocate_dutching_sp(base_cfg, runners)
    assert tickets == []
    assert ev_sp == 0.0


def test_gate_ev_all_pass(base_cfg):
    gates = gate_ev(
        cfg=base_cfg,
        ev_sp=10.0,
        ev_global=20.0,
        roi_sp=0.2,
        roi_global=0.2,
        min_payout_combos=15.0,
        risk_of_ruin=0.1,
        ev_over_std=0.6,
    )
    assert gates["sp"] is True
    assert gates["combo"] is True
    assert not gates["reasons"]["sp"]
    assert not gates["reasons"]["combo"]


def test_gate_ev_sp_fails(base_cfg):
    gates = gate_ev(
        cfg=base_cfg,
        ev_sp=0.1,
        roi_sp=0.01,
        ev_global=20,
        roi_global=0.2,
        min_payout_combos=15,
        ev_over_std=0.6,
    )
    assert gates["sp"] is False
    assert "EV_MIN_SP" in gates["reasons"]["sp"]
    assert "ROI_MIN_SP" in gates["reasons"]["sp"]
    assert gates["combo"] is True


def test_gate_ev_combo_fails(base_cfg):
    gates = gate_ev(
        cfg=base_cfg,
        ev_sp=10,
        roi_sp=0.2,
        ev_global=1,
        roi_global=0.05,
        min_payout_combos=5,
        ev_over_std=0.6,
    )
    assert gates["combo"] is False
    assert "EV_MIN_GLOBAL" in gates["reasons"]["combo"]
    assert "ROI_MIN_GLOBAL" in gates["reasons"]["combo"]
    assert "MIN_PAYOUT_COMBOS" in gates["reasons"]["combo"]
    assert gates["sp"] is True


def test_gate_ev_risk_fails_both(base_cfg):
    gates = gate_ev(
        cfg=base_cfg,
        ev_sp=10,
        roi_sp=0.2,
        ev_global=20,
        roi_global=0.2,
        min_payout_combos=15,
        risk_of_ruin=0.3,
        ev_over_std=0.6,
    )
    assert gates["sp"] is False
    assert gates["combo"] is False
    assert "ROR_MAX" in gates["reasons"]["sp"]
    assert "ROR_MAX" in gates["reasons"]["combo"]


def test_gate_ev_sharpe_fails_both(base_cfg):
    gates = gate_ev(
        cfg=base_cfg,
        ev_sp=10,
        roi_sp=0.2,
        ev_global=20,
        roi_global=0.2,
        min_payout_combos=15,
        risk_of_ruin=0.1,
        ev_over_std=0.1,
    )
    assert gates["sp"] is False
    assert gates["combo"] is False
    assert "SHARPE_MIN" in gates["reasons"]["sp"]
    assert "SHARPE_MIN" in gates["reasons"]["combo"]
