from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import pytest

from hippique_orchestrator import ev_calculator
from hippique_orchestrator.ev_calculator import (
    DEFAULT_KELLY_CAP,
    _apply_dutching,
    _approx_joint_probability,
    _calculate_final_metrics,
    _calculate_ticket_metrics,
    _clone_leg,
    _covariance_from_joint,
    _estimate_joint_probability,
    _kelly_fraction,
    _make_hashable,
    _merge_legs,
    _prepare_legs_for_covariance,
    _prepare_ticket_dependencies,
    _process_single_ticket,
    _process_tickets,
    _rho_for_shared_exposures,
    _simulate_joint_probability,
    _ticket_dependency_keys,
    _ticket_label,
    compute_ev_roi,
    compute_joint_moments,
    optimize_stake_allocation,
    risk_of_ruin,
)


# Fixtures for common mocks
@pytest.fixture
def mock_calculate_kelly_fraction():
    # Patch calculate_kelly_fraction within ev_calculator where it's looked up
    with patch("hippique_orchestrator.ev_calculator.calculate_kelly_fraction") as mock:
        yield mock


@pytest.fixture
def mock_simulate_fn():
    mock = MagicMock(return_value=0.5)
    yield mock


@pytest.fixture
def sample_tickets():
    return [
        {"p": 0.5, "odds": 2.5, "stake": 10.0, "dutching": "group1"},
        {"p": 0.4, "odds": 3.0, "stake": 10.0, "dutching": "group1"},
        {"p": 0.7, "odds": 1.5, "stake": 5.0},  # Not in a dutching group
    ]


@pytest.fixture
def sample_combined_tickets():
    return [
        {"legs": ["leg1a", "leg1b"], "odds": 5.0, "stake": 10.0},
        {"legs": ["leg2a"], "odds": 3.0, "stake": 5.0},
    ]


# --- Test _make_hashable ---
def test_make_hashable_hashable_types():
    assert _make_hashable(1) == 1
    assert _make_hashable("string") == "string"
    assert _make_hashable(True) is True
    assert _make_hashable(None) is None


def test_make_hashable_list():
    assert _make_hashable([1, 2, "a"]) == (1, 2, "a")


def test_make_hashable_dict():
    assert _make_hashable({"a": 1, "b": "hello"}) == (("a", 1), ("b", "hello"))
    assert _make_hashable({"b": "hello", "a": 1}) == (("a", 1), ("b", "hello"))  # Order-independent


def test_make_hashable_nested_structures():
    value = [{"x": 1}, [2, "y"]]
    expected = ((("x", 1),), (2, "y"))
    assert _make_hashable(value) == expected


def test_make_hashable_unhashable_fallback():
    """Tests the fallback behavior of _make_hashable for unhashable types."""

    class Unhashable:
        __hash__ = None  # Explicitly mark as unhashable

        def __eq__(self, other):
            return False  # Make it unhashable

        def __repr__(self):
            return "unhashable_repr"

    instance = Unhashable()
    assert _make_hashable(instance) == "unhashable_repr"


# --- Test _kelly_fraction ---
def test_kelly_fraction_valid_inputs(mock_calculate_kelly_fraction):
    mock_calculate_kelly_fraction.return_value = 0.25  # Expected Kelly fraction for p=0.5, odds=3.0
    assert _kelly_fraction(0.5, 3.0) == 0.25
    mock_calculate_kelly_fraction.assert_called_once_with(0.5, 3.0, lam=1.0, cap=1.0)


def test_kelly_fraction_probability_out_of_range():
    with pytest.raises(ValueError, match=r"probability must be in \(0,1\)"):
        _kelly_fraction(0.0, 3.0)
    with pytest.raises(ValueError, match=r"probability must be in \(0,1\)"):
        _kelly_fraction(1.0, 3.0)
    with pytest.raises(ValueError, match=r"probability must be in \(0,1\)"):
        _kelly_fraction(-0.1, 3.0)


def test_kelly_fraction_odds_out_of_range():
    with pytest.raises(ValueError, match=r"odds must be > 1"):
        _kelly_fraction(0.5, 1.0)
    with pytest.raises(ValueError, match=r"odds must be > 1"):
        _kelly_fraction(0.5, 0.5)


# --- Test _apply_dutching ---
def test_apply_dutching_single_group():
    tickets = [
        {"p": 0.5, "odds": 2.5, "stake": 0, "dutching": "group1"},
        {"p": 0.4, "odds": 3.0, "stake": 0, "dutching": "group1"},
    ]
    initial_total_stake = 100.0
    for t in tickets:
        t["stake"] = initial_total_stake / len(tickets)  # Assign initial stakes for total

    _apply_dutching(tickets)

    # Calculate expected stakes
    w1 = 1 / (2.5 - 1)  # 1 / 1.5 = 0.666...
    w2 = 1 / (3.0 - 1)  # 1 / 2.0 = 0.5
    weight_sum = w1 + w2  # 1.166...

    expected_stake1 = initial_total_stake * (w1 / weight_sum)
    expected_stake2 = initial_total_stake * (w2 / weight_sum)

    assert math.isclose(tickets[0]["stake"], expected_stake1, rel_tol=1e-9)
    assert math.isclose(tickets[1]["stake"], expected_stake2, rel_tol=1e-9)
    assert math.isclose(
        tickets[0]["stake"] + tickets[1]["stake"], initial_total_stake, rel_tol=1e-9
    )
    assert math.isclose(
        tickets[0]["stake"] * (tickets[0]["odds"] - 1),
        tickets[1]["stake"] * (tickets[1]["odds"] - 1),
        rel_tol=1e-9,
    )


def test_apply_dutching_multiple_groups():
    tickets = [
        {"p": 0.5, "odds": 2.5, "stake": 0, "dutching": "group1"},
        {"p": 0.4, "odds": 3.0, "stake": 0, "dutching": "group1"},
        {"p": 0.6, "odds": 2.0, "stake": 0, "dutching": "group2"},
        {"p": 0.3, "odds": 4.0, "stake": 0, "dutching": "group2"},
    ]
    # Assign initial stakes
    for i, t in enumerate(tickets):
        t["stake"] = 50.0 if i < 2 else 70.0  # Different total stakes for groups

    _apply_dutching(tickets)

    # Verify group1
    w1_g1 = 1 / (2.5 - 1)
    w2_g1 = 1 / (3.0 - 1)
    weight_sum_g1 = w1_g1 + w2_g1
    expected_stake1_g1 = 100.0 * (w1_g1 / weight_sum_g1)
    expected_stake2_g1 = 100.0 * (w2_g1 / weight_sum_g1)

    assert math.isclose(tickets[0]["stake"], expected_stake1_g1, rel_tol=1e-9)
    assert math.isclose(tickets[1]["stake"], expected_stake2_g1, rel_tol=1e-9)
    assert math.isclose(
        tickets[0]["stake"] * (tickets[0]["odds"] - 1),
        tickets[1]["stake"] * (tickets[1]["odds"] - 1),
        rel_tol=1e-9,
    )

    # Verify group2
    w1_g2 = 1 / (2.0 - 1)
    w2_g2 = 1 / (4.0 - 1)
    weight_sum_g2 = w1_g2 + w2_g2
    expected_stake1_g2 = 140.0 * (w1_g2 / weight_sum_g2)
    expected_stake2_g2 = 140.0 * (w2_g2 / weight_sum_g2)

    assert math.isclose(tickets[2]["stake"], expected_stake1_g2, rel_tol=1e-9)
    assert math.isclose(tickets[3]["stake"], expected_stake2_g2, rel_tol=1e-9)
    assert math.isclose(
        tickets[2]["stake"] * (tickets[2]["odds"] - 1),
        tickets[3]["stake"] * (tickets[3]["odds"] - 1),
        rel_tol=1e-9,
    )


