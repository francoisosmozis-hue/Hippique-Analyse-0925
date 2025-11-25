from pathlib import Path


def test_validator_shim():
    from validator_ev_v2 import validate_with_simulate_ev
    assert callable(validate_with_simulate_ev)
