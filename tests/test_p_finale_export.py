from p_finale_export import export


def test_export_generates_drift_csv(tmp_path):
    output_dir = tmp_path / "export"
    p_finale = {
        "meta": {
            "rc": "R1C1",
            "hippodrome": "Test",
            "date": "2024-01-01",
            "discipline": "plat",
            "model": "alpha",
        },
        "tickets": [],
        "ev": {"global": 0.0},
        "p30": {"1": 0.1, "2": 0.15},
        "p5": {"2": 0.18, "3": 0.05},
    }

    export(output_dir, p_finale)

    drift_path = output_dir / "drift.csv"
    assert drift_path.exists(), "drift.csv should be created"

    lines = drift_path.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == "num;p30;p5;delta;flag"
    assert lines[1:] == [
        "1;0.100;0.000;-0.100;drift",
        "2;0.150;0.180;0.030;steam",
        "3;0.000;0.050;0.050;steam",
    ]