def test_apply_dutching_no_dutching_groups():
    tickets = [
        {"p": 0.5, "odds": 2.5, "stake": 10.0},
        {"p": 0.4, "odds": 3.0, "stake": 15.0},
    ]
    original_stakes = [t["stake"] for t in tickets]
    _apply_dutching(tickets)
    assert [t["stake"] for t in tickets] == original_stakes


def test_apply_dutching_mixed_groups():
    tickets = [
        {"p": 0.5, "odds": 2.5, "stake": 10.0, "dutching": "group1"},
        {"p": 0.4, "odds": 3.0, "stake": 10.0, "dutching": "group1"},
        {"p": 0.7, "odds": 1.5, "stake": 5.0},  # Not in a dutching group
    ]
    original_non_dutching_stake = tickets[2]["stake"]
    _apply_dutching(tickets)

    # Group1 check
    w1 = 1 / (2.5 - 1)
    w2 = 1 / (3.0 - 1)
    weight_sum = w1 + w2
    total_stake_g1 = 20.0
    expected_stake1 = total_stake_g1 * (w1 / weight_sum)
    expected_stake2 = total_stake_g1 * (w2 / weight_sum)

    assert math.isclose(tickets[0]["stake"], expected_stake1, rel_tol=1e-9)
    assert math.isclose(tickets[1]["stake"], expected_stake2, rel_tol=1e-9)
    assert math.isclose(tickets[2]["stake"], original_non_dutching_stake)  # Unchanged


def test_apply_dutching_invalid_odds_in_group():
    tickets = [
        {"p": 0.5, "odds": 2.5, "stake": 10.0, "dutching": "group1"},
        {"p": 0.4, "odds": 1.0, "stake": 10.0, "dutching": "group1"},  # Invalid odds
    ]
    original_stakes = [t["stake"] for t in tickets]
    _apply_dutching(tickets)
    # The invalid ticket should be skipped, so the valid one's stake is not adjusted (not enough valid tickets)
    assert [t["stake"] for t in tickets] == original_stakes


def test_apply_dutching_single_valid_ticket_in_group():
    tickets = [
        {"p": 0.5, "odds": 2.5, "stake": 10.0, "dutching": "group1"},
        {"p": 0.4, "odds": 0.5, "stake": 10.0, "dutching": "group1"},
    ]
    original_stakes = [t["stake"] for t in tickets]
    _apply_dutching(tickets)
    assert [
        t["stake"] for t in tickets
    ] == original_stakes  # No adjustment if less than MIN_DUTCHING_GROUP_SIZE valid tickets


def test_apply_dutching_group_too_small():
    tickets = [
        {"p": 0.5, "odds": 2.5, "stake": 10.0, "dutching": "group1"},
    ]
    original_stakes = [t["stake"] for t in tickets]
    _apply_dutching(tickets)
    assert [
        t["stake"] for t in tickets
    ] == original_stakes  # No adjustment if group size < MIN_DUTCHING_GROUP_SIZE


def test_ticket_label_with_id():
    ticket = {"id": "horse_id_123"}
    assert _ticket_label(ticket, 0) == "horse_id_123"


def test_ticket_label_with_name():
    ticket = {"name": "MyHorse"}
    assert _ticket_label(ticket, 0) == "MyHorse"


def test_ticket_label_with_label():
    ticket = {"label": "Ticket A"}
    assert _ticket_label(ticket, 0) == "Ticket A"


def test_ticket_label_with_selection():
    ticket = {"selection": "Selection X"}
    assert _ticket_label(ticket, 0) == "Selection X"


def test_ticket_label_with_runner():
    ticket = {"runner": "Runner Y"}
    assert _ticket_label(ticket, 0) == "Runner Y"


def test_ticket_label_no_label_keys_falls_back_to_index():
    ticket = {"odds": 2.0}
    assert _ticket_label(ticket, 5) == "ticket_6"


def test_ticket_label_empty_string_values_falls_back_to_index():
    ticket = {"id": "", "name": "", "odds": 2.0}
    assert _ticket_label(ticket, 1) == "ticket_2"


def test_clone_leg_dict():
    original = {"id": 1, "name": "leg_a"}
    cloned = _clone_leg(original)
    assert cloned == original
    assert cloned is not original  # Ensure it's a clone, not same object
    cloned["name"] = "new_name"
    assert original["name"] == "leg_a"


def test_clone_leg_list_of_dicts():
    original = [{"id": 1}, {"id": 2}]
    cloned = _clone_leg(original)
    assert cloned == original
    assert cloned is not original
    assert cloned[0] is not original[0]  # Ensure nested items are also cloned
    cloned[0]["id"] = 99
    assert original[0]["id"] == 1


def test_clone_leg_primitive_type():
    original = "simple_string"
    cloned = _clone_leg(original)
    assert cloned == original
    assert cloned is original  # Primitive types are not "cloned" in this way (immutable)


def test_prepare_legs_for_covariance_with_legs_for_probability():
    ticket = {"legs_details": ["ld1", "ld2"], "id": "t1"}
    legs_for_prob = ["lp1", "lp2"]
    result = _prepare_legs_for_covariance(ticket, legs_for_prob)
    assert result == ("lp1", "lp2")


def test_prepare_legs_for_covariance_with_legs_details():
    ticket = {"legs_details": ["ld1", {"id": "ld2_id"}], "id": "t1"}
    result = _prepare_legs_for_covariance(ticket, None)
    assert result == ("ld1", {"id": "ld2_id"})
    assert result[1] is not ticket["legs_details"][1]  # Ensure deep copy


def test_prepare_legs_for_covariance_with_legs():
    ticket = {"legs": ["l1", "l2"], "id": "t1"}
    result = _prepare_legs_for_covariance(ticket, None)
    assert result == ("l1", "l2")


