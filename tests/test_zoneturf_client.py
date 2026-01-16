import pathlib
from unittest.mock import MagicMock, patch

import pytest
import requests  # Needed to mock this

from hippique_orchestrator.zoneturf_client import (
    BASE_URL,  # To check URLs built
    CHRONO_CACHE,
    ID_CACHE,
    PERSON_ID_CACHE,
    PERSON_STATS_CACHE,
    _normalize_name,
    _parse_rk_string,
    fetch_chrono_from_html,
    fetch_person_stats_from_html,
    get_chrono_stats,
    get_jockey_trainer_stats,
    resolve_horse_id,
    resolve_person_id,
)

FIXTURE_DIR = pathlib.Path(__file__).parent / 'fixtures'


@pytest.fixture
def zade_html_content() -> str:
    """Provides the HTML content of the Zade Zone-Turf page."""
    fixture_path = FIXTURE_DIR / 'zoneturf_zade.html'
    if not fixture_path.exists():
        pytest.fail(f"Fixture file not found: {fixture_path}")
    return fixture_path.read_text(encoding='utf-8')


@pytest.fixture
def horse_alpha_z_html() -> str:
    fixture_path = FIXTURE_DIR / 'zoneturf_horse_alpha_z.html'
    if not fixture_path.exists():
        pytest.fail(f"Fixture file not found: {fixture_path}")
    return fixture_path.read_text(encoding='utf-8')


@pytest.fixture
def horse_alpha_empty_html() -> str:
    fixture_path = FIXTURE_DIR / 'zoneturf_horse_alpha_empty.html'
    if not fixture_path.exists():
        pytest.fail(f"Fixture file not found: {fixture_path}")
    return fixture_path.read_text(encoding='utf-8')


@pytest.fixture
def person_alpha_s_jockey_html() -> str:
    fixture_path = FIXTURE_DIR / 'zoneturf_person_alpha_s_jockey.html'
    if not fixture_path.exists():
        pytest.fail(f"Fixture file not found: {fixture_path}")
    return fixture_path.read_text(encoding='utf-8')


@pytest.fixture
def person_alpha_empty_html() -> str:
    fixture_path = FIXTURE_DIR / 'zoneturf_person_alpha_empty.html'
    if not fixture_path.exists():
        pytest.fail(f"Fixture file not found: {fixture_path}")
    return fixture_path.read_text(encoding='utf-8')


@pytest.fixture
def person_page_stephane_pasquier_html() -> str:
    fixture_path = FIXTURE_DIR / 'zoneturf_person_page_stephane_pasquier.html'
    if not fixture_path.exists():
        pytest.fail(f"Fixture file not found: {fixture_path}")
    return fixture_path.read_text(encoding='utf-8')


@pytest.fixture(autouse=True)
def clear_caches():
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


