import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from bs4 import BeautifulSoup
import httpx
from datetime import datetime

from hippique_orchestrator.scrapers.boturfers import BoturfersFetcher, fetch_boturfers_programme, fetch_boturfers_race_details


# Fixture pour simuler httpx.AsyncClient et BeautifulSoup
@pytest.fixture
def mock_httpx_and_soup():
    with patch("httpx.AsyncClient", autospec=True) as mock_async_client:
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.content = "<html><body></body></html>"
        mock_async_client.return_value.__aenter__.return_value.get.return_value = mock_response
        with patch("hippique_orchestrator.scrapers.boturfers.BeautifulSoup", autospec=True) as mock_beautiful_soup:
            yield mock_async_client, mock_beautiful_soup


@pytest.mark.asyncio
async def test_boturfers_fetcher_init_value_error():
    """Test that BoturfersFetcher raises ValueError if race_url is empty."""
    with pytest.raises(ValueError, match="L'URL de la course ne peut pas être vide."):
        BoturfersFetcher(race_url="")


@pytest.mark.asyncio
async def test_fetcher_fetch_html_httpx_status_error(mock_httpx_and_soup, caplog):
    """Test _fetch_html handles httpx.HTTPStatusError correctly."""
    mock_async_client, _ = mock_httpx_and_soup
    mock_response = mock_async_client.return_value.__aenter__.return_value.get.return_value
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404 Not Found", request=httpx.Request("GET", "http://test.url"), response=httpx.Response(404)
    )

    fetcher = BoturfersFetcher(race_url="http://test.url")
    result = await fetcher._fetch_html()

    assert result is False
    assert "Erreur HTTP lors du téléchargement de http://test.url: 404" in caplog.text


@pytest.mark.asyncio
async def test_fetcher_fetch_html_generic_exception(mock_httpx_and_soup, caplog):
    """Test _fetch_html handles generic exceptions correctly."""
    mock_async_client, _ = mock_httpx_and_soup
    mock_async_client.return_value.__aenter__.return_value.get.side_effect = Exception("Network error")

    fetcher = BoturfersFetcher(race_url="http://test.url")
    result = await fetcher._fetch_html()

    assert result is False
    assert "Erreur inattendue lors du fetch HTML de http://test.url: Network error" in caplog.text


# Tests pour _parse_programme
@pytest.mark.asyncio
async def test_parse_programme_no_reunion_tabs(mock_httpx_and_soup, caplog):
    """Test _parse_programme when no reunion tabs are found."""
    _, mock_beautiful_soup = mock_httpx_and_soup
    mock_soup_instance = MagicMock()
    mock_soup_instance.select.return_value = []  # No reunion tabs
    mock_beautiful_soup.return_value = mock_soup_instance

    fetcher = BoturfersFetcher(race_url="http://programme.url")
    fetcher.soup = mock_soup_instance  # Manually set soup for parsing functions
    races = fetcher._parse_programme()

    assert races == []
    assert "Aucun onglet de réunion ('div.tab-pane[id^=r]') trouvé sur la page du programme." in caplog.text


@pytest.mark.asyncio
async def test_parse_programme_no_race_table_in_reunion(mock_httpx_and_soup, caplog):
    """Test _parse_programme when a reunion tab has no race table."""
    _, mock_beautiful_soup = mock_httpx_and_soup
    mock_soup_instance = MagicMock()
    mock_reunion_tab = MagicMock()
    mock_reunion_tab.select_one.side_effect = [
        MagicMock(text="R1 - Reunion Test"),  # For reunion_title_tag
        None,  # No race table, so select_one("table.table.data.prgm") returns None
    ]
    mock_reunion_tab.get.return_value = "R1" # For reunion_tab.get("id")
    mock_soup_instance.select.return_value = [mock_reunion_tab]
    mock_beautiful_soup.return_value = mock_soup_instance

    fetcher = BoturfersFetcher(race_url="http://programme.url")
    fetcher.soup = mock_soup_instance
    races = fetcher._parse_programme()

    assert races == []
    assert "Tableau des courses ('table.table.data.prgm') introuvable pour la réunion R1." in caplog.text


