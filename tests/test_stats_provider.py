"""
Unit tests for the StatsProvider implementations.
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import httpx

from hippique_orchestrator.stats_provider import ZoneTurfProvider, _slugify
from hippique_orchestrator import firestore_client

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


class TestZoneTurfProviderHelpers:
    """Tests the helper functions of the ZoneTurfProvider."""

    @pytest.mark.parametrize(
        "text, expected_slug",
        [
            ("Test Name", "test-name"),
            ("Un cheval avec accentué", "un-cheval-avec-accentue"),
            ("  leading & trailing spaces  ", "leading-trailing-spaces"),
            ("!@#invalid-chars$%", "invalid-chars"),
            ("", ""),
            ("---", ""),
        ],
    )
    def test_slugify(self, text, expected_slug):
        """Tests the _slugify utility."""
        assert _slugify(text) == expected_slug

    @pytest.mark.parametrize(
        "name, expected_normalized",
        [
            ("E. Raffin", "eraffin"),
            ("J. DUBOIS", "jdubois"),
            ("Jean-Étienne Dubois", "jeanetiennedubois"),
            ("Horse 123", "horse123"),
            ("", ""),
        ],
    )
    def test_normalize_name(self, zt_provider: ZoneTurfProvider, name, expected_normalized):
        """Tests the _normalize_name utility for cache keys."""
        assert zt_provider._normalize_name(name) == expected_normalized


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

    def test_fetch_horse_chrono_parsing_incomplete(self, zt_provider: ZoneTurfProvider, mocker):
        """Tests parsing a horse page with missing data (e.g., no records table)."""
        mock_html = """
        <html>
            <body>
                <!-- No records table -->
                <table id="horse-performances-table">
                    <tbody>
                        <tr><td>data</td><td>data</td><td>data</td><td>data</td><td>data</td><td>data</td><td>1'15"0</td></tr>
                        <tr><td>data</td><td>data</td><td>data</td><td>data</td><td>data</td><td>data</td><td></td></tr>
                        <tr><td>data</td><td>data</td><td>data</td><td>data</td><td>data</td><td>data</td><td>1'14"5</td></tr>
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
        assert chrono.record_attele_sec is None
        assert chrono.record_monte_sec is None
        assert chrono.last3_rk_sec == [75.0, 74.5]  # Only parses valid chronos
        assert chrono.rk_best3_sec == 74.5

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

    @pytest.mark.parametrize(
        "fetch_method_name", ["fetch_horse_chrono", "fetch_jockey_stats", "fetch_trainer_stats"]
    )
    def test_fetch_methods_handle_http_error(
        self, zt_provider: ZoneTurfProvider, mocker, caplog, fetch_method_name
    ):
        """Ensures fetch methods return None and log an error on HTTP failure."""
        # 1. Setup mocks
        mocker.patch.object(zt_provider, '_resolve_entity_id', return_value="12345")

        mock_response = mocker.Mock()
        mock_response.status_code = 404
        mocker.patch.object(
            zt_provider.client,
            'get',
            side_effect=httpx.HTTPStatusError(
                "Not Found", request=mocker.Mock(), response=mock_response
            ),
        )

        # 2. Get and call the method
        fetch_method = getattr(zt_provider, fetch_method_name)
        result = fetch_method("Known Entity")

        # 3. Assertions
        assert result is None
        assert "HTTP error while fetching" in caplog.text

    @pytest.mark.parametrize(
        "mock_html, expected_stats",
        [
            # Case 1: Zero starters
            (
                """
                <html><body><h2>Statistiques 2025 de S. Mestries</h2>
                <table>
                    <tr><td>Partants</td><td> 0 </td></tr>
                    <tr><td>Victoires</td><td> 0 </td></tr>
                    <tr><td>Placés</td><td> 0 </td></tr>
                </table></body></html>
                """,
                {"starters": 0, "wins": 0, "places": 0, "win_rate": 0.0, "place_rate": 0.0},
            ),
            # Case 2: Missing stats table
            (
                "<html><body><h2>Statistiques 2025 de S. Mestries</h2></body></html>",
                None,
            ),
            # Case 3: Missing header
            (
                "<html><body><table><tr><td>Partants</td><td> 10 </td></tr></table></body></html>",
                None,
            ),
        ],
    )
    def test_fetch_trainer_stats_parsing_edge_cases(
        self, zt_provider: ZoneTurfProvider, mocker, mock_html, expected_stats
    ):
        """Tests edge cases for trainer stats parsing like zero starters or missing elements."""
        mock_response = mocker.Mock()
        mock_response.text = mock_html
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch.object(zt_provider.client, 'get', return_value=mock_response)
        mocker.patch.object(zt_provider, '_resolve_entity_id', return_value="54007")

        stats = zt_provider.fetch_trainer_stats("A Trainer")

        if expected_stats is None:
            assert stats is None
        else:
            assert stats is not None
            assert stats.starters == expected_stats["starters"]
            assert stats.wins == expected_stats["wins"]
            assert stats.places == expected_stats["places"]
            assert stats.win_rate == expected_stats["win_rate"]
            assert stats.place_rate == expected_stats["place_rate"]

    @pytest.mark.parametrize(
        "fetch_method_name", ["fetch_horse_chrono", "fetch_jockey_stats", "fetch_trainer_stats"]
    )
    def test_fetch_methods_handle_id_resolution_failure(
        self, zt_provider: ZoneTurfProvider, mocker, fetch_method_name
    ):
        """Ensures fetch methods return None if the entity ID cannot be resolved."""
        # 1. Setup mocks
        mocker.patch.object(zt_provider, '_resolve_entity_id', return_value=None)
        mock_http_get = mocker.patch.object(zt_provider.client, 'get')

        # 2. Get the actual method from the provider instance
        fetch_method = getattr(zt_provider, fetch_method_name)

        # 3. Call the method
        result = fetch_method("Unknown Entity")

        # 4. Assertions
        assert result is None
        # Ensure no HTTP call was made if ID resolution failed
        mock_http_get.assert_not_called()

    @pytest.mark.parametrize(
        "mock_html, expected_stats",
        [
            # Case 1: Zero starters
            (
                """
                <html><body><h2>Statistiques 2025 de E. Raffin</h2>
                <table>
                    <tr><td>Courses</td><td> 0 </td></tr>
                    <tr><td>Victoires</td><td> 0 </td></tr>
                    <tr><td>Placés</td><td> 0 </td></tr>
                </table></body></html>
                """,
                {"starters": 0, "wins": 0, "places": 0, "win_rate": 0.0, "place_rate": 0.0},
            ),
            # Case 2: Missing stats table
            (
                "<html><body><h2>Statistiques 2025 de E. Raffin</h2></body></html>",
                None,
            ),
            # Case 3: Missing header
            (
                "<html><body><table><tr><td>Courses</td><td> 10 </td></tr></table></body></html>",
                None,
            ),
        ],
    )
    def test_fetch_jockey_stats_parsing_edge_cases(
        self, zt_provider: ZoneTurfProvider, mocker, mock_html, expected_stats
    ):
        """Tests edge cases for jockey stats parsing like zero starters or missing elements."""
        mock_response = mocker.Mock()
        mock_response.text = mock_html
        mock_response.raise_for_status = mocker.Mock()

        mocker.patch.object(zt_provider.client, 'get', return_value=mock_response)
        mocker.patch.object(zt_provider, '_resolve_entity_id', return_value="2957")

        stats = zt_provider.fetch_jockey_stats("A Jockey")

        if expected_stats is None:
            assert stats is None
        else:
            assert stats is not None
            assert stats.starters == expected_stats["starters"]
            assert stats.wins == expected_stats["wins"]
            assert stats.places == expected_stats["places"]
            assert stats.win_rate == expected_stats["win_rate"]
            assert stats.place_rate == expected_stats["place_rate"]

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

    def test_get_id_from_cache_handles_exception(
        self, zt_provider: ZoneTurfProvider, mocker, caplog
    ):
        """Ensures that exceptions during cache read are handled gracefully."""
        mocker.patch.object(
            firestore_client, 'get_document', side_effect=Exception("Firestore unavailable")
        )

        result = zt_provider._get_id_from_cache("horse", "My Horse")

        assert result is None
        assert "Failed to read from cache" in caplog.text

    def test_set_id_to_cache_handles_exception(self, zt_provider: ZoneTurfProvider, mocker, caplog):
        """Ensures that exceptions during cache write are handled gracefully."""
        mocker.patch.object(
            firestore_client, 'set_document', side_effect=Exception("Firestore unavailable")
        )

        # This function should not raise an exception
        zt_provider._set_id_to_cache("horse", "My Horse", "12345")

        assert "Failed to write to cache" in caplog.text

    def test_get_id_from_cache_expired(self, zt_provider: ZoneTurfProvider, mocker):
        """Ensures that an expired cache entry is ignored."""
        expired_time = datetime.now(timezone.utc) - timedelta(days=90)
        mock_doc = {"entity_id": "54321", "cached_at": expired_time}
        mocker.patch.object(firestore_client, 'get_document', return_value=mock_doc)

        # Set TTL to 30 days for this test
        zt_provider.cache_ttl = timedelta(days=30)

        result = zt_provider._get_id_from_cache("horse", "My Horse")

        assert result is None
        firestore_client.get_document.assert_called_once()

    def test_resolve_entity_id_empty_name(self, zt_provider: ZoneTurfProvider, mocker):
        """Tests that an empty name is rejected early."""
        mock_get_cache = mocker.patch.object(zt_provider, '_get_id_from_cache')

        result = zt_provider._resolve_entity_id("horse", "")

        assert result is None
        mock_get_cache.assert_not_called()

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
        # 1. Setup mocks
        mocker.patch.object(zt_provider, '_get_id_from_cache', return_value=None)
        mock_set_to_cache = mocker.patch.object(zt_provider, '_set_id_to_cache')

        fixture_path = Path(__file__).parent / "fixtures" / "zoneturf_index_page.html"
        mock_html = fixture_path.read_text(encoding="utf-8")

        mock_response = mocker.Mock()
        mock_response.text = mock_html
        mock_response.raise_for_status = mocker.Mock()
        mock_http_get = mocker.patch.object(zt_provider.client, 'get', return_value=mock_response)

        # 2. Call the function
        entity_id = zt_provider._resolve_entity_id("horse", "JULLOU")

        # 3. Assertions
        assert entity_id == "1772764"
        zt_provider._get_id_from_cache.assert_called_once_with("horse", "JULLOU")
        mock_http_get.assert_called_once_with("/cheval/lettre-j.html?p=1")
        mock_set_to_cache.assert_called_once_with("horse", "JULLOU", "1772764")

    def test_resolve_entity_id_handles_http_error(
        self, zt_provider: ZoneTurfProvider, mocker, caplog
    ):
        """Tests that a non-404 HTTP error during scraping is handled."""
        mocker.patch.object(zt_provider, '_get_id_from_cache', return_value=None)

        mock_response = mocker.Mock()
        mock_response.status_code = 500
        mocker.patch.object(
            zt_provider.client,
            'get',
            side_effect=httpx.HTTPStatusError(
                "Server Error", request=mocker.Mock(), response=mock_response
            ),
        )

        result = zt_provider._resolve_entity_id("horse", "My Horse")

        assert result is None
        assert "HTTP error while resolving ID" in caplog.text

    def test_resolve_entity_id_handles_non_letter_name(self, zt_provider: ZoneTurfProvider, mocker):
        """Tests ID resolution for names that don't start with a letter."""
        mocker.patch.object(zt_provider, '_get_id_from_cache', return_value=None)

        mock_response = mocker.Mock()
        mock_response.text = "<html><body><p>No links here</p></body></html>"
        mock_response.raise_for_status = mocker.Mock()
        mock_http_get = mocker.patch.object(zt_provider.client, 'get', return_value=mock_response)

        zt_provider._resolve_entity_id("horse", "1st Horse")

        # Assert it requests the '0-9' index page
        mock_http_get.assert_called_once_with("/cheval/lettre-0-9.html?p=1")

    def test_resolve_entity_id_not_found(self, zt_provider: ZoneTurfProvider, mocker):
        """Tests the case where an entity is not found after scraping all pages."""
        mocker.patch.object(zt_provider, '_get_id_from_cache', return_value=None)

        mock_response = mocker.Mock()
        mock_response.text = "<html><body><p>No links here</p></body></html>"
        mock_response.raise_for_status = mocker.Mock()
        mocker.patch.object(zt_provider.client, 'get', return_value=mock_response)

        entity_id = zt_provider._resolve_entity_id("horse", "Unknown Horse")
        assert entity_id is None
        # Should be called once for the first page, then stop as there are no links.
        zt_provider.client.get.assert_called_once()

    def test_resolve_entity_id_pagination_limit(self, zt_provider: ZoneTurfProvider, mocker):
        """Tests that pagination stops after MAX_PAGES_TO_SCRAPE."""
        zt_provider.MAX_PAGES_TO_SCRAPE = 3  # Use a small number for testing
        mocker.patch.object(zt_provider, '_get_id_from_cache', return_value=None)

        # Mock response that always contains non-matching links
        mock_response = mocker.Mock()
        mock_response.text = '<html><body><ul class="list-chevaux"><li><a href="/cheval/other-1">Other</a></li></ul></body></html>'
        mock_response.raise_for_status = mocker.Mock()
        mock_http_get = mocker.patch.object(zt_provider.client, 'get', return_value=mock_response)

        entity_id = zt_provider._resolve_entity_id("horse", "My Horse")

        assert entity_id is None
        assert mock_http_get.call_count == zt_provider.MAX_PAGES_TO_SCRAPE
