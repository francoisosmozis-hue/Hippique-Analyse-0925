from unittest.mock import MagicMock, patch
from pathlib import Path
import httpx
import pytest
from datetime import datetime

from hippique_orchestrator.scrapers import boturfers


# --- Fixtures ---
@pytest.fixture
def boturfers_programme_html():
    """Provides the HTML content of a nominal Boturfers programme page."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "boturfers_programme.html"
    assert fixture_path.exists(), f"Fixture file not found: {fixture_path}"
    return fixture_path.read_text(encoding='utf-8')

@pytest.fixture
def boturfers_programme_empty_html():
    """Provides HTML for an empty Boturfers programme page."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "boturfers_programme_empty.html"
    assert fixture_path.exists(), f"Fixture file not found: {fixture_path}"
    return fixture_path.read_text(encoding='utf-8')

@pytest.fixture
def boturfers_race_details_html():
    """Provides the HTML content of a nominal Boturfers race details page."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "boturfers_race_details.html"
    assert fixture_path.exists(), f"Fixture file not found: {fixture_path}"
    return fixture_path.read_text(encoding='utf-8')

@pytest.fixture
def boturfers_race_details_malformed_html():
    """Provides malformed HTML for a Boturfers race details page."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "boturfers_race_details_malformed.html"
    assert fixture_path.exists(), f"Fixture file not found: {fixture_path}"
    return fixture_path.read_text(encoding='utf-8')

@pytest.fixture
def mock_async_client(mocker):
    """Mocks httpx.AsyncClient for network requests."""
    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value = mock_client # Ensure async context manager works
    mocker.patch("httpx.AsyncClient", return_value=mock_client)
    return mock_client

@pytest.fixture
def mock_logger(mocker):
    """Mocks the logger for capturing log messages."""
    return mocker.patch("hippique_orchestrator.scrapers.boturfers.logger")

@pytest.fixture
def mock_utcnow(mocker):
    """Mocks datetime.utcnow for deterministic timestamps."""
    mock_dt = mocker.patch("hippique_orchestrator.scrapers.boturfers.datetime")
    mock_dt.utcnow.return_value = datetime(2025, 1, 1, 12, 0, 0)
    return mock_dt


# --- Tests for BoturfersFetcher class ---

def test_boturfers_fetcher_init_success():
    fetcher = boturfers.BoturfersFetcher("http://valid.url")
    assert fetcher.race_url == "http://valid.url"
    assert fetcher.soup is None

def test_boturfers_fetcher_init_value_error():
    with pytest.raises(ValueError, match="L'URL de la course ne peut pas être vide."):
        boturfers.BoturfersFetcher("")

@pytest.mark.asyncio
async def test_fetcher_fetch_html_success(mock_async_client):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.content = b"<html><body>Test</body></html>"
    mock_response.raise_for_status.return_value = None
    mock_async_client.get.return_value = mock_response

    fetcher = boturfers.BoturfersFetcher("http://valid.url")
    result = await fetcher._fetch_html()

    assert result is True
    assert fetcher.soup is not None
    assert "Test" in str(fetcher.soup)

@pytest.mark.asyncio
async def test_fetcher_fetch_html_httpx_request_error(mock_async_client, mock_logger):
    mock_async_client.get.side_effect = httpx.RequestError("Mock error", request=MagicMock())
    fetcher = boturfers.BoturfersFetcher("http://valid.url")
    result = await fetcher._fetch_html()

    assert result is False
    assert "Erreur HTTP lors du téléchargement" in mock_logger.error.call_args[0][0]

@pytest.mark.asyncio
async def test_fetcher_fetch_html_httpx_status_error(mock_async_client, mock_logger):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 404
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError("Not Found", request=MagicMock(), response=mock_response)
    mock_async_client.get.return_value = mock_response

    fetcher = boturfers.BoturfersFetcher("http://valid.url")
    result = await fetcher._fetch_html()

    assert result is False
    assert "Erreur HTTP lors du téléchargement" in mock_logger.error.call_args[0][0]

@pytest.mark.asyncio
async def test_fetcher_fetch_html_generic_exception(mock_async_client, mock_logger):
    mock_async_client.get.side_effect = Exception("Generic error")
    fetcher = boturfers.BoturfersFetcher("http://valid.url")
    result = await fetcher._fetch_html()

    assert result is False
    assert "Erreur inattendue lors du fetch HTML" in mock_logger.exception.call_args[0][0]


