import pytest

# TODO: This entire test file is disabled because it tests functions
# (should_cut_exotics, _overround_from_odds_win) that have been removed
# or refactored into other modules like tickets_builder.py.
# These tests need to be rewritten to reflect the new architecture.


@pytest.mark.skip(reason="Functionality refactored into tickets_builder.py")
def test_overround_from_odds_win_simple():
    pass


@pytest.mark.skip(reason="Functionality refactored into tickets_builder.py")
def test_should_cut_exotics_when_overround_high():
    pass