def test_prepare_legs_for_covariance_with_id_only():
    ticket = {"id": "t1_id"}
    result = _prepare_legs_for_covariance(ticket, None)
    assert result == ({"id": "t1_id"},)


def test_prepare_legs_for_covariance_no_identifiable_legs():
    ticket = {"odds": 2.0}
    result = _prepare_legs_for_covariance(ticket, None)
    assert result == ()


def test_ticket_dependency_keys_with_ticket_id():
    ticket = {"id": "ticket_xyz"}
    legs = []
    expected = frozenset(["id:ticket_xyz"])
    assert _ticket_dependency_keys(ticket, legs) == expected


def test_ticket_dependency_keys_with_selection_id():
    ticket = {"selection_id": 123}
    legs = []
    expected = frozenset(["id:123"])
    assert _ticket_dependency_keys(ticket, legs) == expected


def test_ticket_dependency_keys_with_leg_id_in_legs():
    ticket = {}
    legs = [{"id": "leg_abc"}]
    expected = frozenset(["leg:leg_abc"])
    assert _ticket_dependency_keys(ticket, legs) == expected


def test_ticket_dependency_keys_with_mixed_dependencies():
    ticket = {"runner_id": "r99"}
    legs = ["leg_x", {"runner": "horse_y"}]
    expected = frozenset(["id:r99", "leg:leg_x", "leg:horse_y"])
    assert _ticket_dependency_keys(ticket, legs) == expected


def test_ticket_dependency_keys_empty():
    ticket = {}
    legs = []
    expected = frozenset()
    assert _ticket_dependency_keys(ticket, legs) == expected


def test_prepare_ticket_dependencies():
    ticket = {"id": "t1", "legs": ["leg1"]}
    legs_for_probability = None
    result = _prepare_ticket_dependencies(ticket, legs_for_probability)
    assert "legs" in result
    assert "exposures" in result
    assert result["legs"] == ("leg1",)
    assert result["exposures"] == frozenset({"id:t1", "leg:leg1"})


def test_rho_for_shared_exposures_id_dependency():
    shared = frozenset({"id:123", "leg:abc"})
    assert _rho_for_shared_exposures(shared) == 0.85


def test_rho_for_shared_exposures_leg_dependency():
    shared = frozenset({"leg:abc", "other:def"})
    assert _rho_for_shared_exposures(shared) == 0.60


def test_rho_for_shared_exposures_no_specific_dependency():
    shared = frozenset({"other:def"})
    assert _rho_for_shared_exposures(shared) == 0.40


def test_rho_for_shared_exposures_empty():
    shared = frozenset()
    assert _rho_for_shared_exposures(shared) == 0.0


def test_approx_joint_probability_independent():
    p_i, p_j, rho = 0.5, 0.6, 0.0
    expected = p_i * p_j
    assert math.isclose(_approx_joint_probability(p_i, p_j, rho), expected)


def test_approx_joint_probability_positive_correlation():
    p_i, p_j, rho = 0.5, 0.5, 0.8
    # Formula for estimate + bounds check (max(lower, min(upper, estimate)))
    # lower = max(0, 0.5+0.5-1) = 0
    # upper = min(0.5, 0.5) = 0.5
    # term = 0.8 * sqrt(0.5*0.5 * 0.5*0.5) = 0.8 * 0.25 = 0.2
    # estimate = 0.25 + 0.2 = 0.45
    assert math.isclose(_approx_joint_probability(p_i, p_j, rho), 0.45)


def test_approx_joint_probability_negative_correlation():
    p_i, p_j, rho = 0.5, 0.5, -0.8
    # lower = 0
    # upper = 0.5
    # term = -0.8 * 0.25 = -0.2
    # estimate = 0.25 - 0.2 = 0.05.
    # But function returns max(independence, estimate) which is max(0.25, 0.05) = 0.25
    assert math.isclose(_approx_joint_probability(p_i, p_j, rho), 0.25)


def test_approx_joint_probability_rho_clipping():
    p_i, p_j, rho = 0.5, 0.5, 1.5  # Should be clipped to 0.99
    # lower = 0, upper = 0.5
    # term = 0.99 * 0.25 = 0.2475
    # estimate = 0.25 + 0.2475 = 0.4975
    assert math.isclose(_approx_joint_probability(p_i, p_j, rho), 0.4975)


def test_approx_joint_probability_lower_bound():
    p_i, p_j, rho = 0.1, 0.1, -0.1
    # independence = 0.01
    # term = -0.1 * sqrt(0.09 * 0.09) = -0.1 * 0.09 = -0.009
    # estimate = 0.01 - 0.009 = 0.001
    # lower = 0.0, upper = 0.1
    # estimate_bounded = max(0.0, min(0.1, 0.001)) = 0.001
    # max(independence, estimate_bounded) = max(0.01, 0.001) = 0.01
    assert math.isclose(_approx_joint_probability(p_i, p_j, rho), 0.01)


def test_merge_legs_no_duplicates():
    a = ["a", "b"]
    b = ["c", "d"]
    expected = ["a", "b", "c", "d"]
    assert _merge_legs(a, b) == expected


def test_merge_legs_with_duplicates():
    a = ["a", "b"]
    b = ["b", "c"]
    expected = ["a", "b", "c"]
    assert _merge_legs(a, b) == expected


def test_merge_legs_with_dict_duplicates():
    a = [{"id": 1}, {"id": 2}]
    b = [{"id": 2}, {"id": 3}]
    result = _merge_legs(a, b)
    assert len(result) == 3
    assert {"id": 1} in result
    assert {"id": 2} in result
    assert {"id": 3} in result
    assert result[1] is not a[1]  # Ensure original dicts are not modified


def test_merge_legs_empty_inputs():
    a = []
    b = []
    expected = []
    assert _merge_legs(a, b) == expected


def test_simulate_joint_probability_no_simulate_fn():
    legs = ["leg1", "leg2"]
    assert _simulate_joint_probability(legs, None, {}) is None


def test_simulate_joint_probability_no_legs():
    mock_fn = MagicMock(return_value=0.7)
    assert _simulate_joint_probability([], mock_fn, {}) is None
    mock_fn.assert_not_called()


def test_simulate_joint_probability_with_simulate_fn_no_cache():
    legs = ["leg1", "leg2"]
    mock_fn = MagicMock(return_value=0.7)
    result = _simulate_joint_probability(legs, mock_fn, None)
    mock_fn.assert_called_once_with(legs)
    assert result == 0.7


def test_simulate_joint_probability_with_simulate_fn_and_cache_miss():
    legs = ["leg1", "leg2"]
    mock_fn = MagicMock(return_value=0.7)
    cache = {}
    result = _simulate_joint_probability(legs, mock_fn, cache)
    mock_fn.assert_called_once_with(legs)
    assert result == 0.7
    assert cache[(_make_hashable("leg1"), _make_hashable("leg2"))] == 0.7


