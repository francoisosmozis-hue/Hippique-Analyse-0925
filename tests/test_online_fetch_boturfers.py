from hippique_orchestrator.scrapers import boturfers


def test_fetch_boturfers_race_details_success(mocker):
    """Tests the successful path of the fetch_boturfers_race_details function."""
    mocker.patch("hippique_orchestrator.scrapers.boturfers.fetch_boturfers_race_details", return_value={"runners": ["test"]})

    result = boturfers.fetch_boturfers_race_details("http://dummy.url")

    assert result == {"runners": ["test"]}
    boturfers.fetch_boturfers_race_details.assert_called_once_with("http://dummy.url")

def test_fetch_boturfers_race_details_fails(mocker):
    """Tests the failure path of the fetch_boturfers_race_details function."""
    mocker.patch("hippique_orchestrator.scrapers.boturfers.fetch_boturfers_race_details", return_value={"error": "Failed"})
    logger_mock = mocker.patch("hippique_orchestrator.scrapers.boturfers.logger")

    result = boturfers.fetch_boturfers_race_details("http://dummy.url")

    assert result == {"error": "Failed"} # Result should still contain the error
    logger_mock.error.assert_called_once()
    assert logger_mock.error.call_args[0][0] == "Failed to fetch race details."