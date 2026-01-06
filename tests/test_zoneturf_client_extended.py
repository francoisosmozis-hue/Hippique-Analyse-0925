from __future__ import annotations

import pathlib
from unittest.mock import MagicMock, call, patch

import pytest
from pytest import LogCaptureFixture

from hippique_orchestrator.zoneturf_client import (
    BASE_URL,  # To check URLs built
    CHRONO_CACHE,
    ID_CACHE,
    PERSON_ID_CACHE,
    PERSON_STATS_CACHE,
    fetch_chrono_from_html,
    fetch_person_stats_from_html,
    resolve_horse_id,
    resolve_person_id,
)

FIXTURE_DIR = pathlib.Path(__file__).parent / 'fixtures'

# --- Fixtures for missing/malformed HTML snippets ---


@pytest.fixture
def empty_html() -> str:
    return "<html><body></body></html>"


@pytest.fixture
def html_no_info_card() -> str:
    return "<html><body><div class='card-body'>No info card here</div></body></html>"


@pytest.fixture
def html_no_performance_card() -> str:
    return "<html><body><div class='card-header'>Informations générales</div><div class='card-body'>...</div></body></html>"


@pytest.fixture
def html_performance_no_list_group() -> str:
    return """
    <html><body>
        <div class="card-header">Performances détaillées</div>
        <div class="card-body">
            <!-- No ul with class list-group -->
        </div>
    </body></html>
    """


@pytest.fixture
def html_performance_no_attelle_li() -> str:
    return """
    <html><body>
        <div class="card-header">Performances détaillées</div>
        <div class="card-body">
            <ul class="list-group">
                <li class="list-group-item">
                    <p>Obstacle</p>
                    <table><thead><tr><th>Rg</th><th>Cheval</th><th>Red.Km</th></tr></thead><tbody><tr><td>1</td><td>OtherHorse</td><td>1'10"0</td></tr></tbody></table>
                </li>
            </ul>
        </div>
    </body></html>
    """


@pytest.fixture
def html_performance_no_red_km_header() -> str:
    return """
    <html><body>
        <div class="card-header">Performances détaillées</div>
        <div class="card-body">
            <ul class="list-group">
                <li class="list-group-item">
                    <p>Attelé</p>
                    <table><thead><tr><th>Rg</th><th>Cheval</th><th>Distance</th></tr></thead><tbody><tr><td>1</td><td>Jullou</td><td>2000m</td></tr></tbody></table>
                </li>
            </ul>
        </div>
    </body></html>
    """


@pytest.fixture
def html_performance_malformed_row() -> str:
    return """
    <html><body>
        <div class="card-header">Performances détaillées</div>
        <div class="card-body">
            <ul class="list-group">
                <li class="list-group-item">
                    <p>Attelé</p>
                    <table><thead><tr><th>Rg</th><th>Cheval</th><th>Red.Km</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table>
                </li>
            </ul>
        </div>
    </body></html>
    """


@pytest.fixture
def html_performance_other_horse_name() -> str:
    return """
    <html><body>
        <div class="card-header">Performances détaillées</div>
        <div class="card-body">
            <ul class="list-group">
                <li class="list-group-item">
                    <p>Attelé</p>
                    <table><thead><tr><th>Rg</th><th>Cheval</th><th>Red.Km</th></tr></thead>
                        <tbody>
                            <tr><td>1</td><td>OtherHorse</td><td>1'10"0</td></tr>
                            <tr><td>1</td><td>AnotherHorse</td><td>1'11"0</td></tr>
                        </tbody>
                    </table>
                </li>
            </ul>
        </div>
    </body></html>
    """


@pytest.fixture
def html_person_stats_missing_rates() -> str:
    return """
    <html><body>
        <div class="card-body">
            <p>Courses : 100</p>
            <table>
                <thead><tr><th>Courses</th><th>Victoires</th><th>Places</th></tr></thead>
                <tbody><tr><td>100</td><td>10</td><td>30</td></tr></tbody>
            </table>
        </div>
    </body></html>
    """


@pytest.fixture
def html_person_stats_missing_table() -> str:
    return """
    <html><body>
        <div class="card-body">
            <p>Taux de réussite : 10.0%</p>
            <p>Taux de réussite Place : 30.0%</p>
        </div>
    </body></html>
    """


@pytest.fixture
def html_person_stats_malformed_table_data() -> str:
    return """
    <html><body>
        <div class="card-body">
            <p>Taux de réussite : 10.0%</p>
            <p>Taux de réussite Place : 30.0%</p>
            <table>
                <thead><tr><th>Courses</th><th>Victoires</th><th>Places</th></tr></thead>
                <tbody><tr><td>abc</td><td>def</td><td>ghi</td></tr></tbody>
            </table>
        </div>
    </body></html>
    """