@pytest.mark.asyncio
async def test_parse_programme_reunion_id_from_id_attribute(mock_httpx_and_soup, caplog):
    """Test _parse_programme extracts reunion ID from id attribute if title is malformed."""
    _, mock_beautiful_soup = mock_httpx_and_soup
    mock_soup_instance = MagicMock()
    mock_reunion_tab = MagicMock()
    
    # Simulate a reunion_tab that has an ID but no title tag with text
    mock_reunion_tab.select_one.side_effect = [
        None, # No reunion_title_tag
        None,  # No race table, so select_one("table.table.data.prgm") returns None
    ]
    mock_reunion_tab.get.return_value = "r1_tab" # reunion_tab.get("id") returns "r1_tab"
    
    mock_soup_instance.select.return_value = [mock_reunion_tab] # Select returns this reunion_tab
    mock_beautiful_soup.return_value = mock_soup_instance

    fetcher = BoturfersFetcher(race_url="http://programme.url")
    fetcher.soup = mock_soup_instance
    races = fetcher._parse_programme()

    assert races == [] # Should still return empty because no races were parsed
    # Check that a warning for missing table in reunion is logged
    assert "Tableau des courses ('table.table.data.prgm') introuvable pour la réunion R1_TAB." in caplog.text


@pytest.mark.asyncio
async def test_parse_programme_empty_race_table(mock_httpx_and_soup, caplog):
    """Test _parse_programme when a race_table is found but has no 'tbody tr' rows."""
    _, mock_beautiful_soup = mock_httpx_and_soup
    mock_soup_instance = MagicMock()
    mock_reunion_tab = MagicMock()
    mock_race_table = MagicMock()

    mock_reunion_tab.select_one.side_effect = [
        MagicMock(text="R1 - Reunion Test"),  # For reunion_title_tag
        mock_race_table,  # race_table is found
    ]
    mock_reunion_tab.get.return_value = "R1"
    mock_race_table.select.return_value = [] # No 'tbody tr' rows

    mock_soup_instance.select.return_value = [mock_reunion_tab]
    mock_beautiful_soup.return_value = mock_soup_instance

    fetcher = BoturfersFetcher(race_url="http://programme.url")
    fetcher.soup = mock_soup_instance
    races = fetcher._parse_programme()

    assert races == []
    # No specific warning is logged for this case, it just results in an empty list.


# Tests pour _parse_distance
@pytest.mark.asyncio
async def test_parse_distance_not_found(mock_httpx_and_soup):
    """Test _parse_distance returns None if distance cannot be found."""
    _, mock_beautiful_soup = mock_httpx_and_soup
    mock_soup_instance = MagicMock()
    mock_soup_instance.select_one.return_value = None  # No info-race or distance span
    mock_beautiful_soup.return_value = mock_soup_instance

    fetcher = BoturfersFetcher(race_url="http://race.url")
    fetcher.soup = mock_soup_instance
    distance = fetcher._parse_distance()

    assert distance is None


@pytest.mark.asyncio
async def test_parse_distance_from_span_tag(mock_httpx_and_soup):
    """Test _parse_distance extracts distance from span.distance if div.info-race is missing."""
    _, mock_beautiful_soup = mock_httpx_and_soup
    mock_soup_instance = MagicMock()
    
    mock_soup_instance.select_one.side_effect = [
        None, # for _parse_distance: select_one("div.info-race") -> not found
        MagicMock(text="Distance: 2875m"), # for _parse_distance: select_one("span.distance") -> found
    ]
    mock_beautiful_soup.return_value = mock_soup_instance

    fetcher = BoturfersFetcher(race_url="http://race.url")
    fetcher.soup = mock_soup_instance
    distance = fetcher._parse_distance()

    assert distance == 2875


# Tests pour _parse_race_metadata
@pytest.mark.asyncio
async def test_parse_race_metadata_no_info_block(mock_httpx_and_soup, caplog):
    """Test _parse_race_metadata when no info-race block is found."""
    _, mock_beautiful_soup = mock_httpx_and_soup
    mock_soup_instance = MagicMock()
    
    # Mock select_one to return None for all relevant calls in _parse_distance and _parse_race_metadata
    mock_soup_instance.select_one.side_effect = [
        None, # for _parse_distance: select_one("div.info-race")
        None, # for _parse_distance: select_one("span.distance")
        None, # for _parse_race_metadata: select_one("div.info-race")
    ] 
    mock_beautiful_soup.return_value = mock_soup_instance

    fetcher = BoturfersFetcher(race_url="http://race.url")
    fetcher.soup = mock_soup_instance
    metadata = fetcher._parse_race_metadata()

    assert metadata == {}
    assert "Aucune métadonnée de course n'a pu être extraite" in caplog.text


