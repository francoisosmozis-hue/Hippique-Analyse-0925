def test_fetch_boturfers_race_details_success(mocker):
    """Tests the successful path of the fetch_boturfers_race_details function."""
    mock_fetcher_instance = mocker.Mock()
    mock_fetcher_instance.get_race_snapshot.return_value = {"runners": ["test"]}
    mocker.patch("hippique_orchestrator.scrapers.boturfers.BoturfersFetcher", return_value=mock_fetcher_instance)

    result = online_fetch_boturfers.fetch_boturfers_race_details("http://dummy.url")

    assert result == {"runners": ["test"]}
    online_fetch_boturfers.BoturfersFetcher.assert_called_once_with(race_url="http://dummy.url/partant", correlation_id=None)

def test_fetch_boturfers_race_details_fails(mocker):
    """Tests the failure path of the fetch_boturfers_race_details function."""
    mock_fetcher_instance = mocker.Mock()
    mock_fetcher_instance.get_race_snapshot.return_value = {"error": "Failed"}
    mocker.patch("hippique_orchestrator.scrapers.boturfers.BoturfersFetcher", return_value=mock_fetcher_instance)
    logger_mock = mocker.patch("hippique_orchestrator.scrapers.boturfers.logger")

    result = online_fetch_boturfers.fetch_boturfers_race_details("http://dummy.url")

    assert result == {}
    logger_mock.error.assert_called_once()
    assert logger_mock.error.call_args[0][0] == "Le scraping des détails a échoué."