def test_simulate_joint_probability_with_simulate_fn_and_cache_hit():
    legs = ["leg1", "leg2"]
    mock_fn = MagicMock(return_value=0.7)
    cache = {(_make_hashable("leg1"), _make_hashable("leg2")): 0.9}  # Pre-populate cache
    result = _simulate_joint_probability(legs, mock_fn, cache)
    mock_fn.assert_not_called()  # Should not be called if cache hit
    assert result == 0.9


def test_estimate_joint_probability_with_simulate_fn_and_cache(mock_simulate_fn):
    info_i = {"p": 0.5, "exposures": frozenset({"id:t1"}), "legs_for_sim": ["leg_i"]}
    info_j = {"p": 0.6, "exposures": frozenset({"id:t2"}), "legs_for_sim": ["leg_j"]}
    mock_simulate_fn.return_value = 0.35  # Simulated joint probability
    cache = {}

    joint_prob = _estimate_joint_probability(info_i, info_j, mock_simulate_fn, cache)
    # Merged legs: ["leg_i", "leg_j"]
    mock_simulate_fn.assert_called_once()  # Should be called for merged legs
    assert math.isclose(joint_prob, 0.35)


def test_estimate_joint_probability_with_simulate_fn_no_cache(mock_simulate_fn):
    info_i = {"p": 0.5, "exposures": frozenset({"id:t1"}), "legs_for_sim": ["leg_i"]}
    info_j = {"p": 0.6, "exposures": frozenset({"id:t2"}), "legs_for_sim": ["leg_j"]}
    mock_simulate_fn.return_value = 0.35

    joint_prob = _estimate_joint_probability(info_i, info_j, mock_simulate_fn, None)
    mock_simulate_fn.assert_called_once()
    assert math.isclose(joint_prob, 0.35)


def test_estimate_joint_probability_no_simulate_fn_uses_approx():
    info_i = {"p": 0.5, "exposures": frozenset({"id:t1"}), "legs_for_sim": ["leg_i"]}
    info_j = {"p": 0.6, "exposures": frozenset({"id:t1"}), "legs_for_sim": ["leg_j"]}
    # As calculated before, _approx_joint_probability returns 0.5 when p_i=0.5, p_j=0.6, rho=0.85
    joint_prob = _estimate_joint_probability(info_i, info_j, None, {})
    assert math.isclose(joint_prob, 0.5, rel_tol=1e-4)


def test_estimate_joint_probability_with_copula_monte_carlo():
    info_i = {"p": 0.5, "exposures": frozenset({"id:t1"})}
    info_j = {"p": 0.6, "exposures": frozenset({"id:t1"})}

    with patch.object(ev_calculator, "_COPULA_MONTE_CARLO") as mock_copula:
        mock_copula.return_value = 0.45
        joint_prob = _estimate_joint_probability(info_i, info_j, None, {})
        mock_copula.assert_called_once()
        assert math.isclose(joint_prob, 0.45)


def test_covariance_from_joint_positive():
    info_i = {"p": 0.5, "ev": 0.2, "win_value": 15, "loss_value": -10}
    info_j = {"p": 0.4, "ev": 0.1, "win_value": 20, "loss_value": -5}
    joint = 0.3  # Higher than p_i*p_j (0.2)
    covariance = _covariance_from_joint(info_i, info_j, joint)
    assert covariance > 0


def test_covariance_from_joint_negative():
    info_i = {"p": 0.5, "ev": 0.2, "win_value": 15, "loss_value": -10}
    info_j = {"p": 0.4, "ev": 0.1, "win_value": 20, "loss_value": -5}
    joint = 0.1  # Lower than p_i*p_j (0.2)
    covariance = _covariance_from_joint(info_i, info_j, joint)
    assert covariance < 0


def test_covariance_from_joint_zero_probability():
    info_i = {"p": 0.0, "ev": 0, "win_value": 0, "loss_value": 0}
    info_j = {"p": 0.0, "ev": 0, "win_value": 0, "loss_value": 0}
    joint = 0.0
    covariance = _covariance_from_joint(info_i, info_j, joint)
    assert math.isclose(covariance, 0.0)


def test_compute_joint_moments_no_tickets():
    adjustment, details = compute_joint_moments([])
    assert adjustment == 0.0
    assert details == []


def test_compute_joint_moments_fewer_than_min_tickets():
    ticket_infos = [
        {"exposures": frozenset({"id:t1"}), "p": 0.5, "ev": 0, "win_value": 0, "loss_value": 0}
    ]
    adjustment, details = compute_joint_moments(ticket_infos)
    assert adjustment == 0.0
    assert details == []


def test_compute_joint_moments_no_shared_exposures():
    ticket_infos = [
        {
            "exposures": frozenset({"id:t1"}),
            "p": 0.5,
            "ev": 0.2,
            "win_value": 15,
            "loss_value": -10,
            "label": "T1",
        },
        {
            "exposures": frozenset({"id:t2"}),
            "p": 0.4,
            "ev": 0.1,
            "win_value": 20,
            "loss_value": -5,
            "label": "T2",
        },
    ]
    adjustment, details = compute_joint_moments(ticket_infos)
    assert adjustment == 0.0
    assert details == []


def test_compute_joint_moments_with_shared_exposures_positive_covariance(mock_simulate_fn):
    ticket_infos = [
        {
            "exposures": frozenset({"id:shared"}),
            "p": 0.5,
            "ev": 0.2,
            "win_value": 15,
            "loss_value": -10,
            "label": "T1",
        },
        {
            "exposures": frozenset({"id:shared"}),
            "p": 0.4,
            "ev": 0.1,
            "win_value": 20,
            "loss_value": -5,
            "label": "T2",
        },
    ]
    mock_simulate_fn.return_value = 0.3  # To get a positive covariance. joint > p_i * p_j (0.2)

    adjustment, details = compute_joint_moments(ticket_infos, simulate_fn=mock_simulate_fn)
    assert adjustment > 0.0
    assert len(details) == 1
    assert details[0]["tickets"] == ("T1", "T2")
    assert "covariance" in details[0]
    assert details[0]["covariance"] > 0


def test_compute_joint_moments_with_shared_exposures_negative_covariance(mock_simulate_fn):
    ticket_infos = [
        {
            "exposures": frozenset({"id:shared"}),
            "p": 0.5,
            "ev": 0.2,
            "win_value": 15,
            "loss_value": -10,
            "label": "T1",
        },
        {
            "exposures": frozenset({"id:shared"}),
            "p": 0.4,
            "ev": 0.1,
            "win_value": 20,
            "loss_value": -5,
            "label": "T2",
        },
    ]
    mock_simulate_fn.return_value = 0.1  # To get a negative covariance. joint < p_i * p_j (0.2)

    # Patch _covariance_from_joint to return a known negative value for this test
    with patch("hippique_orchestrator.ev_calculator._covariance_from_joint", return_value=-50.02):
        adjustment, details = compute_joint_moments(ticket_infos, simulate_fn=mock_simulate_fn)
        assert adjustment < 0.0
        assert len(details) == 1
        assert details[0]["covariance"] < 0


