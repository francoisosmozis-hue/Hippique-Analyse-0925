import pytest
from hippique.utils.probabilities import implied_prob_from_odds, no_vig_probs, expected_value_simple

# Tests for implied_prob_from_odds
def test_implied_prob_from_odds_valid_input():
    assert implied_prob_from_odds(2.0) == 0.5
    assert implied_prob_from_odds(4.0) == 0.25
    assert implied_prob_from_odds(1.5) == 1/1.5

def test_implied_prob_from_odds_invalid_input():
    with pytest.raises(ValueError, match="Decimal odds must be > 1.0"):
        implied_prob_from_odds(1.0)
    with pytest.raises(ValueError, match="Decimal odds must be > 1.0"):
        implied_prob_from_odds(0.5)
    with pytest.raises(ValueError, match="Decimal odds must be > 1.0"):
        implied_prob_from_odds(-2.0)

# Tests for no_vig_probs
def test_no_vig_probs_valid_input():
    # Example with no overround, sums to 1.0
    odds_list_1 = [2.0, 2.0]
    expected_probs_1 = [0.5, 0.5]
    assert [round(p, 5) for p in no_vig_probs(odds_list_1)] == expected_probs_1

    # Example with overround, normalizes to 1.0
    odds_list_2 = [2.0, 3.0, 4.0] # Implied: 0.5, 0.333, 0.25. Sum: 1.083
    # Normalized: 0.5/1.083, 0.333/1.083, 0.25/1.083
    expected_probs_2 = [0.46154, 0.30769, 0.23077]
    assert [round(p, 5) for p in no_vig_probs(odds_list_2)] == expected_probs_2

    # Example with integer odds
    odds_list_3 = [3, 3]
    expected_probs_3 = [0.5, 0.5]
    assert [round(p, 5) for p in no_vig_probs(odds_list_3)] == expected_probs_3

def test_no_vig_probs_empty_list():
    with pytest.raises(ValueError, match="Invalid odds list"):
        no_vig_probs([])

def test_no_vig_probs_invalid_odds_in_list():
    with pytest.raises(ValueError, match="Decimal odds must be > 1.0"):
        no_vig_probs([2.0, 1.0])
    with pytest.raises(ValueError, match="Decimal odds must be > 1.0"):
        no_vig_probs([3.0, 0.5])



# Tests for expected_value_simple
def test_expected_value_simple_positive_ev():
    # Example: 60% chance to win, odds 2.0, stake 10
    # EV = 0.6 * 10 * (2.0 - 1.0) - (1.0 - 0.6) * 10 = 0.6 * 10 * 1 - 0.4 * 10 = 6 - 4 = 2
    assert expected_value_simple(0.6, 2.0, 10.0) == 2.0

def test_expected_value_simple_negative_ev():
    # Example: 40% chance to win, odds 2.0, stake 10
    # EV = 0.4 * 10 * (2.0 - 1.0) - (1.0 - 0.4) * 10 = 0.4 * 10 * 1 - 0.6 * 10 = 4 - 6 = -2
    assert expected_value_simple(0.4, 2.0, 10.0) == -2.0

def test_expected_value_simple_zero_ev():
    # Example: 50% chance to win, odds 2.0, stake 10
    # EV = 0.5 * 10 * (2.0 - 1.0) - (1.0 - 0.5) * 10 = 0.5 * 10 * 1 - 0.5 * 10 = 5 - 5 = 0
    assert expected_value_simple(0.5, 2.0, 10.0) == 0.0

def test_expected_value_simple_various_stakes():
    assert expected_value_simple(0.6, 2.0, 5.0) == 1.0
    assert expected_value_simple(0.6, 2.0, 0.0) == 0.0

def test_expected_value_simple_edge_cases():
    # odds very close to 1.0 (invalid but let's test if it handles it gracefully if called directly)
    assert expected_value_simple(0.5, 1.000000000000001, 10.0) > -10.0 and expected_value_simple(0.5, 1.000000000000001, 10.0) < 0
    
    # p_win at extremes
    assert expected_value_simple(1.0, 2.0, 10.0) == 10.0 # Guaranteed win
    assert expected_value_simple(0.0, 2.0, 10.0) == -10.0 # Guaranteed loss
