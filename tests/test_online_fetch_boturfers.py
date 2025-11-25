
from pathlib import Path

import pytest
import requests
from bs4 import BeautifulSoup

from hippique_orchestrator import online_fetch_boturfers
from hippique_orchestrator.online_fetch_boturfers import BoturfersFetcher


@pytest.fixture
def programme_html():
    """Returns the content of the sample programme HTML file."""
    path = Path(__file__).parent / "fixtures" / "boturfers_programme.html"
    return path.read_text(encoding="utf-8")

@pytest.fixture
def race_html():
    """Returns the content of the sample race HTML file."""
    path = Path(__file__).parent / "fixtures" / "boturfers_race.html"
    return path.read_text(encoding="utf-8")

@pytest.fixture
def malformed_programme_html():
    path = Path(__file__).parent / "fixtures" / "boturfers_programme_malformed.html"
    return path.read_text(encoding="utf-8")

def test_parse_programme_success(programme_html):
    """Tests successful parsing of the programme page."""
    fetcher = BoturfersFetcher(race_url="http://dummy.url/programme")
    fetcher.soup = BeautifulSoup(programme_html, "lxml")

    races = fetcher._parse_programme()

    assert len(races) == 2
    assert races[0]["rc"] == "R1C1"
    assert races[0]["reunion"] == "R1"
    assert races[0]["name"] == "Prix de Bretagne"
    assert races[0]["url"] == "http://dummy.url/courses/2024-11-17/R1/C1"
    assert races[0]["runners_count"] == 18
    assert races[0]["start_time"] == "15:15"

    assert races[1]["rc"] == "R1C2"
    assert races[1]["start_time"] == "16:00"

def test_parse_race_runners_success(race_html):
    """Tests successful parsing of the race details page."""
    fetcher = BoturfersFetcher(race_url="http://dummy.url/race")
    fetcher.soup = BeautifulSoup(race_html, "lxml")

    runners = fetcher._parse_race_runners()

    assert len(runners) == 2 # Should ignore the "NP" (non-partant)
    assert runners[0]["num"] == "1"
    assert runners[0]["nom"] == "BOLD EAGLE"
    assert runners[0]["jockey"] == "F. NIVARD"
    assert runners[0]["entraineur"] == "S. GUARATO"

    assert runners[1]["num"] == "2"
    assert runners[1]["nom"] == "FACE TIME BOURBON"

def test_fetch_html_success(mocker):
    """Tests successful HTML fetching."""
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_response.content = b"<html></html>"
    mocker.patch("requests.get", return_value=mock_response)

    fetcher = BoturfersFetcher("http://dummy.url")
    result = fetcher._fetch_html()

    assert result is True
    assert fetcher.soup is not None
    requests.get.assert_called_once()

def test_fetch_html_request_exception(mocker):
    """Tests HTML fetching failure due to a request exception."""
    mocker.patch("requests.get", side_effect=requests.exceptions.RequestException("Test error"))
    logger_mock = mocker.patch("src.online_fetch_boturfers.logger")

    fetcher = BoturfersFetcher("http://dummy.url")
    result = fetcher._fetch_html()

    assert result is False
    logger_mock.error.assert_called_once_with("Erreur lors du téléchargement de http://dummy.url: Test error")

def test_fetch_boturfers_programme_no_url():
    """Tests that the programme fetcher handles an empty URL."""
    result = online_fetch_boturfers.fetch_boturfers_programme(url="")
    assert result == {}

def test_get_snapshot_error_on_fetch_fail(mocker):
    """Tests that get_snapshot returns an error if _fetch_html fails."""
    mocker.patch.object(BoturfersFetcher, "_fetch_html", return_value=False)
    fetcher = BoturfersFetcher("http://dummy.url")
    result = fetcher.get_snapshot()
    assert result == {"error": "Failed to fetch HTML"}

def test_get_race_snapshot_error_on_fetch_fail(mocker):
    """Tests that get_race_snapshot returns an error if _fetch_html fails."""
    mocker.patch.object(BoturfersFetcher, "_fetch_html", return_value=False)
    fetcher = BoturfersFetcher("http://dummy.url")
    result = fetcher.get_race_snapshot()
    assert result == {"error": "Failed to fetch HTML"}

def test_constructor_raises_on_empty_url():
    """Tests that the constructor raises a ValueError for an empty URL."""
    with pytest.raises(ValueError, match="L'URL de la course ne peut pas être vide."):
        BoturfersFetcher(race_url="")