def test_compute_joint_moments_covariance_below_threshold():
    ticket_infos = [
        {
            "exposures": frozenset({"id:shared"}),
            "p": 0.5,
            "ev": 0.0,
            "win_value": 1,
            "loss_value": -1,
            "label": "T1",
        },
        {
            "exposures": frozenset({"id:shared"}),
            "p": 0.5,
            "ev": 0.0,
            "win_value": 1,
            "loss_value": -1,
            "label": "T2",
        },
    ]
    # If covariance is very small (e.g., tickets are almost independent, or stakes are small),
    # it should be ignored. For this test, manually construct a scenario where covariance is near 0.
    with patch("hippique_orchestrator.ev_calculator._covariance_from_joint", return_value=1e-13):
        adjustment, details = compute_joint_moments(ticket_infos)
        assert adjustment == 0.0
        assert details == []


@pytest.mark.parametrize(
    "total_ev,total_variance,bankroll,baseline_variance,expected_ror",
    [
        (0.1, 0.01, 100, None, 0.0),  # No variance -> 0.0 ROR
        (0.0, 0.01, 100, None, 1.0),  # No EV -> 1.0 ROR
        (0.1, 0.0, 100, None, 0.0),  # Zero variance -> 0.0 ROR (handled above)
        (0.1, 0.01, 100, 0.02, 0.0),  # Baseline variance applied, effectively increasing variance
        (0.1, 0.01, 100, 0.005, 0.0),  # Baseline variance not applied
        (0.01, 0.01, 1, None, 0.1353352832366127),  # Basic calculation e^(-2*0.01*1/0.01) = e^(-2)
    ],
)
def test_risk_of_ruin(total_ev, total_variance, bankroll, baseline_variance, expected_ror):
    if baseline_variance is not None:
        result = risk_of_ruin(
            total_ev, total_variance, bankroll, baseline_variance=baseline_variance
        )
    else:
        result = risk_of_ruin(total_ev, total_variance, bankroll)
    assert math.isclose(result, expected_ror, rel_tol=1e-9)


def test_risk_of_ruin_invalid_bankroll():
    with pytest.raises(ValueError, match=r"bankroll must be > 0"):
        risk_of_ruin(0.1, 0.01, 0)
    with pytest.raises(ValueError, match=r"bankroll must be > 0"):
        risk_of_ruin(0.1, 0.01, -10)


def test_risk_of_ruin_respects_baseline_variance():
    # When actual variance is less than baseline, baseline should be used
    ev = 0.1
    variance = 0.01
    bankroll = 100
    baseline_variance = 0.05
    # Effective variance becomes 0.05 for calculation
    expected_ror = math.exp(-2 * ev * bankroll / baseline_variance)
    assert math.isclose(
        risk_of_ruin(ev, variance, bankroll, baseline_variance=baseline_variance), expected_ror
    )

    # When actual variance is greater than baseline, actual variance should be used
    baseline_variance_ignored = 0.005
    expected_ror_actual_var = math.exp(-2 * ev * bankroll / variance)
    assert math.isclose(
        risk_of_ruin(ev, variance, bankroll, baseline_variance=baseline_variance_ignored),
        expected_ror_actual_var,
    )


def test_optimize_stake_allocation_with_scipy(mock_calculate_kelly_fraction):
    # Mock scipy.optimize.minimize to always return success with predefined fractions
    mock_minimize_result = MagicMock()
    mock_minimize_result.success = True
    mock_minimize_result.x = [0.2, 0.1]  # Example optimized fractions
    with patch("hippique_orchestrator.ev_calculator.minimize", return_value=mock_minimize_result):
        tickets = [
            {"p": 0.5, "odds": 2.0, "stake": 0, "id": "t1"},
            {"p": 0.3, "odds": 4.0, "stake": 0, "id": "t2"},
        ]
        budget = 100.0
        kelly_cap = 0.5
        mock_calculate_kelly_fraction.side_effect = [0.4, 0.2]  # For t1 and t2 caps

        optimized_stakes = optimize_stake_allocation(tickets, budget, kelly_cap)
        assert len(optimized_stakes) == 2
        assert math.isclose(optimized_stakes[0], budget * 0.2)
        assert math.isclose(optimized_stakes[1], budget * 0.1)


def test_optimize_stake_allocation_without_scipy_fallback_to_grid_search(
    mock_calculate_kelly_fraction,
):
    with patch(
        "hippique_orchestrator.ev_calculator.minimize", None
    ):  # Simulate scipy not available
        tickets = [
            {"p": 0.5, "odds": 2.0, "stake": 0, "id": "t1"},
            {"p": 0.3, "odds": 4.0, "stake": 0, "id": "t2"},
        ]
        budget = 100.0
        kelly_cap = 0.5
        mock_calculate_kelly_fraction.side_effect = [0.4, 0.2]  # For t1 and t2 caps

        # Grid search is hard to assert precisely without mocking random or iterating the exact steps.
        # We'll check if it returns non-negative stakes that sum up to less than or equal to budget.
        optimized_stakes = optimize_stake_allocation(tickets, budget, kelly_cap)

        assert len(optimized_stakes) == 2
        assert all(s >= 0 for s in optimized_stakes)
        assert sum(optimized_stakes) <= budget + ev_calculator.GRID_SEARCH_TOLERANCE * budget


def test_optimize_stake_allocation_empty_tickets():
    tickets = []  # Empty list of tickets
    with patch("hippique_orchestrator.ev_calculator.minimize", None):  # Force grid search path
        optimized_stakes = optimize_stake_allocation(tickets, 100.0, 0.5)
        assert optimized_stakes == []


# Test added to cover the ImportError fallback for scipy.optimize


def test_process_single_ticket_p_provided(mock_calculate_kelly_fraction):
    t = {"p": 0.5, "odds": 2.0, "stake": 10.0}
    config = ev_calculator.ProcessTicketsConfig(
        budget=100.0,
        simulate_fn=None,
        cache_simulations=False,
        kelly_cap=DEFAULT_KELLY_CAP,
        round_to=0.0,
    )
    cache = {}
    mock_calculate_kelly_fraction.side_effect = [
        0.0,  # for _kelly_fraction(p, odds)
        0.0,  # for calculate_kelly_fraction(p, odds, lam=config.kelly_cap, cap=1.0)
    ]

    result = _process_single_ticket(t, config, cache)
    assert result["p"] == 0.5
    assert result["odds"] == 2.0
    assert (
        result["stake"] == 0.0
    )  # Expected to be capped at 0.0 due to Kelly calculation for p=0.5, odds=2.0
    assert "clv" in result
    assert "dependencies" in result


