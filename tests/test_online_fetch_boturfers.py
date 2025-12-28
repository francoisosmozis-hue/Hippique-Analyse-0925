from unittest.mock import MagicMock

import httpx
import pytest

from hippique_orchestrator.scrapers import boturfers


@pytest.mark.asyncio
async def test_fetch_boturfers_race_details_success(mocker):
    """
    Tests the successful path of the fetch_boturfers_race_details function
    by mocking the async client and providing valid HTML.
    """
    html_string = """
        <html><body>
            <div class="info-race">2100m - Attelé</div>
            <table class="data"><tbody>
                <tr>
                    <th class="num">7</th>
                    <td class="tl">
                        <a class="link">Test Horse</a>
                        <div class="size-s"><a class="link">J. Jockey</a></div>
                        <a class="link lg">E. Trainer</a>
                    </td>
                    <td class="cote-gagnant"><span class="c">3,5</span></td>
                    <td class="cote-place"><span class="c">1,5</span></td>
                    <td class="musique">1p2p3p</td>
                    <td class="gains">12345</td>
                </tr>
            </tbody></table>
        </body></html>
    """
    # Use a MagicMock for the response to handle raise_for_status
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = html_string.encode('utf-8')
    mock_response.raise_for_status.return_value = None

    # Mock the async client's get method
    mock_async_client = MagicMock()
    mock_async_client.__aenter__.return_value.get.return_value = mock_response
    mocker.patch("httpx.AsyncClient", return_value=mock_async_client)

    result = await boturfers.fetch_boturfers_race_details("http://dummy.url")

    assert "runners" in result
    assert len(result["runners"]) == 1
    runner = result["runners"][0]
    assert runner["nom"] == "Test Horse"
    assert runner["odds_place"] == 1.5


@pytest.mark.asyncio
async def test_fetch_boturfers_race_details_fails(mocker):
    """
    Tests the failure path of the fetch_boturfers_race_details function.
    """
    # Mock the async client to raise an exception
    mock_async_client = MagicMock()
    mock_async_client.__aenter__.return_value.get.side_effect = httpx.RequestError(
        "Mocked connection error"
    )
    mocker.patch("httpx.AsyncClient", return_value=mock_async_client)

    logger_mock = mocker.patch("hippique_orchestrator.scrapers.boturfers.logger")

    result = await boturfers.fetch_boturfers_race_details("http://dummy.url")

    assert result == {}
    logger_mock.error.assert_any_call(
        "Le scraping des détails a échoué.",
        extra={'correlation_id': None, 'trace_id': None, 'url': 'http://dummy.url'},
    )