# --- Tests for _normalize_name ---
@pytest.mark.parametrize(
    "input_name, expected_normalized",
    [
        ("Zade", "zade"),
        ("  Zade  ", "zade"),
        ("Zade (FR)", "zade"),
        ("Zade-Nivard", "zade nivard"),
        ("Zade-Nivard (FR)", "zade nivard"),
        ("Écurie Royale", "ecurie royale"),
        ("Zade's Horse", "zades horse"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_name(input_name, expected_normalized):
    # Call _normalize_name directly from the module
    assert _normalize_name(input_name) == expected_normalized


# --- Tests for _parse_rk_string ---
@pytest.mark.parametrize(
    "input_str, expected_seconds",
    [
        ("1'11\"6", 71.6),
        ("1'15''3", 75.3),
        ("1'20\"0", 80.0),
        ("0'59\"9", 59.9),
        (None, None),
        ("", None),
        ("invalid", None),
        ("1'11", None),
    ],
)
def test_parse_rk_string(input_str, expected_seconds):
    """Tests the parsing of reduction kilometer strings."""
    if expected_seconds is None:
        assert _parse_rk_string(input_str) is None
    else:
        assert _parse_rk_string(input_str) == pytest.approx(expected_seconds)


# --- Tests for resolve_horse_id ---
def test_resolve_horse_id_success(mock_requests_get, horse_alpha_z_html):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = horse_alpha_z_html
    mock_requests_get.return_value = mock_response

    horse_id = resolve_horse_id("Zade")
    assert horse_id == "2127225"
    assert ID_CACHE["zade"] == "2127225"
    mock_requests_get.assert_called_once_with(
        f"{BASE_URL}/cheval/lettre-z.html?p=1", timeout=15, headers={"User-Agent": "Mozilla/5.0"}
    )


def test_resolve_horse_id_not_found(mock_requests_get, horse_alpha_empty_html):
    mock_response = MagicMock()
    mock_response.status_code = 200
    # Use the empty HTML fixture directly to simulate no horse found
    mock_response.text = horse_alpha_empty_html
    mock_requests_get.return_value = mock_response

    horse_id = resolve_horse_id("NonExistentHorse")
    assert horse_id is None
    assert ID_CACHE["nonexistenthorse"] is None
    # The first letter of "NonExistentHorse" is 'n'
    # It should iterate through all max_pages when not found and no "page suivante" link
    mock_requests_get.assert_called_with(
        f"{BASE_URL}/cheval/lettre-n.html?p=20", timeout=15, headers={"User-Agent": "Mozilla/5.0"}
    )
    assert mock_requests_get.call_count == 20  # Verify it tried all pages


def test_resolve_horse_id_network_error(mock_requests_get):
    mock_requests_get.side_effect = requests.RequestException("Network issue")

    horse_id = resolve_horse_id("Zade")
    assert horse_id is None
    assert ID_CACHE["zade"] is None
    mock_requests_get.assert_called_once()  # Ensure get was attempted


def test_resolve_horse_id_cache_hit(mock_requests_get):
    ID_CACHE["zade"] = "12345"
    horse_id = resolve_horse_id("Zade")
    assert horse_id == "12345"
    mock_requests_get.assert_not_called()


def test_resolve_horse_id_no_alpha_in_name(mock_requests_get):
    horse_id = resolve_horse_id("12345")
    assert horse_id is None
    assert ID_CACHE["12345"] is None
    mock_requests_get.assert_not_called()


# --- Tests for resolve_person_id ---
def test_resolve_person_id_success(mock_requests_get, person_alpha_s_jockey_html):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = person_alpha_s_jockey_html
    mock_requests_get.return_value = mock_response

    person_id = resolve_person_id("Stephane Pasquier", "jockey")
    assert person_id == "743"
    assert PERSON_ID_CACHE["jockey_stephane pasquier"] == "743"
    mock_requests_get.assert_called_once_with(
        f"{BASE_URL}/jockey/lettre-s.html?p=1", timeout=15, headers={"User-Agent": "Mozilla/5.0"}
    )


def test_resolve_person_id_cache_hit(mock_requests_get):
    PERSON_ID_CACHE["jockey_stephane pasquier"] = "98765"
    person_id = resolve_person_id("Stephane Pasquier", "jockey")
    assert person_id == "98765"
    mock_requests_get.assert_not_called()


def test_resolve_person_id_not_found(mock_requests_get, person_alpha_empty_html):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = person_alpha_empty_html
    mock_requests_get.return_value = mock_response

    person_id = resolve_person_id("NonExistentJockey", "jockey")
    assert person_id is None
    assert PERSON_ID_CACHE["jockey_nonexistentjockey"] is None
    # The first letter of "NonExistentJockey" is 'n'
    # It should iterate through all max_pages when not found and no "page suivante" link
    mock_requests_get.assert_called_with(
        f"{BASE_URL}/jockey/lettre-n.html?p=20", timeout=15, headers={"User-Agent": "Mozilla/5.0"}
    )
    assert mock_requests_get.call_count == 20  # Verify it tried all pages


# --- Tests for fetch_chrono_from_html ---
def test_fetch_chrono_from_html_with_zade_page(zade_html_content):
    """
    Tests the main HTML parsing function using the saved fixture for 'Zade'.
    """
    assert zade_html_content is not None, "Fixture content should not be None"

    result = fetch_chrono_from_html(zade_html_content, "Zade")

    assert result is not None, "Parsing should return a result dict"

    # Check record
    assert result.get('record_attele') is None

    # Check last 3 chronos from the performance table
    assert 'last_3_chrono' in result
    last_3 = result['last_3_chrono']

    assert isinstance(last_3, list)
    assert len(last_3) == 0, "Should find no valid chronos"


def test_fetch_chrono_from_html_no_chrono_data():
    html_content = "<html><body></body></html>"
    result = fetch_chrono_from_html(html_content, "TestHorse")
    assert result == {'last_3_chrono': []}


def test_fetch_chrono_from_html_empty_content():
    result = fetch_chrono_from_html("", "TestHorse")
    assert result is None


def test_fetch_chrono_from_html_malformed_record():
    html_content = """
    <div class="card-body"><p><strong>Record Attelé :</strong> invalid string</p></div>
    """
    result = fetch_chrono_from_html(html_content, "TestHorse")
    assert result is not None
    assert result.get('record_attele') is None
    assert result.get('last_3_chrono') == []


def test_fetch_chrono_from_html_malformed_table_chrono():
    html_content = """
    <div class="card-body">
        <p><strong>Record Attelé :</strong> 1'10"0</p>
    </div>
    <ul class="list-group">
        <li class="list-group-item">
            <p>Attelé</p>
            <table><thead><tr><th>Red.Km</th></tr></thead><tbody><tr><td>invalid</td></tr></tbody></table>
        </li>
    </ul>
    """
    result = fetch_chrono_from_html(html_content, "TestHorse")
    assert result is not None
    assert result.get('record_attele') is None
    assert result.get('last_3_chrono') == []


def test_fetch_chrono_from_html_correctly_finds_zade_chrono():
    html_content = """
    <div class="card mb-4">
        <div class="card-header">
            Performances détaillées
        </div>
        <div class="card-body">
            <ul class="list-group">
                <li class="list-group-item">
                    <p>19 000€ - Prix Axius - Attelé</p>
                    <table class="table"><thead><tr><th>Rg</th><th>Cheval</th><th>Red.Km</th></tr></thead>
                        <tbody>
                            <tr><td>1</td><td>Javotte Madrik</td><td>1'14"1</td></tr>
                            <tr><td>0</td><td>Zade</td><td>1'15"1</td></tr>
                        </tbody>
                    </table>
                </li>
            </ul>
        </div>
    </div>
    """
    result = fetch_chrono_from_html(html_content, "Zade")
    assert result is not None
    assert result['last_3_chrono'] == [75.1]


# --- Tests for fetch_person_stats_from_html ---
def test_fetch_person_stats_from_html_success(person_page_stephane_pasquier_html):
    result = fetch_person_stats_from_html(person_page_stephane_pasquier_html, "jockey")
    assert result is not None
    assert result.get('win_rate') is None
    assert result.get('place_rate') == 18.0
    assert result.get('num_races') == 17
    assert result.get('num_wins') is None
    assert result.get('num_places') == 3


def test_fetch_person_stats_from_html_no_stats_block():
    html_content = "<html><body></body></html>"
    result = fetch_person_stats_from_html(html_content, "jockey")
    assert result is None


def test_fetch_person_stats_from_html_empty_content():
    result = fetch_person_stats_from_html("", "jockey")
    assert result is None


# --- Tests for get_chrono_stats ---
def test_get_chrono_stats_success(mock_requests_get, zade_html_content, caplog):
    # Mock resolve_horse_id to immediately return a known ID
    with patch('hippique_orchestrator.zoneturf_client.resolve_horse_id', return_value="2127225"):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = zade_html_content
        mock_requests_get.return_value = mock_response

        horse_name = "Zade"
        stats = get_chrono_stats(horse_name)

        assert stats is not None
        assert stats.get('record_attele') is None
        assert CHRONO_CACHE[horse_name.lower()] == stats
        mock_requests_get.assert_called_once_with(
            f"{BASE_URL}/cheval/{_normalize_name(horse_name).replace(' ', '-')}-2127225/",
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )


def test_get_chrono_stats_id_not_resolved(caplog):
    with patch('hippique_orchestrator.zoneturf_client.resolve_horse_id', return_value=None):
        stats = get_chrono_stats("Zade")
        assert stats is None
        assert CHRONO_CACHE["zade"] is None
        assert "Could not get Zone-Turf ID for horse: Zade" in caplog.text


def test_get_chrono_stats_network_error_fetching_page(mock_requests_get, caplog):
    with patch('hippique_orchestrator.zoneturf_client.resolve_horse_id', return_value="2127225"):
        mock_requests_get.side_effect = requests.RequestException("Network error")
        stats = get_chrono_stats("Zade")
        assert stats is None
        assert CHRONO_CACHE["zade"] is None
        assert "Failed to fetch Zone-Turf page for Zade due to network error" in caplog.text


def test_get_chrono_stats_page_fetch_failed(mock_requests_get, caplog):
    with patch('hippique_orchestrator.zoneturf_client.resolve_horse_id', return_value="2127225"):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_requests_get.return_value = mock_response
        stats = get_chrono_stats("Zade")
        assert stats is None
        assert CHRONO_CACHE["zade"] is None
        assert (
            "Failed to fetch Zone-Turf page for Zade (ID: 2127225) with status 404" in caplog.text
        )


def test_get_chrono_stats_cache_hit(mock_requests_get):
    CHRONO_CACHE["zade"] = {"record_attele": 70.0}
    stats = get_chrono_stats("Zade")
    assert stats == {"record_attele": 70.0}
    mock_requests_get.assert_not_called()


# --- Tests for get_jockey_trainer_stats ---
def test_get_jockey_trainer_stats_success(mock_requests_get, person_page_stephane_pasquier_html, caplog):
    with patch('hippique_orchestrator.zoneturf_client.resolve_person_id', return_value="743"):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = person_page_stephane_pasquier_html
        mock_requests_get.return_value = mock_response

        person_name = "Stephane Pasquier"
        person_type = "jockey"
        stats = get_jockey_trainer_stats(person_name, person_type)

        assert stats is not None
        assert stats.get('win_rate') is None
        assert PERSON_STATS_CACHE[f"{person_type}_{_normalize_name(person_name)}"] == stats
        mock_requests_get.assert_called_once_with(
            f"{BASE_URL}/{person_type}/{_normalize_name(person_name).replace(' ', '-')}-743/",
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )


def test_get_jockey_trainer_stats_id_not_resolved(caplog):
    with patch('hippique_orchestrator.zoneturf_client.resolve_person_id', return_value=None):
        stats = get_jockey_trainer_stats("Julien Dupont", "jockey")
        assert stats is None
        assert PERSON_STATS_CACHE["jockey_julien dupont"] is None
        assert "Could not get Zone-Turf ID for jockey: Julien Dupont" in caplog.text


def test_get_jockey_trainer_stats_cache_hit(mock_requests_get):
    PERSON_STATS_CACHE["jockey_julien dupont"] = {"win_rate": 20.0}
    stats = get_jockey_trainer_stats("Julien Dupont", "jockey")
    assert stats == {"win_rate": 20.0}
    mock_requests_get.assert_not_called()


def test_get_jockey_trainer_stats_network_error_fetching_page(mock_requests_get, caplog):
    with patch('hippique_orchestrator.zoneturf_client.resolve_person_id', return_value="112233"):
        mock_requests_get.side_effect = requests.RequestException("Network error")
        stats = get_jockey_trainer_stats("Julien Dupont", "jockey")
        assert stats is None
        assert PERSON_STATS_CACHE["jockey_julien dupont"] is None
        assert (
            "Failed to fetch Zone-Turf page for jockey Julien Dupont due to network error"
            in caplog.text
        )


def test_get_jockey_trainer_stats_page_fetch_failed(mock_requests_get, caplog):
    with patch('hippique_orchestrator.zoneturf_client.resolve_person_id', return_value="112233"):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_requests_get.return_value = mock_response
        stats = get_jockey_trainer_stats("Julien Dupont", "jockey")
        assert stats is None
        assert PERSON_STATS_CACHE["jockey_julien dupont"] is None
        assert (
            "Failed to fetch Zone-Turf page for jockey Julien Dupont (ID: 112233) with status 404"
            in caplog.text
        )