def test_process_single_ticket_legs_provided_simulated_p(
    mock_simulate_fn, mock_calculate_kelly_fraction
):
    t = {"legs": ["leg_a"], "odds": 2.0}
    config = ev_calculator.ProcessTicketsConfig(
        budget=100.0,
        simulate_fn=mock_simulate_fn,
        cache_simulations=False,
        kelly_cap=DEFAULT_KELLY_CAP,
        round_to=0.0,
    )
    cache = {}
    mock_simulate_fn.return_value = 0.6  # Simulated probability
    # For _kelly_fraction(0.6, 2.0) -> kelly_fraction = (0.6 * 2 - 1) / (2 - 1) = 0.2
    # For calculate_kelly_fraction(0.6, 2.0, lam=DEFAULT_KELLY_CAP, cap=1.0) -> 0.6 * 0.2 = 0.12
    mock_calculate_kelly_fraction.side_effect = [
        0.2,  # for _kelly_fraction
        0.12,  # for calculate_kelly_fraction (max_stake)
    ]

    result = _process_single_ticket(t, config, cache)
    assert result["p"] == 0.6
    mock_simulate_fn.assert_called_once_with(["leg_a"])
    assert math.isclose(result["stake"], 0.12 * config.budget)


def test_process_single_ticket_legs_provided_simulated_p_cached(
    mock_simulate_fn, mock_calculate_kelly_fraction
):
    t = {"legs": ["leg_a"], "odds": 2.0}
    config = ev_calculator.ProcessTicketsConfig(
        budget=100.0,
        simulate_fn=mock_simulate_fn,
        cache_simulations=True,
        kelly_cap=DEFAULT_KELLY_CAP,
        round_to=0.0,
    )
    cache = {(_make_hashable("leg_a"),): 0.7}  # Pre-cached probability
    mock_simulate_fn.return_value = 0.6  # This should not be used
    # For _kelly_fraction(0.7, 2.0) -> kelly_fraction = (0.7 * 2 - 1) / (2 - 1) = 0.4
    # For calculate_kelly_fraction(0.7, 2.0, lam=DEFAULT_KELLY_CAP, cap=1.0) -> 0.6 * 0.4 = 0.24
    mock_calculate_kelly_fraction.side_effect = [
        0.4,  # for _kelly_fraction
        0.24,  # for calculate_kelly_fraction (max_stake)
    ]

    result = _process_single_ticket(t, config, cache)
    assert result["p"] == 0.7
    mock_simulate_fn.assert_not_called()  # Should use cache
    assert math.isclose(result["stake"], 0.24 * config.budget)


def test_process_single_ticket_no_p_or_legs_raises_value_error():
    t = {"odds": 2.0}
    config = ev_calculator.ProcessTicketsConfig(
        budget=100.0,
        simulate_fn=None,
        cache_simulations=False,
        kelly_cap=DEFAULT_KELLY_CAP,
        round_to=0.0,
    )
    cache = {}
    with pytest.raises(ValueError, match=r"Ticket must include probability 'p'"):
        _process_single_ticket(t, config, cache)


def test_process_single_ticket_invalid_p_raises_value_error():
    t = {"p": 0.0, "odds": 2.0}
    config = ev_calculator.ProcessTicketsConfig(
        budget=100.0,
        simulate_fn=None,
        cache_simulations=False,
        kelly_cap=DEFAULT_KELLY_CAP,
        round_to=0.0,
    )
    cache = {}
    with pytest.raises(ValueError, match=r"probability must be in \(0,1\)"):
        _process_single_ticket(t, config, cache)


def test_process_single_ticket_invalid_odds_raises_value_error():
    t = {"p": 0.5, "odds": 1.0}
    config = ev_calculator.ProcessTicketsConfig(
        budget=100.0,
        simulate_fn=None,
        cache_simulations=False,
        kelly_cap=DEFAULT_KELLY_CAP,
        round_to=0.0,
    )
    cache = {}
    with pytest.raises(ValueError, match=r"odds must be > 1"):
        _process_single_ticket(t, config, cache)


def test_process_single_ticket_stake_capping_and_rounding(mock_calculate_kelly_fraction):
    t = {"p": 0.5, "odds": 3.0, "stake": 50.0}  # Initial stake higher than max_stake
    config = ev_calculator.ProcessTicketsConfig(
        budget=100.0,
        simulate_fn=None,
        cache_simulations=False,
        kelly_cap=0.1,
        round_to=5.0,  # High initial stake, low kelly_cap, rounding
    )
    cache = {}
    # For p=0.5, odds=3.0, kelly_fraction is 0.25
    # For lam=0.1 (config.kelly_cap), calculate_kelly_fraction returns 0.1 * 0.25 = 0.025
    mock_calculate_kelly_fraction.side_effect = [
        0.25,  # for _kelly_fraction(p, odds)
        0.025,  # for calculate_kelly_fraction(p, odds, lam=config.kelly_cap, cap=1.0)
    ]

    result = _process_single_ticket(t, config, cache)
    assert result["capped"] is True
    # max_stake = 0.025 * 100 = 2.5.
    # stake = min(50.0, 2.5) = 2.5.
    # Rounded to 5.0 (due to round_to=5.0) -> round(2.5/5.0)*5.0 = round(0.5)*5.0 = 0*5.0 = 0.0
    assert math.isclose(result["stake"], 0.0)


def test_process_tickets_basic_functionality(mock_simulate_fn, mock_calculate_kelly_fraction):
    tickets_input = [
        {"p": 0.5, "odds": 2.0, "stake": 10.0},
        {"legs": ["leg_b"], "odds": 3.0, "stake": 5.0},
    ]
    config = ev_calculator.ProcessTicketsConfig(
        budget=100.0,
        simulate_fn=mock_simulate_fn,
        cache_simulations=False,
        kelly_cap=DEFAULT_KELLY_CAP,
        round_to=0.0,
    )
    cache = {}
    mock_simulate_fn.return_value = 0.3  # Simulated probability for second ticket
    # For first ticket: p=0.5, odds=2.0 -> kelly_fraction = 0.0
    # For second ticket: p=0.3, odds=3.0 -> kelly_fraction = -0.05 (capped at 0.0 for stake)
    mock_calculate_kelly_fraction.side_effect = [
        0.0,
        0.0,  # for ticket 1 (_kelly_fraction, calculate_kelly_fraction)
        0.0,
        0.0,  # for ticket 2 (_kelly_fraction, calculate_kelly_fraction)
    ]

    processed, total_clv, clv_count, has_combined = _process_tickets(tickets_input, config, cache)

    assert len(processed) == 2
    assert processed[0]["p"] == 0.5
    assert processed[1]["p"] == 0.3  # From mock_simulate_fn
    assert math.isclose(processed[0]["clv"], 0.0)
    assert math.isclose(processed[1]["clv"], 0.0)
    assert clv_count == 2
    assert has_combined is True


