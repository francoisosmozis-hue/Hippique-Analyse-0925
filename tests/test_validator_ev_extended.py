import pytest
from pathlib import Path
import json
from hippique_orchestrator import validator_ev

@pytest.fixture
def temp_readme(tmp_path):
    """A fixture to create a temporary README.md file."""
    def _create_readme(content):
        readme_path = tmp_path / "README.md"
        readme_path.write_text(content, encoding="utf-8")
        # Monkeypatch the Path class to use the tmp_path
        original_path = validator_ev.Path
        validator_ev.Path = lambda x: tmp_path / x if x == "README.md" else original_path(x)
        return readme_path
    yield _create_readme
    # Restore the original Path class
    from pathlib import Path as original_path_class
    validator_ev.Path = original_path_class


def test_readme_has_roi_sp_success(temp_readme):
    """Tests _readme_has_roi_sp with a valid ROI_SP in README."""
    temp_readme("ROI_SP > 15%")
    assert validator_ev._readme_has_roi_sp(0.10) is True
    assert validator_ev._readme_has_roi_sp(0.15) is True
    assert validator_ev._readme_has_roi_sp(0.20) is False

def test_readme_has_roi_sp_no_match(temp_readme):
    """Tests _readme_has_roi_sp when ROI_SP is not in README."""
    temp_readme("Some other content")
    assert validator_ev._readme_has_roi_sp(0.10) is False

def test_must_have():
    """Tests the must_have helper function."""
    assert validator_ev.must_have("value", "message") == "value"
    with pytest.raises(RuntimeError, match="message"):
        validator_ev.must_have(None, "message")

def test_validate_missing_odds():
    """Tests validate function with missing odds."""
    h30 = {"runners": [{"id": "1"}]}
    h5 = {"runners": [{"id": "1"}]}
    with pytest.raises(ValueError, match="Cotes manquantes H-30 pour 1"):
        validator_ev.validate(h30, h5, False)

def test_validate_invalid_odds():
    """Tests validate function with invalid odds."""
    h30 = {"runners": [{"id": "1", "odds": "invalid"}]}
    h5 = {"runners": [{"id": "1", "odds": "1.5"}]}
    with pytest.raises(ValueError, match="Cote non numérique H-30 pour 1: invalid"):
        validator_ev.validate(h30, h5, False)

def test_validate_missing_je_stats():

    """Tests validate function with missing JE stats."""

    h30 = {"runners": [{"id": "1", "odds": "2.0"}]}

    h5 = {"runners": [{"id": "1", "odds": "1.5"}]}

    with pytest.raises(ValueError, match="Stats J/E manquantes: 1"):

        validator_ev.validate(h30, h5, False)



def test_validate_budget_fails():

    """Tests the failure paths for validate_budget."""

    with pytest.raises(validator_ev.ValidationError, match="Budget cap exceeded"):

        validator_ev.validate_budget({"1": 10, "2": 20}, 25, 0.5)



    with pytest.raises(validator_ev.ValidationError, match="Stake cap exceeded for 1"):

        validator_ev.validate_budget({"1": 15, "2": 10}, 30, 0.4)





def test_prepare_validation_inputs(mocker, tmp_path):

    """Tests the _prepare_validation_inputs function."""

    rc_dir = tmp_path / "R1C1"

    rc_dir.mkdir()



    # Create mock files

    (rc_dir / "partants.json").write_text(json.dumps([{"id": "1"}]))

    (rc_dir / "h5.json").write_text(json.dumps({"1": 2.0}))

    (rc_dir / "stats_je.json").write_text(json.dumps({"coverage": 90}))

    (rc_dir / "gpi.yml").write_text("ALLOW_JE_NA: true")



    args = mocker.MagicMock()

    args.phase = "H5"

    args.artefacts = str(rc_dir)

    args.base_dir = None

    args.reunion = None

    args.course = None

    args.partants = None

    args.odds = None

    args.stats_je = None

    args.config = None

    args.allow_je_na = False



    cfg, partants, odds, stats = validator_ev._prepare_validation_inputs(args)



    assert cfg["ALLOW_JE_NA"] is True

    assert partants == [{"id": "1"}]

    assert odds == {"1": 2.0}

    assert stats == {"coverage": 90}
