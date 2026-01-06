import csv
import json
from pathlib import Path
import shlex # Moved import to top-level

import pytest
from fsspec.implementations.memory import MemoryFileSystem

from hippique_orchestrator import fetch_je_stats


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
    mock_get = mocker.patch(
        "hippique_orchestrator.fetch_je_stats.http_get", return_value=search_page_html
    )

    url = fetch_je_stats.discover_horse_url_by_name("Bold Eagle")

    assert url == "https://www.geny.com/cheval/222-bold-eagle.html"
    mock_get.assert_called_once()


def test_discover_horse_url_by_name_http_error(mocker):
    mocker.patch(
        "hippique_orchestrator.fetch_je_stats.http_get",
        side_effect=RuntimeError("HTTP failed"),
    )
    url = fetch_je_stats.discover_horse_url_by_name("Bold Eagle")
    assert url is None


def test_parse_horse_percentages_success(
    mocker, search_page_html, horse_page_html, profile_page_html
):
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

    mocker.patch(
        "hippique_orchestrator.fetch_je_stats.discover_horse_url_by_name", return_value=None
    )
    j_rate, t_rate = fetch_je_stats.parse_horse_percentages("Unknown Horse")
    assert j_rate is None
    assert t_rate is None

    mocker.patch(
        "hippique_orchestrator.fetch_je_stats.discover_horse_url_by_name",
        return_value="http://horse.url",
    )
    mocker.patch(
        "hippique_orchestrator.fetch_je_stats.http_get", side_effect=RuntimeError("HTTP failed")
    )
    j_rate, t_rate = fetch_je_stats.parse_horse_percentages("Known Horse")
    assert j_rate is None
    assert t_rate is None


@pytest.mark.parametrize(
    "h5_data, expected_coverage, expected_rows, expected_j_rate",
    [
        ({"runners": []}, 0, 0, None),
        ({"runners": [{"num": 1}]}, 0, 1, ""),
        ({"runners": [{"num": 1, "name": "Unknown Horse"}]}, 0, 1, ""),
        (
            {"runners": [{"num": 1, "name": "Partially Failing Horse"}]},
            100,  # Successful if at least one stat is fetched
            1,
            "",  # Jockey rate should be empty
        ),
    ],
)
def test_collect_stats_edge_cases(
    mocker,
    tmp_path,
    h5_data,
    expected_coverage,
    expected_rows,
    expected_j_rate,
    search_page_html,
    horse_page_html,
    profile_page_html,
):
    """Tests collect_stats with various edge cases like empty runners or partial failures."""
    mocker.patch("hippique_orchestrator.fetch_je_stats.get_gcs_manager", return_value=None)
    mocker.patch("time.sleep")

    h5_path = tmp_path / "h5_snapshot.json"
    h5_path.write_text(json.dumps(h5_data), encoding="utf-8")

    def mock_fetcher(url, **kwargs):
        if "recherche" in url:
            if "Unknown" in url:
                # Simulate horse not found
                return "<html></html>"
            return search_page_html
        if "cheval" in url:
            return horse_page_html
        if "jockey" in url and "Partially" in h5_data["runners"][0].get("name", ""):
            # Simulate jockey fetch failure
            raise RuntimeError("Jockey fetch failed")
        if "entraineur" in url:
            return profile_page_html
        return ""

    mocker.patch("hippique_orchestrator.fetch_je_stats.http_get", side_effect=mock_fetcher)

    json_output_path_str = fetch_je_stats.collect_stats(h5=str(h5_path))
    stats_data = json.loads(Path(json_output_path_str).read_text())

    assert stats_data["coverage"] == expected_coverage
    assert len(stats_data["rows"]) == expected_rows
    if expected_rows > 0 and expected_j_rate is not None:
        assert stats_data["rows"][0]["j_rate"] == expected_j_rate


def test_discover_horse_url_by_name_empty_name(mocker):
    """Tests that an empty name returns None without making a request."""
    mock_get = mocker.patch("hippique_orchestrator.fetch_je_stats.http_get")
    url = fetch_je_stats.discover_horse_url_by_name("")
    assert url is None
    mock_get.assert_not_called()


def test_extract_rate_from_profile_not_found():
    """Tests that None is returned when no rate is found in the HTML."""
    html = "<html><body>No relevant information here.</body></html>"
    rate = fetch_je_stats.extract_rate_from_profile(html)
    assert rate is None


def test_main_function_calls_collect_stats(mocker):
    """Tests that the main function parses args and calls collect_stats."""
    mock_collect = mocker.patch("hippique_orchestrator.fetch_je_stats.collect_stats")
    mocker.patch(
        "argparse.ArgumentParser.parse_args",
        return_value=mocker.MagicMock(
            h5="test.json",
            out="test.csv",
            timeout=10,
            delay=0.5,
            retries=1,
            cache=True,
            cache_dir="/cache",
            ttl_seconds=300,
            neutral_on_fail=True,
        ),
    )

    fetch_je_stats.main()

    mock_collect.assert_called_once_with(
        "test.json",
        "test.csv",
        timeout=10,
        delay=0.5,
        retries=1,
        cache=True,
        cache_dir="/cache",
        ttl_seconds=300,
        neutral_on_fail=True,
    )


