from unittest.mock import MagicMock
from pathlib import Path

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
    mock_response.text = html_string  # Add text attribute for consistency
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


@pytest.mark.asyncio
async def test_fetch_boturfers_programme_success(mocker):
    """
    Tests that `fetch_boturfers_programme` correctly parses the programme
    from a local HTML fixture.
    """
    # 1. Load HTML fixture
    html_content = (Path(__file__).parent.parent / "boturfers_programme.html").read_bytes()

    # 2. Mock the response and client, similar to other tests in this file
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = html_content
    mock_response.text = html_content.decode('utf-8')
    mock_response.raise_for_status.return_value = None

    mock_async_client = MagicMock()
    mock_async_client.__aenter__.return_value.get.return_value = mock_response
    mocker.patch("httpx.AsyncClient", return_value=mock_async_client)

    # 3. Call the function
    result = await boturfers.fetch_boturfers_programme("http://dummy.url/programme-pmu-du-jour")

    # 4. Assertions
    assert "races" in result
    assert len(result["races"]) == 24  # R1 has 8, R2 has 8, R4 has 8

    # Check details of the first race to ensure parsing is correct
    first_race = result["races"][0]
    assert first_race["rc"] == "R1 C1"
    assert first_race["reunion"] == "R1"
    assert first_race["name"] == "Prix De La Vesubie"
    assert first_race["runners_count"] == 10
    assert first_race["start_time"] == "11:30"

    # Check details of the last race
    last_race = result["races"][-1]
    assert last_race["rc"] == "R4 C8"
    assert last_race["reunion"] == "R4"
    assert last_race["name"] == "Prix De L'Elevage Du Centre"
