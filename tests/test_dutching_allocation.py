from hippique.utils.dutching import equal_profit_stakes


def test_equal_profit_stakes_sum():
    stakes = equal_profit_stakes([3.0, 4.0], total_stake=3.0)
    assert abs(sum(stakes) - 3.0) < 1e-9