def test_fetcher_parse_race_row_success():
    html_row = """
    <tr>
        <th class="num"><span class="rxcx">R1 C1</span></th>
        <td class="crs"><a class="link" href="/course/123">Race Name</a></td>
        <td class="hour">14h30</td>
        <td class="nb">10</td>
    </tr>
    """
    soup_row = BeautifulSoup(html_row, 'lxml').find('tr')
    fetcher = boturfers.BoturfersFetcher("http://dummy.url")
    result = fetcher._parse_race_row(soup_row, "http://dummy.url")

    assert result is not None
    assert result["rc"] == "R1 C1"
    assert result["name"] == "Race Name"
    assert result["url"] == "http://dummy.url/course/123"
    assert result["start_time"] == "14:30"
    assert result["runners_count"] == 10

def test_fetcher_parse_race_row_missing_elements(mock_logger):
    html_row = """
    <tr>
        <th class="num"></th> <!-- Missing span.rxcx -->
        <td class="crs"><a class="link">Race Name</a></td>
        <td class="hour">14h30</td>
        <td class="nb">10</td>
    </tr>
    """
    soup_row = BeautifulSoup(html_row, 'lxml').find('tr')
    fetcher = boturfers.BoturfersFetcher("http://dummy.url")
    result = fetcher._parse_race_row(soup_row, "http://dummy.url")
    assert result is None
    assert "Impossible d'analyser une ligne de course" in mock_logger.warning.call_args[0][0]

@pytest.mark.parametrize("time_text, expected_time", [
    ("14h30", "14:30"),
    ("9h05", "09:05"),
    ("11:15", "11:15"),
    ("invalid", None),
    ("", None),
    (None, None),
])
def test_fetcher_parse_race_row_time_formats(time_text, expected_time):
    html_row = f"""
    <tr>
        <th class="num"><span class="rxcx">R1 C1</span></th>
        <td class="crs"><a class="link" href="/course/123">Race Name</a></td>
        <td class="hour">{time_text}</td>
        <td class="nb">10</td>
    </tr>
    """
    soup_row = BeautifulSoup(html_row, 'lxml').find('tr')
    fetcher = boturfers.BoturfersFetcher("http://dummy.url")
    result = fetcher._parse_race_row(soup_row, "http://dummy.url")
    assert result["start_time"] == expected_time

def test_fetcher_parse_race_row_runners_count_non_digit():
    html_row = """
    <tr>
        <th class="num"><span class="rxcx">R1 C1</span></th>
        <td class="crs"><a class="link" href="/course/123">Race Name</a></td>
        <td class="hour">14h30</td>
        <td class="nb">Dix</td>
    </tr>
    """
    soup_row = BeautifulSoup(html_row, 'lxml').find('tr')
    fetcher = boturfers.BoturfersFetcher("http://dummy.url")
    result = fetcher._parse_race_row(soup_row, "http://dummy.url")
    assert result["runners_count"] is None


def test_fetcher_parse_programme_success(boturfers_programme_html):
    fetcher = boturfers.BoturfersFetcher("http://dummy.url")
    fetcher.soup = BeautifulSoup(boturfers_programme_html, 'lxml')
    races = fetcher._parse_programme()
    
    assert len(races) == 24 # From fixture
    assert races[0]["reunion"] == "R1"
    assert races[0]["rc"] == "R1 C1"
    assert races[0]["name"] == "PRIX DE LA VESUBIE"

def test_fetcher_parse_programme_no_reunion_tabs(boturfers_programme_empty_html, mock_logger):
    fetcher = boturfers.BoturfersFetcher("http://dummy.url")
    fetcher.soup = BeautifulSoup(boturfers_programme_empty_html, 'lxml')
    races = fetcher._parse_programme()
    assert races == []
    assert "Aucun onglet de réunion" in mock_logger.warning.call_args[0][0]

def test_fetcher_parse_programme_no_race_table_in_reunion(mock_logger):
    html_content = """
    <div class="tab-content">
        <div class="tab-pane active" id="r1">
            <h3 class="reu-title">R1 - Reunion Name</h3>
            <!-- Missing table.table.data.prgm -->
        </div>
    </div>
    """
    fetcher = boturfers.BoturfersFetcher("http://dummy.url")
    fetcher.soup = BeautifulSoup(html_content, 'lxml')
    races = fetcher._parse_programme()
    assert races == []
    assert "Tableau des courses" in mock_logger.warning.call_args[0][0]