def test_collect_stats_local_filesystem(
    mocker, tmp_path, search_page_html, horse_page_html, profile_page_html
):
    """Tests that collect_stats writes to the local filesystem when GCS is not used."""
    # Ensure GCS is disabled for this test
    mocker.patch("hippique_orchestrator.fetch_je_stats.get_gcs_manager", return_value=None)

    h5_path = tmp_path / "h5_snapshot.json"
    h5_data = {"runners": [{"num": 1, "name": "HORSE A"}]}
    h5_path.write_text(json.dumps(h5_data), encoding="utf-8")

    def mock_fetcher(url, **kwargs):
        if "recherche" in url:
            return search_page_html
        if "cheval" in url:
            return horse_page_html
        if "jockey" in url or "entraineur" in url:
            return profile_page_html
        return ""

    mocker.patch("hippique_orchestrator.fetch_je_stats.http_get", side_effect=mock_fetcher)
    mocker.patch("time.sleep")

    json_output_path_str = fetch_je_stats.collect_stats(h5=str(h5_path))
    
    json_output_path = Path(json_output_path_str)
    assert json_output_path.exists()
    
    with json_output_path.open("r") as f:
        stats_data = json.load(f)

    assert stats_data["coverage"] == 100.0
    assert len(stats_data["rows"]) == 1
    assert stats_data["rows"][0]["j_rate"] == "15.00"

    csv_output_path = tmp_path / "h5_snapshot_je.csv"
    assert csv_output_path.exists()
    with csv_output_path.open("r") as f:
        reader = csv.DictReader(f)
        csv_rows = list(reader)
        assert len(csv_rows) == 1
        assert csv_rows[0]["j_rate"] == "15.00"

def test_enrich_from_snapshot_calls_subprocess(mocker):
    """Tests that enrich_from_snapshot calls the correct subprocess command."""
    mock_run = mocker.patch("subprocess.run")
    snapshot_path = "/data/R1C1/h5_snapshot.json"

    result_path = fetch_je_stats.enrich_from_snapshot(snapshot_path)

    expected_out_path = str(Path(snapshot_path).parent / "h5_snapshot_je.csv")
    assert result_path == expected_out_path

    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    # Check the command passed to shlex.split

    expected_cmd = f'python -m hippique_orchestrator.fetch_je_stats --h5 "{snapshot_path}" --out "{expected_out_path}" --cache --ttl-seconds 86400'
    assert args[0] == shlex.split(expected_cmd)
    assert kwargs["check"] is True



def test_collect_stats_integration(
    mocker, tmp_path, search_page_html, horse_page_html, profile_page_html
):
    """Tests the collect_stats function's orchestration."""
    # Mock GCS manager to use an in-memory filesystem
    mem_fs = MemoryFileSystem()
    mock_gcs_manager = mocker.MagicMock()
    mock_gcs_manager.fs = mem_fs
    mock_gcs_manager.get_gcs_path.side_effect = lambda path: path
    mocker.patch(
        "hippique_orchestrator.fetch_je_stats.get_gcs_manager",
        return_value=mock_gcs_manager,
    )

    h5_path = tmp_path / "h5_snapshot.json"
    h5_data = {"runners": [{"num": 1, "name": "HORSE A"}]}
    mem_fs.pipe_file(str(h5_path), json.dumps(h5_data).encode("utf-8"))

    def mock_fetcher(url, **kwargs):
        if "recherche" in url:
            return search_page_html
        if "cheval" in url:
            return horse_page_html
        if "jockey" in url or "entraineur" in url:
            return profile_page_html
        return ""

    mocker.patch("hippique_orchestrator.fetch_je_stats.http_get", side_effect=mock_fetcher)
    mocker.patch("time.sleep")

    json_output_path_str = fetch_je_stats.collect_stats(h5=str(h5_path))

    with mem_fs.open(json_output_path_str, "r") as f:
        stats_data = json.load(f)

    assert stats_data["coverage"] == 100.0
    rows = stats_data["rows"]
    assert len(rows) == 1
    assert rows[0]["j_rate"] == "15.00"
    assert rows[0]["e_rate"] == "15.00"

    csv_output_path = str(tmp_path / "h5_snapshot_je.csv")
    assert mem_fs.exists(csv_output_path)
    with mem_fs.open(csv_output_path, "r") as f:
        reader = csv.DictReader(f)
        csv_rows = list(reader)
        assert len(csv_rows) == 1
        assert csv_rows[0]["j_rate"] == "15.00"
