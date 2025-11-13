from hippique.utils.probabilities import expected_value_simple, no_vig_probs


def test_no_vig_sum_to_one():
    probs = no_vig_probs([2.5, 3.0, 4.0])
    assert abs(sum(probs) - 1.0) < 1e-9


def test_ev_drops_when_margin_higher():
    odds_low_margin = [2.5, 3.0, 4.0]
    odds_high_margin = [2.2, 2.6, 3.6]

    probs_low = no_vig_probs(odds_low_margin)
    probs_high = no_vig_probs(odds_high_margin)

    ev_low = sum(
        expected_value_simple(prob, odds, 1.0)
        for prob, odds in zip(probs_low, odds_low_margin, strict=False)
    )
    ev_high = sum(
        expected_value_simple(prob, odds, 1.0)
        for prob, odds in zip(probs_high, odds_high_margin, strict=False)
    )
    assert ev_high <= ev_low
