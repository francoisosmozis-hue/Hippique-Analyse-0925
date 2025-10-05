import json
import math

import pandas as pd
import pytest

from calibration import p_true_model
from calibration.p_true_model import (
    compute_runner_features,
    load_p_true_model,
    predict_probability,
)
from calibration.p_true_training import (
    assemble_history_dataset,
    serialize_model,
    train_logistic_model,
)


def test_assemble_history_dataset(tmp_path):
    base = tmp_path
    race = base / "R1C1"
    race.mkdir()

    report = """id,odds_h5,odds_h30,j_win,e_win\n1,2.5,3.0,10,5\n2,5.0,4.5,3,2\n"""
    (race / "per_horse_report.csv").write_text(report, encoding="utf-8")

    arrival = {"arrival": [{"id": "1", "position": 1}, {"id": "2", "position": 2}]}
    (race / "arrivee_officielle.json").write_text(json.dumps(arrival), encoding="utf-8")

    tickets = {"tickets": [{"legs": [{"id": "1"}, {"id": "3"}]}]}
    (race / "p_finale.json").write_text(json.dumps(tickets), encoding="utf-8")

    df = assemble_history_dataset(base)
    assert set(df["runner_id"]) == {"1", "2"}

    row_winner = df.loc[df["runner_id"] == "1"].iloc[0]
    assert pytest.approx(row_winner["drift"], rel=1e-6) == -0.5
    assert pytest.approx(row_winner["je_total"], rel=1e-6) == 15.0
    assert row_winner["is_winner"] == 1.0
    assert row_winner["was_backed"] == 1.0


def test_train_and_predict_roundtrip(tmp_path, monkeypatch):
    rows = []
    data = [
        ("R1C1", 5.0, 4.0, 10, 8, 1),
        ("R1C1", 4.0, 5.0, 5, 5, 0),
        ("R1C1", 10.0, 12.0, 2, 3, 0),
        ("R1C1", 3.0, 2.5, 12, 12, 0),
        ("R2C1", 2.5, 2.2, 15, 15, 1),
        ("R2C1", 8.0, 7.0, 8, 9, 0),
        ("R2C1", 5.0, 6.0, 6, 5, 0),
        ("R2C1", 12.0, 14.0, 2, 1, 0),
    ]

    for idx, (race, o30, o5, jw, ew, win) in enumerate(data, start=1):
        rows.append(
            {
                "race_id": race,
                "runner_id": str(idx),
                "odds_h5": o5,
                "odds_h30": o30,
                "drift": o5 - o30,
                "log_odds": math.log(o5),
                "implied_prob": 1.0 / o5,
                "j_win": jw,
                "e_win": ew,
                "je_total": jw + ew,
                "was_backed": 0.0,
                "is_winner": float(win),
            }
        )

    df = pd.DataFrame(rows)

    result = train_logistic_model(
        df,
        features=["log_odds", "drift", "je_total", "implied_prob"],
    )

    path = tmp_path / "model.yaml"
    serialize_model(result, path)

    monkeypatch.setattr(p_true_model, "_MODEL_CACHE", None, raising=False)
    model = load_p_true_model(path)
    assert model is not None
    assert set(model.features) == {
        "log_odds",
        "drift",
        "je_total",
        "implied_prob",
    }

    fav_features = compute_runner_features(2.2, 2.5, {"j_win": 15, "e_win": 15})
    outsider_features = compute_runner_features(6.0, 5.0, {"j_win": 5, "e_win": 4})

    p_fav = predict_probability(model, fav_features)
    p_outsider = predict_probability(model, outsider_features)

    assert 0.0 < p_outsider < 1.0
    assert p_fav > p_outsider