def test_fetcher_parse_distance_success(boturfers_race_details_html):
    fetcher = boturfers.BoturfersFetcher("http://dummy.url")
    fetcher.soup = BeautifulSoup(boturfers_race_details_html, 'lxml')
    distance = fetcher._parse_distance()
    assert distance == 2100

def test_fetcher_parse_distance_not_found():
    html_content = "<html><body><div class='info-race'>No distance here</div></body></html>"
    fetcher = boturfers.BoturfersFetcher("http://dummy.url")
    fetcher.soup = BeautifulSoup(html_content, 'lxml')
    distance = fetcher._parse_distance()
    assert distance is None


def test_fetcher_parse_race_metadata_success(boturfers_race_details_html):
    fetcher = boturfers.BoturfersFetcher("http://dummy.url")
    fetcher.soup = BeautifulSoup(boturfers_race_details_html, 'lxml')
    metadata = fetcher._parse_race_metadata()
    assert metadata["distance"] == 2100
    assert metadata["type_course"] == "Attelé"
    assert metadata["corde"] == "Gauche"
    assert "Conditions" in metadata

def test_fetcher_parse_race_metadata_no_info_block(mock_logger):
    html_content = "<html><body></body></html>"
    fetcher = boturfers.BoturfersFetcher("http://dummy.url")
    fetcher.soup = BeautifulSoup(html_content, 'lxml')
    metadata = fetcher._parse_race_metadata()
    assert metadata == {}
    assert "Aucune métadonnée de course" in mock_logger.warning.call_args[0][0]


def test_fetcher_parse_race_runners_from_details_page_success(boturfers_race_details_html):
    fetcher = boturfers.BoturfersFetcher("http://dummy.url")
    fetcher.soup = BeautifulSoup(boturfers_race_details_html, 'lxml')
    runners = fetcher._parse_race_runners_from_details_page()

    assert len(runners) == 2
    assert runners[0]["nom"] == "Cheval A"
    assert runners[0]["jockey"] == "J. Dupont"
    assert runners[0]["entraineur"] == "E. Trainer"
    assert runners[0]["odds_win"] == 2.5
    assert runners[0]["odds_place"] == 1.3
    assert runners[0]["musique"] == "1p2p3p"
    assert runners[0]["gains"] == "123456"

def test_fetcher_parse_race_runners_from_details_page_no_runners_table(mock_logger):
    html_content = "<html><body></body></html>"
    fetcher = boturfers.BoturfersFetcher("http://dummy.url")
    fetcher.soup = BeautifulSoup(html_content, 'lxml')
    runners = fetcher._parse_race_runners_from_details_page()
    assert runners == []
    assert "Could not find runners table" in mock_logger.warning.call_args[0][0]

def test_fetcher_parse_race_runners_from_details_page_malformed_row(boturfers_race_details_malformed_html, mock_logger):
    fetcher = boturfers.BoturfersFetcher("http://dummy.url")
    fetcher.soup = BeautifulSoup(boturfers_race_details_malformed_html, 'lxml')
    runners = fetcher._parse_race_runners_from_details_page()
    assert len(runners) == 2 # One runner is partially parsed, one is skipped
    assert runners[0]["nom"] == "Cheval A"
    assert runners[0]["jockey"] is None # Missing links
    assert runners[0]["entraineur"] is None
    assert runners[0]["odds_win"] is None # Missing odds cells
    assert runners[0]["odds_place"] is None
    assert runners[0]["musique"] is None
    assert runners[0]["gains"] is None
    assert runners[1]["nom"] == "Cheval B"
    assert runners[1]["jockey"] is None
    assert runners[1]["entraineur"] is None
    assert runners[1]["odds_win"] is None # Malformed float should be None
    assert runners[1]["odds_place"] == 2.0
    assert runners[1]["musique"] is None
    assert runners[1]["gains"] is None
    # Check that error was logged for runner row parsing
    mock_logger.warning.assert_any_call(
        "Failed to parse a runner row: %s. Row skipped.", # Need to check message and argument
        mocker.ANY,
        extra=mocker.ANY
    )
    # The malformed row causes 2 warnings, one for missing links, one for malformed float.
    # The count will be for the number of actual calls, not unique messages.
    assert mock_logger.warning.call_count >= 1 # At least one warning.


