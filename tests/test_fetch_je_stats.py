import pytest
from pathlib import Path
import json
import csv
from src import fetch_je_stats

@pytest.fixture
def horse_page_html():
    """Returns the content of the sample Geny horse page HTML file."""
    path = Path(__file__).parent / "fixtures" / "geny_horse_page.html"
    return path.read_text(encoding="utf-8")

@pytest.fixture
def profile_page_html():
    """Returns the content of the sample Geny profile page HTML file."""
    path = Path(__file__).parent / "fixtures" / "geny_profile_page.html"
    return path.read_text(encoding="utf-8")

@pytest.fixture
def search_page_html():
    """Returns the content of the sample Geny search page HTML file."""
    path = Path(__file__).parent / "fixtures" / "geny_search_page.html"
    return path.read_text(encoding="utf-8")

@pytest.mark.parametrize(
    "value, expected",
    [
        ("  Test String  ", "teststring"),
        ("Écurie Spéciale", "ecuriespeciale"),
        ("J. VANMEERBECK", "jvanmeerbeck"),
    ],
)
def test_normalise_text(value, expected):
    fetch_je_stats._normalise_text.cache_clear()
    assert fetch_je_stats._normalise_text(value) == expected

@pytest.mark.parametrize(
    "text, expected",
    [
        ("Réussite jockey/cheval : 15%", 15.0),
        ("Ratio: 3 / 10", 30.0),
        ("Victoires : 5", 5.0),
        ("Taux de réussite : 0.25", 25.0),
        ("Just a number 42.5 here", 42.5),
        ("No number here", None),
        ("", None),
        ("Victoires=10", 10.0),
        ("12,5%", 12.5),
    ],
)
def test_parse_percentage(text, expected):
    assert fetch_je_stats._parse_percentage(text) == expected

def test_extract_links_from_horse_page(horse_page_html):
    """Tests that jockey and trainer links are extracted from a horse page."""
    links = fetch_je_stats.extract_links_from_horse_page(horse_page_html)
    
    assert "jockey" in links
    assert "trainer" in links
    assert links["jockey"] == "https://www.geny.com/jockeys/1234-j-doe.html"
    assert links["trainer"] == "https://www.geny.com/entraineurs/5678-s-smith.html"

def test_extract_rate_from_profile(profile_page_html):
    """Tests that a success rate is extracted from a profile page."""
    rate = fetch_je_stats.extract_rate_from_profile(profile_page_html)
    assert rate == 15.0

def test_discover_horse_url_by_name(mocker, search_page_html):
    """Tests that the correct horse URL is discovered from a search page."""
    mock_get = mocker.patch("src.fetch_je_stats.http_get", return_value=search_page_html)
    
    url = fetch_je_stats.discover_horse_url_by_name("Bold Eagle")
    
    assert url == "https://www.geny.com/cheval/222-bold-eagle.html"
    mock_get.assert_called_once()

def test_discover_horse_url_by_name_http_error(mocker):
    """Tests that discover_horse_url_by_name handles HTTP errors."""
    mocker.patch("src.fetch_je_stats.http_get", side_effect=RuntimeError("HTTP failed"))
    url = fetch_je_stats.discover_horse_url_by_name("Bold Eagle")
    assert url is None

def test_parse_horse_percentages_success(mocker, search_page_html, horse_page_html, profile_page_html):
    """Tests the full orchestration of parsing percentages for a horse."""
    
    def mock_fetcher(url):
        if "recherche" in url:
            return search_page_html
        if "cheval" in url:
            return horse_page_html
        if "jockeys" in url or "entraineurs" in url:
            return profile_page_html
        raise RuntimeError(f"Unexpected URL in mock_fetcher: {url}")

    j_rate, t_rate = fetch_je_stats.parse_horse_percentages("Bold Eagle", get=mock_fetcher)
    
    assert j_rate == 15.0
    assert t_rate == 15.0

def test_parse_horse_percentages_handles_failures(mocker):
    """Tests that parse_horse_percentages returns None for various failures."""
    
    mocker.patch("src.fetch_je_stats.discover_horse_url_by_name", return_value=None)
    j_rate, t_rate = fetch_je_stats.parse_horse_percentages("Unknown Horse")
    assert j_rate is None
    assert t_rate is None

    mocker.patch("src.fetch_je_stats.discover_horse_url_by_name", return_value="http://horse.url")
    mocker.patch("src.fetch_je_stats.http_get", side_effect=RuntimeError("HTTP failed"))
    j_rate, t_rate = fetch_je_stats.parse_horse_percentages("Known Horse")
    assert j_rate is None
    assert t_rate is None

def test_collect_stats_integration(mocker, tmp_path, search_page_html, horse_page_html, profile_page_html):
    """Tests the collect_stats function's orchestration."""
    h5_path = tmp_path / "h5_snapshot.json"
    h5_data = {"runners": [{"num": 1, "name": "HORSE A"}]}
    h5_path.write_text(json.dumps(h5_data))

    def mock_fetcher(url, **kwargs):
        if "recherche" in url: return search_page_html
        if "cheval" in url: return horse_page_html
        if "jockey" in url or "entraineur" in url: return profile_page_html
        return ""
    
    mocker.patch("src.fetch_je_stats.http_get", side_effect=mock_fetcher)
    mocker.patch("time.sleep")

    json_output_path_str = fetch_je_stats.collect_stats(h5=str(h5_path))
    
    json_output_path = Path(json_output_path_str)
    stats_data = json.loads(json_output_path.read_text())
    
    assert stats_data["coverage"] == 100.0
    rows = stats_data["rows"]
    assert len(rows) == 1
    assert rows[0]["j_rate"] == "15.00"
    assert rows[0]["e_rate"] == "15.00"
    
    csv_output_path = tmp_path / "h5_snapshot_je.csv"
    assert csv_output_path.exists()
    with csv_output_path.open("r") as f:
        reader = csv.DictReader(f)
        csv_rows = list(reader)
        assert len(csv_rows) == 1
        assert csv_rows[0]["j_rate"] == "15.00"