@pytest.fixture(autouse=True)
def clear_caches_extended():
    ID_CACHE.clear()
    CHRONO_CACHE.clear()
    PERSON_ID_CACHE.clear()
    PERSON_STATS_CACHE.clear()
    yield  # Run test
    ID_CACHE.clear()
    CHRONO_CACHE.clear()
    PERSON_ID_CACHE.clear()
    PERSON_STATS_CACHE.clear()


@pytest.fixture
def mock_requests_get():
    # Patch requests.Session.get which is used by the client functions
    with patch('requests.Session.get') as mock_get:
        yield mock_get


# --- Tests for resolve_horse_id (extended) ---
def test_resolve_horse_id_non_200_status(mock_requests_get, caplog: LogCaptureFixture):
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = "Not Found"
    mock_requests_get.return_value = mock_response

    caplog.set_level("WARNING")
    horse_id = resolve_horse_id("TestHorse")
    assert horse_id is None
    assert "Received non-200 status code 404 for URL" in caplog.text
    mock_requests_get.assert_called_once()  # Should try once and break


def test_resolve_horse_id_url_without_id(mock_requests_get):
    """
    Test scenario where an a_tag matches the horse name but the href
    does not contain a numeric ID.
    """
    malformed_html_page1 = f"""
    <html><body>
        <a href="{BASE_URL}/cheval/jullou-notanid/" title="Jullou">Jullou</a>
        <a href="{BASE_URL}/cheval/lettre-j.html?p=2" title="page suivante">page suivante</a>
    </body></html>
    """
    malformed_html_other_pages = f"""
    <html><body>
        <a href="{BASE_URL}/cheval/otherhorse-1234/" title="OtherHorse">OtherHorse</a>
    </body></html>
    """

    mock_response_page1 = MagicMock(status_code=200, text=malformed_html_page1)
    mock_response_other_pages = MagicMock(status_code=200, text=malformed_html_other_pages)

    # Configure mock_requests_get to return the malformed page once, then empty pages
    mock_requests_get.side_effect = [mock_response_page1] + [
        mock_response_other_pages
    ] * 19  # Simulate 20 pages

    horse_id = resolve_horse_id("Jullou")
    assert horse_id is None
    # Expect it to have tried all max_pages attempts
    assert mock_requests_get.call_count == 20
    # Also check the last call to ensure it iterated
    expected_last_call = call(
        f"{BASE_URL}/cheval/lettre-j.html?p=20", timeout=15, headers={"User-Agent": "Mozilla/5.0"}
    )
    assert mock_requests_get.call_args_list[-1] == expected_last_call


# --- Tests for fetch_chrono_from_html (extended) ---
def test_fetch_chrono_from_html_no_info_card(html_no_info_card):
    result = fetch_chrono_from_html(html_no_info_card, "TestHorse")
    assert result == {'last_3_chrono': []}  # Should return empty but not None


def test_fetch_chrono_from_html_no_performance_card(html_no_performance_card):
    result = fetch_chrono_from_html(html_no_performance_card, "TestHorse")
    assert result == {'last_3_chrono': []}  # Should return empty but not None


def test_fetch_chrono_from_html_no_record_tag():
    html_content = """
    <html><body>
        <div class="card-header">Informations générales</div>
        <div class="card-body">
            <p>Some other info</p>
        </div>
    </body></html>
    """
    result = fetch_chrono_from_html(html_content, "TestHorse")
    assert "record_attele" not in result
    assert result == {'last_3_chrono': []}


def test_fetch_chrono_from_html_no_record_text():
    html_content = """
    <html><body>
        <div class="card-header">Informations générales</div>
        <div class="card-body">
            <p><strong>Record Attelé :</strong></p> <!-- No text after strong tag -->
        </div>
    </body></html>
    """
    result = fetch_chrono_from_html(html_content, "TestHorse")
    assert "record_attele" not in result
    assert result == {'last_3_chrono': []}


def test_fetch_chrono_from_html_performance_no_list_group(html_performance_no_list_group):
    result = fetch_chrono_from_html(html_performance_no_list_group, "TestHorse")
    assert result == {'last_3_chrono': []}


def test_fetch_chrono_from_html_performance_no_attelle_li(html_performance_no_attelle_li):
    result = fetch_chrono_from_html(html_performance_no_attelle_li, "TestHorse")
    assert result == {'last_3_chrono': []}


def test_fetch_chrono_from_html_performance_no_red_km_header(
    html_performance_no_red_km_header, caplog: LogCaptureFixture
):
    caplog.set_level("DEBUG")
    result = fetch_chrono_from_html(html_performance_no_red_km_header, "Jullou")
    assert result == {'last_3_chrono': []}
    assert "Red.Km column not found" in caplog.text


def test_fetch_chrono_from_html_performance_malformed_row(html_performance_malformed_row):
    result = fetch_chrono_from_html(html_performance_malformed_row, "Jullou")
    assert result == {'last_3_chrono': []}  # No chrono added due to malformed row