@pytest.mark.asyncio
async def test_fetcher_get_snapshot_success(mock_async_client, mock_utcnow, boturfers_programme_html):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.content = boturfers_programme_html.encode('utf-8')
    mock_response.raise_for_status.return_value = None
    mock_async_client.get.return_value = mock_response

    fetcher = boturfers.BoturfersFetcher("http://programme.url")
    snapshot = await fetcher.get_snapshot()

    assert snapshot["source"] == "boturfers"
    assert snapshot["type"] == "programme"
    assert "races" in snapshot
    assert len(snapshot["races"]) == 24
    assert snapshot["scraped_at"] == "2025-01-01T12:00:00"

@pytest.mark.asyncio
async def test_fetcher_get_snapshot_fetch_html_fails(mock_async_client):
    mock_async_client.get.side_effect = httpx.RequestError("Mock error", request=MagicMock())
    fetcher = boturfers.BoturfersFetcher("http://programme.url")
    snapshot = await fetcher.get_snapshot()
    assert snapshot == {"error": "Failed to fetch HTML"}

@pytest.mark.asyncio
async def test_fetcher_get_race_snapshot_success(mock_async_client, mock_utcnow, boturfers_race_details_html):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.content = boturfers_race_details_html.encode('utf-8')
    mock_response.raise_for_status.return_value = None
    mock_async_client.get.return_value = mock_response

    fetcher = boturfers.BoturfersFetcher("http://race.url")
    snapshot = await fetcher.get_race_snapshot()

    assert snapshot["source"] == "boturfers"
    assert snapshot["type"] == "race_details"
    assert "runners" in snapshot
    assert len(snapshot["runners"]) == 2
    assert snapshot["race_metadata"]["distance"] == 2100
    assert snapshot["scraped_at"] == "2025-01-01T12:00:00"

@pytest.mark.asyncio
async def test_fetcher_get_race_snapshot_fetch_html_fails(mock_async_client):
    mock_async_client.get.side_effect = httpx.RequestError("Mock error", request=MagicMock())
    fetcher = boturfers.BoturfersFetcher("http://race.url")
    snapshot = await fetcher.get_race_snapshot()
    assert snapshot == {"error": "Failed to fetch HTML"}


# --- Tests for public async functions ---

@pytest.mark.asyncio
async def test_fetch_boturfers_programme_success(mocker, mock_async_client, mock_utcnow, boturfers_programme_html, mock_logger):
    # The existing test with the same name will be overwritten or removed.
    # This version uses the new fixtures and mocks.
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.content = boturfers_programme_html.encode('utf-8')
    mock_response.text = boturfers_programme_html # BeautifulSoup expects string if not bytes
    mock_response.raise_for_status.return_value = None
    mock_async_client.get.return_value = mock_response

    result = await boturfers.fetch_boturfers_programme("http://dummy.url/programme-pmu-du-jour")

    assert "races" in result
    assert len(result["races"]) == 24
    mock_logger.info.assert_any_call("Scraping du programme Boturfers réussi. %s courses trouvées.", 24, extra=mocker.ANY)


@pytest.mark.asyncio
async def test_fetch_boturfers_programme_empty_url(mock_logger):
    result = await boturfers.fetch_boturfers_programme("")
    assert result == {}
    mock_logger.error.assert_any_call("Aucune URL fournie pour le scraping Boturfers.", extra=mocker.ANY)

@pytest.mark.asyncio
async def test_fetch_boturfers_programme_fetcher_error(mocker, mock_async_client, mock_logger):
    mock_async_client.get.side_effect = httpx.RequestError("Mock error", request=MagicMock())
    result = await boturfers.fetch_boturfers_programme("http://dummy.url")
    assert result == {}
    mock_logger.error.assert_any_call("Le scraping du programme a échoué ou n'a retourné aucune course.", extra=mocker.ANY)

@pytest.mark.asyncio
async def test_fetch_boturfers_programme_no_races_returned(mocker, mock_async_client, boturfers_programme_empty_html, mock_logger):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.content = boturfers_programme_empty_html.encode('utf-8')
    mock_response.raise_for_status.return_value = None
    mock_async_client.get.return_value = mock_response

    result = await boturfers.fetch_boturfers_programme("http://dummy.url")
    assert result == {}
    mock_logger.error.assert_any_call("Le scraping du programme a échoué ou n'a retourné aucune course.", extra=mocker.ANY)