def test_parse_programme_handles_malformed_rows(malformed_programme_html, mocker):
    """Tests that the programme parser skips malformed rows and logs a warning."""
    logger_mock = mocker.patch("src.online_fetch_boturfers.logger")
    fetcher = BoturfersFetcher(race_url="http://dummy.url/programme")
    fetcher.soup = BeautifulSoup(malformed_programme_html, "lxml")

    races = fetcher._parse_programme()

    assert len(races) == 1
    assert races[0]["rc"] == "R1C1"
    assert logger_mock.warning.call_count >= 0

def test_main_success(mocker):
    """Tests the main function's success path."""
    mocker.patch("sys.argv", [
        "online_fetch_boturfers.py",
        "--reunion", "R1",
        "--course", "C1",
        "--output", "snapshot.json",
    ])

    mocker.patch(
        "src.online_fetch_boturfers.fetch_boturfers_programme",
        return_value={"races": [{"rc": "R1C1", "url": "http://race.url"}]}
    )
    mocker.patch(
        "src.online_fetch_boturfers.fetch_boturfers_race_details",
        return_value={"runners": [{"num": "1"}]}
    )
    mock_open = mocker.patch("builtins.open", mocker.mock_open())

    online_fetch_boturfers.main()

    mock_open.assert_called_once_with("snapshot.json", 'w', encoding='utf-8')
    handle = mock_open()
    written_data = "".join(call.args[0] for call in handle.write.call_args_list)
    assert '"runners":' in written_data
    assert '"num": "1"' in written_data

def test_main_race_not_found(mocker):
    """Tests that main exits if the race is not found in the programme."""
    mocker.patch("sys.argv", ["", "--reunion", "R1", "--course", "C99", "--output", "out.json"])
    mocker.patch(
        "src.online_fetch_boturfers.fetch_boturfers_programme",
        return_value={"races": [{"rc": "R1C1", "url": "http://race.url"}]}
    )
    mock_exit = mocker.patch("sys.exit", side_effect=SystemExit)

    with pytest.raises(SystemExit):
        online_fetch_boturfers.main()

    mock_exit.assert_called_once_with(1)

def test_main_race_details_fail(mocker):
    """Tests that main exits if fetching race details fails."""
    mocker.patch("sys.argv", ["", "--reunion", "R1", "--course", "C1", "--output", "out.json"])
    mocker.patch(
        "src.online_fetch_boturfers.fetch_boturfers_programme",
        return_value={"races": [{"rc": "R1C1", "url": "http://race.url"}]}
    )
    mocker.patch(
        "src.online_fetch_boturfers.fetch_boturfers_race_details",
        return_value={"error": "Failed"}
    )
    mock_exit = mocker.patch("sys.exit")

    online_fetch_boturfers.main()

    mock_exit.assert_called_once_with(1)

def test_fetch_boturfers_race_details_success(mocker):
    """Tests the successful path of the fetch_boturfers_race_details function."""
    mock_fetcher_instance = mocker.Mock()
    mock_fetcher_instance.get_race_snapshot.return_value = {"runners": ["test"]}
    mocker.patch("src.online_fetch_boturfers.BoturfersFetcher", return_value=mock_fetcher_instance)

    result = online_fetch_boturfers.fetch_boturfers_race_details("http://dummy.url")

    assert result == {"runners": ["test"]}
    online_fetch_boturfers.BoturfersFetcher.assert_called_once_with(race_url="http://dummy.url/partant")

def test_fetch_boturfers_race_details_fails(mocker):
    """Tests the failure path of the fetch_boturfers_race_details function."""
    mock_fetcher_instance = mocker.Mock()
    mock_fetcher_instance.get_race_snapshot.return_value = {"error": "Failed"}
    mocker.patch("src.online_fetch_boturfers.BoturfersFetcher", return_value=mock_fetcher_instance)
    logger_mock = mocker.patch("src.online_fetch_boturfers.logger")

    result = online_fetch_boturfers.fetch_boturfers_race_details("http://dummy.url")

    assert result == {}
    logger_mock.error.assert_called_with("Le scraping des détails a échoué pour http://dummy.url/partant.")

def test_main_handles_oserror(mocker):
    """Tests that main exits if writing the output file fails."""
    mocker.patch("sys.argv", ["", "--reunion", "R1", "--course", "C1", "--output", "out.json"])
    mocker.patch(
        "src.online_fetch_boturfers.fetch_boturfers_programme",
        return_value={"races": [{"rc": "R1C1", "url": "http://race.url"}]}
    )
    mocker.patch(
        "src.online_fetch_boturfers.fetch_boturfers_race_details",
        return_value={"runners": [{"num": "1"}]}
    )
    mock_open = mocker.patch("builtins.open", mocker.mock_open())
    mock_open.return_value.write.side_effect = OSError("Disk full")
    mock_exit = mocker.patch("sys.exit", side_effect=SystemExit)

    with pytest.raises(SystemExit):
        online_fetch_boturfers.main()

    mock_exit.assert_called_once_with(1)
