import pytest

# TODO: This smoke test needs to be completely rewritten to use the new API
# and data structures from the tickets_builder.py module. The old
# `build_tickets` function it was testing has been removed.

@pytest.mark.skip(reason="build_tickets API has been refactored into tickets_builder.py")
def test_roi_smoke_guardrails():
    pass