def test_calculate_ticket_metrics_single_ticket():
    processed = [
        {
            "ticket": {"id": "t1"},
            "p": 0.5,
            "odds": 2.0,
            "stake": 10.0,
            "kelly_stake": 10.0,
            "max_stake": 10.0,
            "capped": False,
            "clv": 0.0,
            "dependencies": {"exposures": frozenset({"id:t1"}), "legs": ()},
        }
    ]

    (
        total_ev,
        total_variance,
        total_expected_payout,
        combined_expected_payout,
        ticket_metrics,
        covariance_inputs,
    ) = _calculate_ticket_metrics(processed)

    # ev = 10 * (0.5 * (2-1) - (1-0.5)) = 10 * (0.5 - 0.5) = 0
    assert math.isclose(total_ev, 0.0)
    # variance = 0.5 * (10*(2-1))^2 + 0.5 * (-10)^2 - 0^2 = 0.5 * 100 + 0.5 * 100 = 100
    assert math.isclose(total_variance, 100.0)
    # expected_payout = 0.5 * 10 * 2 = 10
    assert math.isclose(total_expected_payout, 10.0)
    assert math.isclose(combined_expected_payout, 0.0)  # Not a combined bet
    assert len(ticket_metrics) == 1
    assert math.isclose(ticket_metrics[0]["ev"], 0.0)
    assert len(covariance_inputs) == 1


def test_calculate_ticket_metrics_with_combined_ticket():
    processed = [
        {
            "ticket": {"id": "t1", "legs": ["leg1"]},  # Mark as combined
            "p": 0.5,
            "odds": 2.0,
            "stake": 10.0,
            "kelly_stake": 10.0,
            "max_stake": 10.0,
            "capped": False,
            "clv": 0.0,
            "dependencies": {"exposures": frozenset({"id:t1", "leg:leg1"}), "legs": ("leg1",)},
        }
    ]
    (
        total_ev,
        total_variance,
        total_expected_payout,
        combined_expected_payout,
        ticket_metrics,
        covariance_inputs,
    ) = _calculate_ticket_metrics(processed)
    assert math.isclose(combined_expected_payout, 10.0)


def test_calculate_final_metrics_green_flag():
    config = ev_calculator.FinalMetricsConfig(
        total_ev=10.0,
        total_variance=100.0,
        total_stake_normalized=50.0,
        budget=100.0,
        total_variance_naive=100.0,
        has_combined=False,
        combined_expected_payout=0.0,
        ror_threshold=0.5,
        ev_threshold=0.1,
        roi_threshold=0.1,
        variance_cap=None,
        variance_exceeded=False,
        total_clv=0.0,
        clv_count=0,
        covariance_adjustment=0.0,
        covariance_details=[],
        ticket_metrics=[],
        total_expected_payout=0.0,
    )
    with patch(
        "hippique_orchestrator.ev_calculator.risk_of_ruin", return_value=0.1
    ):  # Low risk of ruin
        result = _calculate_final_metrics(config)
        assert result["green"] is True
        assert "failure_reasons" not in result


def test_calculate_final_metrics_red_flag_ev_ratio():
    config = ev_calculator.FinalMetricsConfig(
        total_ev=1.0,  # Low EV
        total_variance=100.0,
        total_stake_normalized=50.0,
        budget=100.0,
        total_variance_naive=100.0,
        has_combined=False,
        combined_expected_payout=0.0,
        ror_threshold=None,
        ev_threshold=0.1,  # High threshold for EV ratio
        roi_threshold=0.0,
        variance_cap=None,
        variance_exceeded=False,
        total_clv=0.0,
        clv_count=0,
        covariance_adjustment=0.0,
        covariance_details=[],
        ticket_metrics=[],
        total_expected_payout=0.0,
    )
    with patch("hippique_orchestrator.ev_calculator.risk_of_ruin", return_value=0.1):
        result = _calculate_final_metrics(config)
        assert result["green"] is False
        assert "EV ratio below 0.10" in result["failure_reasons"]


def test_calculate_final_metrics_red_flag_ror():
    config = ev_calculator.FinalMetricsConfig(
        total_ev=10.0,
        total_variance=100.0,
        total_stake_normalized=50.0,
        budget=100.0,
        total_variance_naive=100.0,
        has_combined=False,
        combined_expected_payout=0.0,
        ror_threshold=0.05,  # Low ROR threshold
        ev_threshold=0.0,
        roi_threshold=0.0,
        variance_cap=None,
        variance_exceeded=False,
        total_clv=0.0,
        clv_count=0,
        covariance_adjustment=0.0,
        covariance_details=[],
        ticket_metrics=[],
        total_expected_payout=0.0,
    )
    with patch(
        "hippique_orchestrator.ev_calculator.risk_of_ruin", return_value=0.1
    ):  # High risk of ruin
        result = _calculate_final_metrics(config)
        assert result["green"] is False
        assert "risk of ruin above 5.00%" in result["failure_reasons"]


def test_compute_ev_roi_basic_functionality(mock_simulate_fn, sample_tickets):
    budget = 100.0
    # Processed tickets will have stakes adjusted by _apply_dutching
    # For simplicity, mock the internal calculations for this higher-level test
    with (
        patch("hippique_orchestrator.ev_calculator._apply_dutching") as mock_apply_dutching,
        patch("hippique_orchestrator.ev_calculator._process_tickets") as mock_process_tickets,
        patch("hippique_orchestrator.ev_calculator._adjust_stakes") as mock_adjust_stakes,
        patch("hippique_orchestrator.ev_calculator._calculate_ticket_metrics") as mock_calc_metrics,
        patch("hippique_orchestrator.ev_calculator.compute_joint_moments") as mock_joint_moments,
        patch("hippique_orchestrator.ev_calculator._calculate_final_metrics") as mock_final_metrics,
    ):
        # _process_tickets returns (processed, total_clv, clv_count, has_combined)
        mock_process_tickets.return_value = (
            [
                {
                    "ticket": t,
                    "p": t["p"],
                    "odds": t["odds"],
                    "stake": t["stake"],
                    "clv": 0.0,
                    "dependencies": {"exposures": frozenset()},
                }
                for t in sample_tickets
            ],
            0.0,
            3,
            False,
        )  # clv_count is 3 for sample tickets
        mock_adjust_stakes.return_value = 50.0  # total_stake_normalized
        # _calculate_ticket_metrics returns (total_ev, total_variance, total_expected_payout, combined_expected_payout, ticket_metrics, covariance_inputs)
        mock_calc_metrics.return_value = (
            10.0,  # total_ev
            100.0,  # total_variance
            200.0,  # total_expected_payout
            0.0,  # combined_expected_payout
            [],  # ticket_metrics
            [
                {
                    "exposures": frozenset({"id:t1"}),
                    "p": 0.5,
                    "ev": 0.2,
                    "win_value": 15,
                    "loss_value": -10,
                    "label": "T1",
                }
            ],  # Non-empty covariance_inputs
        )
        mock_joint_moments.return_value = (0.0, [])
        mock_final_metrics.return_value = {"ev": 10.0, "green": True}

        result = compute_ev_roi(sample_tickets, budget, simulate_fn=mock_simulate_fn)

        mock_apply_dutching.assert_called_once_with(sample_tickets)
        mock_process_tickets.assert_called_once()
        mock_adjust_stakes.assert_called_once()
        mock_calc_metrics.assert_called_once()
        mock_joint_moments.assert_called_once()
        mock_final_metrics.assert_called_once()

        assert result["ev"] == 10.0
        assert result["green"] is True


