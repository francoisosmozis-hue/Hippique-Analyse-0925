import json

# This is a bit of a hack to import the script
import sys
from pathlib import Path

import pytest

from hippique_orchestrator.scripts import online_fetch_zeturf

# Add the script's directory to the path to allow imports
sys.path.append(str(Path(online_fetch_zeturf.__file__).parent))


@pytest.fixture
def zeturf_course_html():
    """Returns the content of the Zeturf course page fixture."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "zeturf" / "2024-01-11_R1C1.html"
    return fixture_path.read_text(encoding="utf-8")


def test_fallback_parse_html_extracts_data(zeturf_course_html):
    """
    Tests that the _fallback_parse_html function can extract basic information
    from a real (but saved) ZEturf course page.
    """
    parsed_data = online_fetch_zeturf._fallback_parse_html(zeturf_course_html)

    assert parsed_data is not None
    assert isinstance(parsed_data, dict)

    assert parsed_data["meeting"] == "SAINT GALMIER"
    assert parsed_data["discipline"] == "trot"
    assert parsed_data["partants"] == 12

    assert "runners" in parsed_data
    runners = parsed_data["runners"]
    assert isinstance(runners, list)
    assert len(runners) == 2

    # Check a few runners for correctness
    runner_1 = next((r for r in runners if r.get("num") == "1"), None)
    assert runner_1 is not None
    assert runner_1["name"] == "Gagnant"
    assert runner_1["cote"] == "2,5"

    runner_12 = next((r for r in runners if r.get("num") == "2"), None)
    assert runner_12 is not None
    assert runner_12["name"] == "Placé"
    assert runner_12["cote"] == "5,0"

@pytest.mark.parametrize(
    "reunion, course, expected",
    [
        ("R1", "C1", "R1C1"),
        (1, 2, "R1C2"),
        ("R4C5", None, "R4C5"),
    ],
)
def test_normalise_rc_tag(reunion, course, expected):
    assert online_fetch_zeturf._normalise_rc_tag(reunion, course) == expected


def test_normalise_rc_tag_raises_error():
    with pytest.raises(ValueError, match="C value is required"):
        online_fetch_zeturf._normalise_rc_tag("R3", None)


def test_coerce_runner_entry():
    raw_runner = {
        "num": "1",
        "name": "Test Horse",
        "cote": "10,5",
        "odds_place": "2.5",
    }
    coerced = online_fetch_zeturf._coerce_runner_entry(raw_runner)
    assert coerced["num"] == "1"
    assert coerced["name"] == "Test Horse"
    assert coerced["cote"] == 10.5
    assert coerced["odds_place"] == 2.5


def test_build_snapshot_payload():
    raw_snapshot = {
        "meeting": "Test Meeting",
        "date": "2025-01-01",
        "discipline": "Test Discipline",
        "partants": 2,
        "runners": [
            {"num": "1", "name": "Test Horse 1", "cote": "10,5", "odds_place": "2.5"},
            {"num": "2", "name": "Test Horse 2", "cote": "5.0", "odds_place": "1.5"},
        ],
    }
    payload = online_fetch_zeturf._build_snapshot_payload(raw_snapshot, "R1", "C1", phase="H-30")
    assert payload["meeting"] == "Test Meeting"
    assert payload["date"] == "2025-01-01"
    assert payload["discipline"] == "Test Discipline"
    assert payload["partants_count"] == 2
    assert len(payload["runners"]) == 2
    assert payload["runners"][0]["name"] == "Test Horse 1"


def test_fetch_race_snapshot_cli(mocker):
    mock_run = mocker.patch("subprocess.run")
    mocker.patch("pathlib.Path.is_file", return_value=True)
    mocker.patch(
        "pathlib.Path.read_text",
        return_value=json.dumps({"test": "data"}),
    )
    mocker.patch("pathlib.Path.rglob", return_value=[Path("snapshot.json")])

    result = online_fetch_zeturf.fetch_race_snapshot_cli(
        course_url="https://www.zeturf.fr/fr/course/2025-11-21/R4C1-saint-galmier",
        phase="H5",
        out_dir="/tmp",
    )

    assert result == {"test": "data"}
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert "analyse_courses_du_jour_enrichie" in args[0]
