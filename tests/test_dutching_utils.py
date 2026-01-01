import pytest
from hippique.utils.dutching import (
    equal_profit_stakes,
    diversify_guard,
    require_mid_odds,
    CHRONO_CORRELATION_THRESHOLD,
    MID_ODDS_LOWER_BOUND,
    MID_ODDS_UPPER_BOUND,
)


# Tests for equal_profit_stakes
def test_equal_profit_stakes_valid_input():
    odds_list = [2.0, 3.0, 4.0]
    total_stake = 100.0
    stakes = equal_profit_stakes(odds_list, total_stake)
    # Expected stakes calculation:
    # 1/2 + 1/3 + 1/4 = 0.5 + 0.3333 + 0.25 = 1.0833
    # unit_stake = 100 / 1.0833 = 92.30
    # stake1 = 92.30 / 2 = 46.15
    # stake2 = 92.30 / 3 = 30.77
    # stake3 = 92.30 / 4 = 23.07
    # Sum of stakes should be approx total_stake
    assert sum(stakes) == pytest.approx(total_stake)
    # Payouts should be equal
    assert stakes[0] * odds_list[0] == pytest.approx(stakes[1] * odds_list[1])
    assert stakes[1] * odds_list[1] == pytest.approx(stakes[2] * odds_list[2])


def test_equal_profit_stakes_empty_odds_list():
    with pytest.raises(ValueError, match="Odds list cannot be empty"):
        equal_profit_stakes([], 100.0)


@pytest.mark.parametrize("odds_list", [[0.0], [-1.0], [1.0, 0.0], [1.0, -2.0]])
def test_equal_profit_stakes_invalid_odds_list(odds_list):
    with pytest.raises(ValueError, match="Odds must be greater than 1.0"):
        equal_profit_stakes(odds_list, 100.0)


# Tests for diversify_guard
def test_diversify_guard_no_correlation():
    horses_meta = [
        {"ecurie": "E1", "driver": "D1", "chrono_last": 60.0},
        {"ecurie": "E2", "driver": "D2", "chrono_last": 60.1},
    ]
    assert diversify_guard(horses_meta) is True


def test_diversify_guard_correlated_same_stable_driver_within_threshold():
    horses_meta = [
        {"ecurie": "E1", "driver": "D1", "chrono_last": 60.0},
        {"ecurie": "E1", "driver": "D1", "chrono_last": 60.0 + CHRONO_CORRELATION_THRESHOLD / 2},
    ]
    assert diversify_guard(horses_meta) is False


def test_diversify_guard_correlated_same_stable_driver_outside_threshold():
    horses_meta = [
        {"ecurie": "E1", "driver": "D1", "chrono_last": 60.0},
        {"ecurie": "E1", "driver": "D1", "chrono_last": 60.0 + CHRONO_CORRELATION_THRESHOLD * 2},
    ]
    assert diversify_guard(horses_meta) is True


def test_diversify_guard_different_stable_same_driver():
    horses_meta = [
        {"ecurie": "E1", "driver": "D1", "chrono_last": 60.0},
        {"ecurie": "E2", "driver": "D1", "chrono_last": 60.1},
    ]
    assert diversify_guard(horses_meta) is True


def test_diversify_guard_same_stable_different_driver():
    horses_meta = [
        {"ecurie": "E1", "driver": "D1", "chrono_last": 60.0},
        {"ecurie": "E1", "driver": "D2", "chrono_last": 60.1},
    ]
    assert diversify_guard(horses_meta) is True


def test_diversify_guard_missing_ecurie_or_driver_lenient():
    horses_meta = [
        {"ecurie": None, "driver": "D1", "chrono_last": 60.0},
        {"ecurie": "E1", "driver": None, "chrono_last": 60.1},
        {"ecurie": "E1", "driver": "D1", "chrono_last": 60.2},
    ]
    assert diversify_guard(horses_meta) is True


def test_diversify_guard_missing_chrono_lenient():
    horses_meta = [
        {"ecurie": "E1", "driver": "D1", "chrono_last": None},
        {"ecurie": "E1", "driver": "D1", "chrono_last": 60.1},
    ]
    assert diversify_guard(horses_meta) is True


def test_diversify_guard_empty_list():
    assert diversify_guard([]) is True


def test_diversify_guard_single_horse():
    horses_meta = [{"ecurie": "E1", "driver": "D1", "chrono_last": 60.0}]
    assert diversify_guard(horses_meta) is True


# Tests for require_mid_odds
def test_require_mid_odds_found():
    horses_meta = [
        {"name": "Horse1", "odds": 3.0},
        {"name": "Horse2", "odds": 5.5},  # Mid-range
        {"name": "Horse3", "odds": 8.0},
    ]
    assert require_mid_odds(horses_meta) is True


def test_require_mid_odds_not_found_all_low():
    horses_meta = [
        {"name": "Horse1", "odds": 2.0},
        {"name": "Horse2", "odds": 3.9},
    ]
    assert require_mid_odds(horses_meta) is False


def test_require_mid_odds_not_found_all_high():
    horses_meta = [
        {"name": "Horse1", "odds": 7.1},
        {"name": "Horse2", "odds": 10.0},
    ]
    assert require_mid_odds(horses_meta) is False


def test_require_mid_odds_empty_list():
    assert require_mid_odds([]) is False


def test_require_mid_odds_missing_odds():
    horses_meta = [
        {"name": "Horse1", "odds": None},
        {"name": "Horse2", "odds": 2.0},
    ]
    assert require_mid_odds(horses_meta) is False


def test_require_mid_odds_non_numeric_odds_ignored():
    horses_meta = [
        {"name": "Horse1", "odds": "N/A"},
        {"name": "Horse2", "odds": 5.0},
    ]
    assert require_mid_odds(horses_meta) is True
