"""
Unit tests for the StatsProvider implementations.
"""

from datetime import datetime

import pytest

from hippique_orchestrator.stats_provider import ZoneTurfProvider

# Mock config for the provider
MOCK_ZT_CONFIG = {
    "base_url": "https://www.zone-turf.fr",
    "horse_path": "/cheval/{slug}-{id}/",
    "jockey_path": "/jockey/{slug}-{id}/",
    "trainer_path": "/entraineur/{slug}-{id}/",
    "horse_letter_index_path": "/cheval/lettre-{letter}.html?p={page}",
    "jockey_letter_index_path": "/jockey/lettre-{letter}.html?p={page}",
    "trainer_letter_index_path": "/entraineur/lettre-{letter}.html?p={page}",
}


@pytest.fixture
def zt_provider() -> ZoneTurfProvider:
    """Provides a reusable instance of the ZoneTurfProvider for tests."""
    return ZoneTurfProvider(config=MOCK_ZT_CONFIG)


class TestZoneTurfProviderParsing:
    """Tests the parsing logic of the ZoneTurfProvider."""

    @pytest.mark.parametrize(
        "chrono_str, expected_seconds",
        [
            ("1'11\"6", 71.6),
            ("1'12''3", 72.3),
            ("1'10\"", 70.0),
            ("59\"8", 59.8),
            (None, None),
            ("", None),
            ("invalid", None),
        ],
    )
    def test_parse_chrono_to_seconds(
        self, zt_provider: ZoneTurfProvider, chrono_str, expected_seconds
    ):
        """Tests the chrono string parsing utility."""
        assert zt_provider._parse_chrono_to_seconds(chrono_str) == expected_seconds

    def test_fetch_horse_chrono_parsing(self, zt_provider: ZoneTurfProvider, mocker):
        """Tests the parsing of a mock horse page."""
        mock_html = """
        <html>
            <body>
                <table class="performances-table">
                    <tr><td>Record attelé</td><td>1'10"5</td></tr>
                    <tr><td>Record monté</td><td>1'12"1</td></tr>
                </table>
                <table id="horse-performances-table">
                    <tbody>
                        <tr><td>data</td><td>data</td><td>data</td><td>data</td><td>data</td><td>data</td><td>1'11"8</td></tr>
                        <tr><td>data</td><td>data</td><td>data</td><td>data</td><td>data</td><td>data</td><td>1'12"2</td></tr>
                        <tr><td>data</td><td>data</td><td>data</td><td>data</td><td>data</td><td>data</td><td>1'11"9</td></tr>
                    </tbody>
                </table>
            </body>
        </html>
        """
        mock_response = mocker.Mock()
        mock_response.text = mock_html
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch.object(zt_provider.client, 'get', return_value=mock_response)
        mocker.patch.object(zt_provider, '_resolve_entity_id', return_value="12345")

        chrono = zt_provider.fetch_horse_chrono("Test Horse")

        assert chrono is not None
        assert chrono.record_attele_sec == 70.5
        assert chrono.record_monte_sec == 72.1
        assert chrono.last3_rk_sec == [71.8, 72.2, 71.9]
        assert chrono.rk_best3_sec == 71.8

    def test_fetch_jockey_stats_parsing(self, zt_provider: ZoneTurfProvider, mocker):
        """Tests the parsing of a mock jockey page."""
        mock_html = """
        <html>
            <body>
                <h2>Statistiques 2025 de E. Raffin</h2>
                <table>
                    <tr><td>Courses</td><td> 850 </td></tr>
                    <tr><td>Victoires</td><td> 150 </td></tr>
                    <tr><td>Placés</td><td> 425 </td></tr>
                </table>
            </body>
        </html>
        """
        mock_response = mocker.Mock()
        mock_response.text = mock_html
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch.object(zt_provider.client, 'get', return_value=mock_response)
        mocker.patch.object(zt_provider, '_resolve_entity_id', return_value="2957")

        stats = zt_provider.fetch_jockey_stats("E. Raffin")

        assert stats is not None
        assert stats.year == datetime.now().year
        assert stats.starters == 850
        assert stats.wins == 150
        assert stats.places == 425
        assert stats.win_rate == pytest.approx(150 / 850)
        assert stats.place_rate == pytest.approx(425 / 850)

    def test_fetch_trainer_stats_parsing(self, zt_provider: ZoneTurfProvider, mocker):
        """Tests the parsing of a mock trainer page."""
        mock_html = """
        <html>
            <body>
                <h2>Statistiques 2025 de S. Mestries</h2>
                <table>
                    <tr><td>Partants</td><td> 109 </td></tr>
                    <tr><td>Victoires</td><td> 4 </td></tr>
                    <tr><td>Placés</td><td> 25 </td></tr>
                </table>
            </body>
        </html>
        """
        mock_response = mocker.Mock()
        mock_response.text = mock_html
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch.object(zt_provider.client, 'get', return_value=mock_response)
        mocker.patch.object(zt_provider, '_resolve_entity_id', return_value="54007")

        stats = zt_provider.fetch_trainer_stats("S. Mestries")

        assert stats is not None
        assert stats.year == datetime.now().year
        assert stats.starters == 109
        assert stats.wins == 4
        assert stats.places == 25
        assert stats.win_rate == pytest.approx(4 / 109)
        assert stats.place_rate == pytest.approx(25 / 109)


class TestZoneTurfIdResolution:
    """Tests the ID resolution logic."""

    def test_resolve_entity_id_cache_hit(self, zt_provider: ZoneTurfProvider, mocker):
        """Ensures the cache is checked first."""
        mocker.patch.object(zt_provider, '_get_id_from_cache', return_value="12345")
        mock_http_get = mocker.patch.object(zt_provider.client, 'get')

        entity_id = zt_provider._resolve_entity_id("horse", "My Horse")

        assert entity_id == "12345"
        zt_provider._get_id_from_cache.assert_called_once_with("horse", "My Horse")
        mock_http_get.assert_not_called()

    def test_resolve_entity_id_scraping(self, zt_provider: ZoneTurfProvider, mocker):
        """Tests the successful scraping of an ID from the index."""
        # TODO: Add mock HTML and test the scraping logic
        pass

    def test_resolve_entity_id_not_found(self, zt_provider: ZoneTurfProvider, mocker):
        """Tests the case where an entity is not found after scraping all pages."""
        # TODO: Add mock HTML and test the not found case
        pass