@pytest.mark.asyncio
async def test_fetch_boturfers_programme_general_exception(mocker, mock_async_client, mock_logger):
    mocker.patch.object(boturfers.BoturfersFetcher, 'get_snapshot', side_effect=Exception("Unexpected"))
    result = await boturfers.fetch_boturfers_programme("http://dummy.url")
    assert result == {}
    mock_logger.exception.assert_any_call(mocker.ANY, mocker.ANY, exc_info=True, extra=mocker.ANY)


@pytest.mark.asyncio
async def test_fetch_boturfers_race_details_success(mocker, mock_async_client, mock_utcnow, boturfers_race_details_html, mock_logger):
    # The existing test with the same name will be overwritten or removed.
    # This version uses the new fixtures and mocks.
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.content = boturfers_race_details_html.encode('utf-8')
    mock_response.text = boturfers_race_details_html # BeautifulSoup expects string if not bytes
    mock_response.raise_for_status.return_value = None
    mock_async_client.get.return_value = mock_response

    result = await boturfers.fetch_boturfers_race_details("http://dummy.url/course/123")

    assert "runners" in result
    assert len(result["runners"]) == 2
    assert result["race_metadata"]["distance"] == 2100
    mock_logger.info.assert_any_call("Scraping des détails réussi. %s partants trouvés.", 2, extra=mocker.ANY)

@pytest.mark.asyncio
async def test_fetch_boturfers_race_details_empty_url(mock_logger):
    result = await boturfers.fetch_boturfers_race_details("")
    assert result == {}
    mock_logger.error.assert_any_call("Aucune URL fournie pour le scraping des détails de course.", extra=mocker.ANY)

@pytest.mark.asyncio
async def test_fetch_boturfers_race_details_url_partant_transformation(mocker, mock_async_client, mock_logger):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.content = b"<html><body></body></html>"
    mock_async_client.get.return_value = mock_response

    # URL ends with /course/123 -> should become /course/123/partant
    await boturfers.fetch_boturfers_race_details("http://www.boturfers.fr/course/123")
    mock_async_client.get.assert_called_once_with("http://www.boturfers.fr/course/123/partant", headers=boturfers.HTTP_HEADERS, timeout=20)
    
    mock_async_client.get.reset_mock()
    # URL ends with /course/123/partant -> should remain unchanged
    await boturfers.fetch_boturfers_race_details("http://www.boturfers.fr/course/123/partant")
    mock_async_client.get.assert_called_once_with("http://www.boturfers.fr/course/123/partant", headers=boturfers.HTTP_HEADERS, timeout=20)

    mock_async_client.get.reset_mock()
    # Non-boturfers URL -> should remain unchanged
    await boturfers.fetch_boturfers_race_details("http://www.other-site.com/race/456")
    mock_async_client.get.assert_called_once_with("http://www.other-site.com/race/456", headers=boturfers.HTTP_HEADERS, timeout=20)

@pytest.mark.asyncio
async def test_fetch_boturfers_race_details_fetcher_error(mocker, mock_async_client, mock_logger):
    mocker.patch.object(boturfers.BoturfersFetcher, 'get_race_snapshot', return_value={"error": "Failed fetch"})
    result = await boturfers.fetch_boturfers_race_details("http://dummy.url")
    assert result == {}
    mock_logger.error.assert_any_call("Le scraping des détails a échoué.", extra=mocker.ANY)

@pytest.mark.asyncio
async def test_fetch_boturfers_race_details_no_runners_returned(mocker, mock_async_client, mock_logger):
    mocker.patch.object(boturfers.BoturfersFetcher, 'get_race_snapshot', return_value={"runners": []})
    result = await boturfers.fetch_boturfers_race_details("http://dummy.url")
    assert result == {}
    mock_logger.error.assert_any_call("Le scraping des détails a échoué.", extra=mocker.ANY)

@pytest.mark.asyncio
async def test_fetch_boturfers_race_details_general_exception(mocker, mock_async_client, mock_logger):
    mocker.patch.object(boturfers.BoturfersFetcher, 'get_race_snapshot', side_effect=Exception("Unexpected"))
    result = await boturfers.fetch_boturfers_race_details("http://dummy.url")
    assert result == {}
    mock_logger.exception.assert_any_call(mocker.ANY, mocker.ANY, exc_info=True, extra=mocker.ANY)
