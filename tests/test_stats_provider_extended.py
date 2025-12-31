
import pytest
from hippique_orchestrator import stats_provider
from hippique_orchestrator.stats_provider import Chrono, JEStats
from unittest.mock import MagicMock
import httpx

@pytest.fixture
def provider():
    config = {
        "base_url": "https://www.zone-turf.fr",
        "horse_path": "/cheval/{slug}-{id}/",
        "jockey_path": "/jockey/{slug}-{id}/",
        "trainer_path": "/entraineur/{slug}-{id}/",
        "horse_letter_index_path": "/cheval/lettre-{letter}.html?p={page}",
        "jockey_letter_index_path": "/jockey/lettre-{letter}.html?p={page}",
        "trainer_letter_index_path": "/entraineur/lettre-{letter}.html?p={page}",
    }
    return stats_provider.ZoneTurfProvider(config)

def test_slugify():
    assert stats_provider._slugify("Test String") == "test-string"
    assert stats_provider._slugify("Çà va?") == "ca-va"
    assert stats_provider._slugify("  --multiple--dashes--  ") == "multiple-dashes"

def test_normalize_name(provider):
    assert provider._normalize_name("Test Name") == "testname"
    assert provider._normalize_name("J. Dupont") == "jdupont"

    @pytest.mark.parametrize(

        "chrono_str, expected",

        [

            ("1'11\"6", 71.6),

            ("59\"8", 59.8),

            ("1'12''3", 72.3),

            (None, None),

            ("invalid", None),

        ],

    )

    def test_parse_chrono_to_seconds(provider, chrono_str, expected):

        assert provider._parse_chrono_to_seconds(chrono_str) == expected

def test_fetch_horse_chrono_success(provider, mocker):
    mocker.patch.object(provider, "_resolve_entity_id", return_value="12345")
    mock_response = MagicMock()
    mock_response.text = """
    <table class="performances-table">
        <tr><td>Record attelé</td><td>1'10"5</td></tr>
    </table>
    <table id="horse-performances-table">
        <tbody>
            <tr><td></td><td></td><td></td><td></td><td></td><td></td><td>1'11"0</td></tr>
            <tr><td></td><td></td><td></td><td></td><td></td><td></td><td>1'12"0</td></tr>
        </tbody>
    </table>
    """
    mocker.patch.object(provider.client, "get", return_value=mock_response)

    chrono = provider.fetch_horse_chrono("Test Horse", None)
    assert isinstance(chrono, Chrono)
    assert chrono.record_attele_sec == 70.5
    assert chrono.last3_rk_sec == [71.0, 72.0]
    assert chrono.rk_best3_sec == 71.0

def test_fetch_jockey_stats_success(provider, mocker):
    mocker.patch.object(provider, "_resolve_entity_id", return_value="123")
    mock_response = MagicMock()
    mock_response.text = """
    <h2>Statistiques 2025 de Test Jockey</h2>
    <table>
        <tr><td>Courses</td><td>100</td></tr>
        <tr><td>Victoires</td><td>10</td></tr>
        <tr><td>Placés</td><td>30</td></tr>
    </table>
    """
    mocker.patch.object(provider.client, "get", return_value=mock_response)

    stats = provider.fetch_jockey_stats("Test Jockey", None)
    assert isinstance(stats, JEStats)
    assert stats.starters == 100
    assert stats.wins == 10
    assert stats.places == 30
    assert stats.win_rate == 0.1
    assert stats.place_rate == 0.3

def test_fetch_trainer_stats_success(provider, mocker):
    mocker.patch.object(provider, "_resolve_entity_id", return_value="456")
    mock_response = MagicMock()
    mock_response.text = """
    <h2>Statistiques 2025 de Test Trainer</h2>
    <table>
        <tr><td>Partants</td><td>200</td></tr>
        <tr><td>Victoires</td><td>20</td></tr>
        <tr><td>Placés</td><td>60</td></tr>
    </table>
    """
    mocker.patch.object(provider.client, "get", return_value=mock_response)

    stats = provider.fetch_trainer_stats("Test Trainer", None)
    assert isinstance(stats, JEStats)
    assert stats.starters == 200
    assert stats.wins == 20
    assert stats.places == 60
    assert stats.win_rate == 0.1
    assert stats.place_rate == 0.3