def test_fetch_chrono_from_html_performance_other_horse_name(html_performance_other_horse_name):
    result = fetch_chrono_from_html(html_performance_other_horse_name, "Jullou")
    assert result == {'last_3_chrono': []}  # Should not match other horses


def test_fetch_chrono_from_html_multiple_attelle_sections():
    html_content = """
    <html><body>
        <div class="card-header">Performances détaillées</div>
        <div class="card-body">
            <ul class="list-group">
                <li class="list-group-item">
                    <p>Attelé</p>
                    <table><thead><tr><th>Rg</th><th>Cheval</th><th>Red.Km</th></tr></thead>
                        <tbody><tr><td>1</td><td>Jullou</td><td>1'10"0</td></tr></tbody>
                    </table>
                </li>
                <li class="list-group-item">
                    <p>Autre course</p>
                    <table><thead><tr><th>Rg</th><th>Cheval</th><th>Red.Km</th></tr></thead>
                        <tbody><tr><td>1</td><td>Jullou</td><td>1'15"0</td></tr></tbody>
                    </table>
                </li>
                <li class="list-group-item">
                    <p>Attelé</p>
                    <table><thead><tr><th>Rg</th><th>Cheval</th><th>Red.Km</th></tr></thead>
                        <tbody><tr><td>1</td><td>Jullou</td><td>1'11"0</td></tr></tbody>
                    </table>
                </li>
            </ul>
        </div>
    </body></html>
    """
    result = fetch_chrono_from_html(html_content, "Jullou")
    assert result['last_3_chrono'] == [70.0, 71.0]  # Should only pick 'Attelé' ones


# --- Tests for resolve_person_id (extended) ---
def test_resolve_person_id_non_200_status(mock_requests_get, caplog: LogCaptureFixture):
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = "Not Found"
    mock_requests_get.return_value = mock_response

    caplog.set_level("WARNING")
    person_id = resolve_person_id("TestPerson", "jockey")
    assert person_id is None
    assert "Received non-200 status code 404 for URL" in caplog.text
    mock_requests_get.assert_called_once()


def test_resolve_person_id_url_without_id(mock_requests_get):
    """
    Test scenario where an a_tag matches the person name but the href
    does not contain a numeric ID.
    """
    malformed_html_page1 = f"""
    <html><body>
        <a href="{BASE_URL}/jockey/testperson-notanid/" title="TestPerson">TestPerson</a>
        <a href="{BASE_URL}/jockey/lettre-t.html?p=2" title="page suivante">page suivante</a>
    </body></html>
    """
    malformed_html_other_pages = f"""
    <html><body>
        <a href="{BASE_URL}/jockey/otherperson-1234/" title="OtherPerson">OtherPerson</a>
    </body></html>
    """

    mock_response_page1 = MagicMock(status_code=200, text=malformed_html_page1)
    mock_response_other_pages = MagicMock(status_code=200, text=malformed_html_other_pages)

    # Configure mock_requests_get to return the malformed page once, then empty pages
    mock_requests_get.side_effect = [mock_response_page1] + [
        mock_response_other_pages
    ] * 19  # Simulate 20 pages

    person_id = resolve_person_id("TestPerson", "jockey")
    assert person_id is None
    # Expect it to have tried all max_pages attempts
    assert mock_requests_get.call_count == 20
    # Also check the last call to ensure it iterated
    expected_last_call = call(
        f"{BASE_URL}/jockey/lettre-t.html?p=20", timeout=15, headers={"User-Agent": "Mozilla/5.0"}
    )
    assert mock_requests_get.call_args_list[-1] == expected_last_call


# --- Tests for fetch_person_stats_from_html (extended) ---
def test_fetch_person_stats_from_html_missing_rates(html_person_stats_missing_rates):
    result = fetch_person_stats_from_html(html_person_stats_missing_rates, "jockey")
    assert result is None  # Should return None if any critical stats are missing


def test_fetch_person_stats_from_html_missing_table(html_person_stats_missing_table):
    result = fetch_person_stats_from_html(html_person_stats_missing_table, "jockey")
    assert result is None  # Should return None if table is missing (num_races, wins, places)


def test_fetch_person_stats_from_html_malformed_table_data(html_person_stats_malformed_table_data):
    result = fetch_person_stats_from_html(html_person_stats_malformed_table_data, "jockey")
    assert result is None  # Should return None if parsing table data fails


def test_fetch_person_stats_from_html_no_stat_paragraph():
    html_content = """
    <html><body>
        <div class="card-body">
            <!-- No P tags with stats -->
            <table>
                <thead><tr><th>Courses</th><th>Victoires</th><th>Places</th></tr></thead>
                <tbody><tr><td>100</td><td>10</td><td>30</td></tr></tbody>
            </table>
        </div>
    </body></html>
    """
    result = fetch_person_stats_from_html(html_content, "jockey")
    assert result is None
