from pathlib import Path


def test_validator_shim():
    from validator_ev_v2 import validate_with_simulate_ev
    assert callable(validate_with_simulate_ev)

def test_runner_chain_snapshot_guard(tmp_path: Path):
    from runner_chain import validate_snapshot_or_die
    snap = {"runners": [{"num": "1"}, {"num": "2"}], "partants": 10}
    validate_snapshot_or_die(snap, "H5")  # ne doit pas sys.exit