@pytest.mark.asyncio
async def test_parse_race_metadata_no_conditions_tag_and_no_conditions_text(mock_httpx_and_soup):
    """Test _parse_race_metadata when conditions_tag is None and no 'conditions' text is found."""
    _, mock_beautiful_soup = mock_httpx_and_soup
    mock_soup_instance = MagicMock()
    
    mock_info_race_distance = MagicMock()
    mock_info_race_distance.text = "1200m"
    mock_info_race_distance.get_text.return_value = "1200m" # Return value for get_text() inside _parse_distance

    mock_info_race_metadata = MagicMock()
    mock_info_race_metadata.get_text.return_value = "some text without explicit conditions tag or keyword"

    mock_soup_instance.select_one.side_effect = [
        mock_info_race_distance, # 1. for _parse_distance: select_one("div.info-race") -> found distance
        None,                    # 2. for _parse_distance: select_one("span.distance")
        mock_info_race_metadata, # 3. for _parse_race_metadata: select_one("div.info-race") (found)
        None,                    # 4. for _parse_race_metadata: select_one("div.conditions-course") (not found)
    ]
    mock_beautiful_soup.return_value = mock_soup_instance

    fetcher = BoturfersFetcher(race_url="http://race.url")
    fetcher.soup = mock_soup_instance
    metadata = fetcher._parse_race_metadata()

    assert "conditions" not in metadata
    assert metadata["distance"] == 1200


# Tests pour _parse_race_runners_from_details_page
@pytest.mark.asyncio
async def test_parse_race_runners_no_runners_table(mock_httpx_and_soup, caplog):
    """Test _parse_race_runners_from_details_page when no runners table is found."""
    _, mock_beautiful_soup = mock_httpx_and_soup
    mock_soup_instance = MagicMock()
    mock_soup_instance.select_one.return_value = None  # No runners table
    mock_beautiful_soup.return_value = mock_soup_instance

    fetcher = BoturfersFetcher(race_url="http://race.url")
    fetcher.soup = mock_soup_instance
    runners = fetcher._parse_race_runners_from_details_page()

    assert runners == []
    assert "Could not find runners table ('table.data') on the page." in caplog.text


@pytest.mark.asyncio
async def test_parse_race_runners_malformed_row(mock_httpx_and_soup, caplog):
    """Test _parse_race_runners_from_details_page handles malformed runner rows gracefully."""
    _, mock_beautiful_soup = mock_httpx_and_soup
    mock_soup_instance = MagicMock()
    mock_runners_table = MagicMock()
    
    # A valid row
    mock_row_valid = MagicMock()
    mock_num_tag = MagicMock(text="1")
    mock_nom_tag = MagicMock(text="Nom Valide")
    mock_nom_tag.get.return_value = "http://example.com/runner1" # for 'href'
    mock_jockey_link = MagicMock(text="Jockey Valide")
    mock_trainer_link = MagicMock(text="Entraineur Valide")
    mock_odds_win_tag = MagicMock(text="1.5")
    mock_odds_place_tag = MagicMock(text="1.2")
    mock_musique_tag = MagicMock(text="Musique")
    mock_gains_tag = MagicMock(text="Gains")
    
    mock_row_valid.select_one.side_effect = [
        mock_num_tag, mock_nom_tag, mock_odds_win_tag, mock_odds_place_tag, mock_musique_tag, mock_gains_tag
    ]
    mock_row_valid.select.return_value = [mock_nom_tag, mock_jockey_link, mock_trainer_link] # links for jockey/trainer

    # A malformed row that causes an IndexError (e.g., not enough links for jockey/trainer)
    mock_row_malformed = MagicMock()
    mock_row_malformed.select_one.side_effect = [
        MagicMock(text="2"), # num
        MagicMock(text="Nom Malformé"), # nom
        MagicMock(text="1.8"), # odds_win
        MagicMock(text="1.3"), # odds_place
        MagicMock(text="Musique"), # musique
        MagicMock(text="Gains"), # gains
    ]
    mock_row_malformed.select.return_value = [MagicMock(text="Only One Link")] # Not enough links for jockey/trainer (links[1] will fail)

    mock_runners_table.select.return_value = [mock_row_valid, mock_row_malformed]
    mock_soup_instance.select_one.return_value = mock_runners_table
    mock_beautiful_soup.return_value = mock_soup_instance


    fetcher = BoturfersFetcher(race_url="http://race.url")
    fetcher.soup = mock_soup_instance
    runners = fetcher._parse_race_runners_from_details_page()

    assert len(runners) == 1
    assert runners[0]["nom"] == "Nom Valide"
    assert "Failed to parse a runner row: list index out of range. Row skipped." in caplog.text


