
import pytest
from src.kelly import kelly_fraction, kelly_stake

@pytest.mark.parametrize(
    "p, odds, lam, cap, expected",
    [
        # Basic positive case
        (0.5, 3.0, 1.0, 1.0, 0.25),
        # Negative edge (should return 0)
        (0.2, 3.0, 1.0, 1.0, 0.0),
        # Zero edge (should return 0)
        (1/3, 3.0, 1.0, 1.0, 0.0),
        # Test with lambda (fractional Kelly)
        (0.5, 3.0, 0.5, 1.0, 0.125),
        # Test with cap
        (0.8, 3.0, 1.0, 0.2, 0.2),
        # Test with both lambda and cap
        (0.8, 3.0, 0.5, 0.3, 0.3), # f = 0.7 * 0.5 = 0.35, capped at 0.3
        # --- Input Validation Cases ---
        # Invalid p
        (1.5, 3.0, 1.0, 1.0, 0.0),
        (0.0, 3.0, 1.0, 1.0, 0.0),
        (-0.5, 3.0, 1.0, 1.0, 0.0),
        # Invalid odds
        (0.5, 1.0, 1.0, 1.0, 0.0),
        (0.5, 0.5, 1.0, 1.0, 0.0),
        # Invalid lam/cap are handled internally, returning valid fractions
        (0.5, 3.0, -0.5, 1.0, 0.25), # lam defaults to 1.0
        (0.8, 3.0, 1.0, 1.5, 0.7),   # cap defaults to 1.0, f = 0.7
    ],
)
def test_kelly_fraction(p, odds, lam, cap, expected):
    """Tests kelly_fraction with various inputs."""
    assert kelly_fraction(p, odds, lam=lam, cap=cap) == pytest.approx(expected)

def test_kelly_stake():
    """Tests the kelly_stake calculation."""
    # Basic case: 25% of 100€ bankroll
    assert kelly_stake(p=0.5, odds=3.0, bankroll=100) == pytest.approx(25.0)
    # Case with zero bankroll
    assert kelly_stake(p=0.5, odds=3.0, bankroll=0) == 0.0
    # Case with negative edge
    assert kelly_stake(p=0.2, odds=3.0, bankroll=100) == 0.0
