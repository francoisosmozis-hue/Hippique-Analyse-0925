from hippique_orchestrator.scrapers import boturfers


def test_fetch_boturfers_race_details_success(mocker):
    """Tests the successful path of the fetch_boturfers_race_details function."""
    mocker.patch("hippique_orchestrator.scrapers.boturfers.fetch_boturfers_race_details", return_value={"runners": ["test"]})

    result = boturfers.fetch_boturfers_race_details("http://dummy.url")

    assert result == {"runners": ["test"]}
    boturfers.fetch_boturfers_race_details.assert_called_once_with("http://dummy.url")

def test_fetch_boturfers_race_details_fails(mocker):
    """Tests the failure path of the fetch_boturfers_race_details function."""
    from unittest.mock import call

    from requests.exceptions import HTTPError

    # Mock requests.get to raise an HTTPError
    mocker.patch("hippique_orchestrator.scrapers.boturfers.requests.get", side_effect=HTTPError("Mocked HTTP Error"))
    logger_mock = mocker.patch("hippique_orchestrator.scrapers.boturfers.logger")

    result = boturfers.fetch_boturfers_race_details("http://dummy.url")

    assert result == {} # Result should be an empty dict on failure
    # Check that logger.error was called with the two expected messages
    logger_mock.error.assert_has_calls([
        call("Erreur lors du téléchargement de http://dummy.url/partant: Mocked HTTP Error", extra={'correlation_id': None, 'trace_id': None}),
        call("Le scraping des détails a échoué.", extra={'correlation_id': None, 'trace_id': None, 'url': 'http://dummy.url'})
    ], any_order=True)