def test_compute_ev_roi_invalid_budget():
    with pytest.raises(ValueError, match=r"budget must be > 0"):
        compute_ev_roi([], 0)
    with pytest.raises(ValueError, match=r"budget must be > 0"):
        compute_ev_roi([], -10)


def test_compute_ev_roi_invalid_variance_cap_config():
    with pytest.raises(ValueError, match=r"variance_cap must be > 0"):
        compute_ev_roi([], 100, config={"variance_cap": 0})
    with pytest.raises(ValueError, match=r"variance_cap must be > 0"):
        compute_ev_roi([], 100, config={"variance_cap": -1})


def test_compute_ev_roi_with_optimize_true(mock_simulate_fn, sample_tickets):
    budget = 100.0
    with (
        patch("hippique_orchestrator.ev_calculator._apply_dutching"),
        patch("hippique_orchestrator.ev_calculator._process_tickets") as mock_process_tickets,
        patch("hippique_orchestrator.ev_calculator._adjust_stakes") as mock_adjust_stakes,
        patch("hippique_orchestrator.ev_calculator._calculate_ticket_metrics") as mock_calc_metrics,
        patch("hippique_orchestrator.ev_calculator.compute_joint_moments"),
        patch("hippique_orchestrator.ev_calculator._calculate_final_metrics") as mock_final_metrics,
        patch(
            "hippique_orchestrator.ev_calculator.optimize_stake_allocation"
        ) as mock_optimize_stake,
    ):
        # _process_tickets returns (processed, total_clv, clv_count, has_combined)
        mock_process_tickets.return_value = (
            [
                {
                    "ticket": t,
                    "p": t["p"],
                    "odds": t["odds"],
                    "stake": t["stake"],
                    "clv": 0.0,
                    "dependencies": {"exposures": frozenset()},
                }
                for t in sample_tickets
            ],
            0.0,
            3,
            False,
        )
        # Mock initial calculations
        mock_calc_metrics.side_effect = [
            (10.0, 100.0, 200.0, 0.0, [{"ev": 10.0, "stake": 50.0}], []),  # Initial metrics
            (12.0, 120.0, 220.0, 0.0, [{"ev": 12.0, "stake": 60.0}], []),  # Optimized metrics
        ]
        # optimized_stakes_list should have 3 elements to match sample_tickets
        mock_optimize_stake.return_value = [60.0, 20.0, 5.0]

        # The mock_final_metrics.return_value should also reflect all optimized stakes
        mock_final_metrics.return_value = {
            "ev": 12.0,
            "green": True,
            "optimized_stakes": [60.0, 20.0, 5.0],
        }
        mock_adjust_stakes.return_value = 50.0  # Make sure adjust_stakes returns a float

        result = compute_ev_roi(
            sample_tickets, budget, simulate_fn=mock_simulate_fn, config={"optimize": True}
        )

        mock_optimize_stake.assert_called_once()
        assert result["ev"] == 12.0
        assert result["optimized_stakes"] == [60.0, 20.0, 5.0]
        assert "ev_individual" in result
        assert "ticket_metrics_individual" in result
        assert "calibrated_expected_payout_individual" in result


def test_compute_ev_roi_variance_capping(mock_simulate_fn, sample_tickets):
    budget = 100.0
    with (
        patch("hippique_orchestrator.ev_calculator._apply_dutching"),
        patch("hippique_orchestrator.ev_calculator._process_tickets") as mock_process_tickets,
        patch("hippique_orchestrator.ev_calculator._adjust_stakes") as mock_adjust_stakes,
        patch("hippique_orchestrator.ev_calculator._calculate_ticket_metrics") as mock_calc_metrics,
        patch("hippique_orchestrator.ev_calculator.compute_joint_moments"),
        patch("hippique_orchestrator.ev_calculator._calculate_final_metrics") as mock_final_metrics,
    ):
        # Create a deep copy of sample_tickets to simulate modification in _calculate_ticket_metrics
        tickets_with_ev = [t.copy() for t in sample_tickets]
        for t in tickets_with_ev:
            t["ev"] = 10.0  # Add 'ev' key for the scaling loop
            t["stake"] = 50.0  # Add 'stake' key
            t["variance"] = 1000.0  # Add 'variance' key
            t["roi"] = 0.2  # Add 'roi' key
            t["expected_payout"] = 200.0  # Add 'expected_payout' key

        # _process_tickets returns (processed, total_clv, clv_count, has_combined)
        mock_process_tickets.return_value = (
            [
                {
                    "ticket": t,
                    "p": t["p"],
                    "odds": t["odds"],
                    "stake": t["stake"],
                    "clv": 0.0,
                    "dependencies": {"exposures": frozenset()},
                }
                for t in tickets_with_ev
            ],
            0.0,
            3,
            False,
        )
        # Initial metrics with high variance
        mock_calc_metrics.return_value = (
            10.0,  # total_ev
            1000.0,  # total_variance (exceeds cap)
            200.0,  # total_expected_payout
            0.0,  # combined_expected_payout
            [
                {
                    "ev": 10.0,
                    "stake": 50.0,
                    "variance": 1000.0,
                    "roi": 0.2,
                    "expected_payout": 200.0,
                },  # For ticket 1
                {
                    "ev": 5.0,
                    "stake": 20.0,
                    "variance": 500.0,
                    "roi": 0.1,
                    "expected_payout": 100.0,
                },  # For ticket 2
                {
                    "ev": 2.0,
                    "stake": 10.0,
                    "variance": 200.0,
                    "roi": 0.05,
                    "expected_payout": 50.0,
                },  # For ticket 3
            ],
            [],  # covariance_inputs
        )
        mock_final_metrics.return_value = {"ev": 5.0, "green": False, "variance_exceeded": True}
        mock_adjust_stakes.return_value = 150.0  # Make sure adjust_stakes returns a float

        result = compute_ev_roi(
            tickets_with_ev, budget, simulate_fn=mock_simulate_fn, config={"variance_cap": 0.01}
        )

        # Verify that scaling happens due to variance cap
        assert result["ev"] == 5.0  # Example scaled value
        assert result["variance_exceeded"] is True
