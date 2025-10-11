from pipeline_run import _clv_median_ok


def test_clv_gate():
    assert _clv_median_ok([-0.02, 0.00, 0.01, 0.02], 0.0) is True
    assert _clv_median_ok([-0.05, -0.01, -0.02], 0.0) is False