@pytest.mark.asyncio
async def test_fetcher_parse_race_runners_from_details_page_no_odds(mock_httpx_and_soup):
    """Test runner parsing when odds are missing from a row."""
    _, mock_beautiful_soup = mock_httpx_and_soup
    html_row = """
    <tr>
        <th class="num">1</th>
        <td class="tl">
            <a class="link">Cheval A</a>
            <div class="size-s"><a class="link">J. Dupont</a></div>
            <a class="link lg">E. Trainer</a>
        </td>
        <td class="cote-gagnant"><!-- No odds --></td>
        <td class="cote-place"><!-- No place odds --></td>
        <td class="musique">1p2p3p</td>
        <td class="gains">123456</td>
    </tr>
    """
    mock_soup_instance = BeautifulSoup(f'<table class="table data"><tbody>{html_row}</tbody></table>', "lxml")
    mock_beautiful_soup.return_value = mock_soup_instance

    fetcher = BoturfersFetcher(race_url="http://race.url")
    fetcher.soup = mock_soup_instance
    runners = fetcher._parse_race_runners_from_details_page()
    
    assert len(runners) == 1
    assert runners[0]["odds_win"] is None
    assert runners[0]["odds_place"] is None
    assert runners[0]["nom"] == "Cheval A"


@pytest.mark.asyncio
async def test_parse_race_runners_missing_musique_gains(mock_httpx_and_soup):
    """Test runner parsing when musique or gains tags are missing from a row."""
    _, mock_beautiful_soup = mock_httpx_and_soup
    html_row = """
    <tr>
        <th class="num">1</th>
        <td class="tl">
            <a class="link">Cheval B</a>
            <div class="size-s"><a class="link">J. Smith</a></div>
            <a class="link lg">E. Jones</a>
        </td>
        <td class="cote-gagnant"><span class="c">3,0</span></td>
        <td class="cote-place"><span class="c">1,5</span></td>
        <td class="musique"></td> <!-- Empty musique tag -->
        <!-- Missing gains tag -->
    </tr>
    """
    mock_soup_instance = BeautifulSoup(f'<table class="table data"><tbody>{html_row}</tbody></table>', "lxml")
    mock_beautiful_soup.return_value = mock_soup_instance

    fetcher = BoturfersFetcher(race_url="http://race.url")
    fetcher.soup = mock_soup_instance
    runners = fetcher._parse_race_runners_from_details_page()
    
    assert len(runners) == 1
    assert runners[0]["nom"] == "Cheval B"
    assert runners[0]["musique"] == "" # Should be empty string from empty tag
    assert runners[0]["gains"] is None # Should be None from missing tag


@pytest.mark.asyncio
async def test_fetcher_parse_race_row_missing_url(mock_httpx_and_soup, caplog):
    """Test _parse_race_row returns None if the race link has no href attribute."""
    _, mock_beautiful_soup = mock_httpx_and_soup
    fetcher = BoturfersFetcher(race_url="http://base.url")

    mock_row = MagicMock()
    mock_row.select_one.side_effect = [
        MagicMock(text="R1C1"),  # rc_tag
        MagicMock(text="Race Name", get=lambda x: None),  # name_tag without href
    ]

    result = fetcher._parse_race_row(mock_row, "http://base.url")
    assert result is None


@pytest.mark.asyncio
async def test_fetcher_parse_race_row_no_name_tag(mock_httpx_and_soup, caplog):
    """Test _parse_race_row returns None and logs warning if no name_tag is found."""
    _, mock_beautiful_soup = mock_httpx_and_soup
    fetcher = BoturfersFetcher(race_url="http://base.url")

    mock_row = MagicMock()
    mock_row.select_one.side_effect = [
        MagicMock(text="R1C1"),  # rc_tag
        None,  # name_tag is None
    ]

    result = fetcher._parse_race_row(mock_row, "http://base.url")
    assert result is None


