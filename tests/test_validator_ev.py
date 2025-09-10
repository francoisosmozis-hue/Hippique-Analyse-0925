import pytest
from validator_ev import validate

def sample(h):
    return {
        "runners":[
            {"id":"1","name":"A","odds":2.5,"je_stats":{"j_win":10,"e_win":11}},
            {"id":"2","name":"B","odds":3.5,"je_stats":{"j_win":9,"e_win":8}}
        ]
    }

def test_validate_ok():
    h30=sample("H30")
    h5=sample("H05")
    assert validate(h30,h5,allow_je_na=False)

def test_incoherent_partants():
    h30=sample("H30")
    h5=sample("H05")
    h5["runners"].append({"id":"3","name":"C","odds":5.0,"je_stats":{"j_win":7,"e_win":7}})
    with pytest.raises(ValueError):
        validate(h30,h5,allow_je_na=False)    

def test_missing_stats_blocked():
    h30=sample("H30")
    h5=sample("H05")
    del h5["runners"][0]["je_stats"]
    with pytest.raises(ValueError):
        validate(h30,h5,allow_je_na=False)