# Tests pour get_snapshot et get_race_snapshot
@pytest.mark.asyncio
@patch("hippique_orchestrator.scrapers.boturfers.BoturfersFetcher._fetch_html")
async def test_get_snapshot_fetch_html_fails(mock_fetch_html, caplog):
    """Test get_snapshot returns an error if _fetch_html fails."""
    mock_fetch_html.return_value = False

    fetcher = BoturfersFetcher(race_url="http://programme.url")
    snapshot = await fetcher.get_snapshot()

    assert snapshot == {"error": "Failed to fetch HTML"}
    assert mock_fetch_html.called


@pytest.mark.asyncio
@patch("hippique_orchestrator.scrapers.boturfers.BoturfersFetcher._fetch_html")
@patch("hippique_orchestrator.scrapers.boturfers.BoturfersFetcher._parse_programme")
async def test_get_snapshot_no_races_extracted(mock_parse_programme, mock_fetch_html, caplog):
    """Test get_snapshot logs an error if no races are extracted."""
    mock_fetch_html.return_value = True
    mock_parse_programme.return_value = []

    fetcher = BoturfersFetcher(race_url="http://programme.url")
    snapshot = await fetcher.get_snapshot()

    assert snapshot["races"] == []
    assert "Aucune course n'a pu être extraite de http://programme.url." in caplog.text


@pytest.mark.asyncio
@patch("hippique_orchestrator.scrapers.boturfers.BoturfersFetcher._fetch_html")
async def test_get_race_snapshot_fetch_html_fails(mock_fetch_html, caplog):
    """Test get_race_snapshot returns an error if _fetch_html fails."""
    mock_fetch_html.return_value = False

    fetcher = BoturfersFetcher(race_url="http://race.url")
    snapshot = await fetcher.get_race_snapshot()

    assert snapshot == {"error": "Failed to fetch HTML"}
    assert mock_fetch_html.called


@pytest.mark.asyncio
@patch("hippique_orchestrator.scrapers.boturfers.BoturfersFetcher._fetch_html")
@patch("hippique_orchestrator.scrapers.boturfers.BoturfersFetcher._parse_race_metadata")
@patch("hippique_orchestrator.scrapers.boturfers.BoturfersFetcher._parse_race_runners_from_details_page")
async def test_get_race_snapshot_no_runners_extracted(mock_parse_runners, mock_parse_metadata, mock_fetch_html, caplog):
    """Test get_race_snapshot logs an error if no runners are extracted."""
    mock_fetch_html.return_value = True
    mock_parse_metadata.return_value = {}
    mock_parse_runners.return_value = []

    fetcher = BoturfersFetcher(race_url="http://race.url")
    snapshot = await fetcher.get_race_snapshot()

    assert snapshot["runners"] == []
    assert "Aucun partant n'a pu être extrait de http://race.url." in caplog.text


# Tests pour les fonctions fetch_boturfers_programme et fetch_boturfers_race_details
@pytest.mark.asyncio
@patch("hippique_orchestrator.scrapers.boturfers.BoturfersFetcher.get_snapshot")
@patch("hippique_orchestrator.scrapers.boturfers.BoturfersFetcher._fetch_html")
async def test_fetch_boturfers_programme_fetcher_error(mock_fetch_html, mock_get_snapshot, caplog):
    """Test fetch_boturfers_programme handles fetcher errors gracefully."""
    mock_fetch_html.return_value = False
    mock_get_snapshot.return_value = {"error": "Failed to fetch HTML"} # This mock is not strictly necessary if _fetch_html is patched

    result = await fetch_boturfers_programme("http://programme.url")

    assert result == {}
    assert "Le scraping du programme a échoué ou n'a retourné aucune course." in caplog.text


@pytest.mark.asyncio
@patch("hippique_orchestrator.scrapers.boturfers.BoturfersFetcher.get_race_snapshot")
@patch("hippique_orchestrator.scrapers.boturfers.BoturfersFetcher._fetch_html")
async def test_fetch_boturfers_race_details_fetcher_error(mock_fetch_html, mock_get_race_snapshot, caplog):
    """Test fetch_boturfers_race_details handles fetcher errors gracefully."""
    mock_fetch_html.return_value = False
    mock_get_race_snapshot.return_value = {"error": "Failed to fetch HTML"} # This mock is not strictly necessary if _fetch_html is patched

    result = await fetch_boturfers_race_details("http://race.url")

    assert result == {}
    assert "Le scraping des détails a échoué." in caplog.text
