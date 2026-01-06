from datetime import datetime
from unittest.mock import MagicMock, patch

import httpx
import pytest

from hippique_orchestrator.scrapers import geny


# Fixture to read HTML content
@pytest.fixture
def geny_programme_html_success():
    with open("tests/fixtures/geny_programme.html") as f:
        return f.read()


@pytest.fixture
def mock_httpx_get():
    with patch("httpx.get") as mock_get:
        yield mock_get


@pytest.fixture
def mock_datetime_today():
    with patch("hippique_orchestrator.scrapers.geny.datetime") as mock_dt:
        mock_dt.today.return_value = datetime(2025, 12, 30)
        mock_dt.today.strftime.side_effect = lambda x: datetime(2025, 12, 30).strftime(x)
        # Ensure datetime.today() returns the mocked date directly when called
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        yield mock_dt


# Test for _slugify helper
@pytest.mark.parametrize(
    "input_str, expected_slug",
    [
        ("Paris-Vincennes (FR)", "paris-vincennes-fr"),
        ("Hippodrome de la Côte d'Azur", "hippodrome-de-la-cote-d-azur"),
        ("Saint-Cloud", "saint-cloud"),
        ("123 Test", "123-test"),
        ("", ""),
        ("   ", ""),
        ("  _!@# my string 123", "my-string-123"),
    ],
)
def test_slugify(input_str, expected_slug):
    assert geny._slugify(input_str) == expected_slug


# Nominal case test
def test_fetch_geny_programme_success(
    geny_programme_html_success, mock_httpx_get, mock_datetime_today
):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.text = geny_programme_html_success
    mock_response.raise_for_status.return_value = None
    mock_httpx_get.return_value = mock_response

    result = geny.fetch_geny_programme()

    expected_date_geny_url_format = "30-12-2025"  # Format used in Geny URL
    expected_date_result_format = "2025-12-30"  # Format used in result dict

    mock_httpx_get.assert_called_once_with(
        f"https://www.genybet.fr/reunions/{expected_date_geny_url_format}",
        follow_redirects=True,
        timeout=10.0,
    )
    assert result["date"] == expected_date_result_format
    assert len(result["meetings"]) == 2  # Hippodrome A and Hippodrome B

    meeting_a = next(m for m in result["meetings"] if m["hippo"] == "Hippodrome A (FR)")
    meeting_b = next(m for m in result["meetings"] if m["hippo"] == "Hippodrome B (BE)")

    assert meeting_a["r"] == "R1"
    assert meeting_a["slug"] == "hippodrome-a-fr"
    assert len(meeting_a["courses"]) == 2
    assert meeting_a["courses"][0]["c"] == "C1"
    assert meeting_a["courses"][0]["id_course"] == "12345"
    assert meeting_a["courses"][1]["c"] == "C2"
    assert meeting_a["courses"][1]["id_course"] == "98765"

    assert meeting_b["r"] == "R2"
    assert meeting_b["slug"] == "hippodrome-b-be"
    assert len(meeting_b["courses"]) == 1
    assert meeting_b["courses"][0]["c"] == "C1"
    assert meeting_b["courses"][0]["id_course"] == "67890"


def test_fetch_geny_programme_no_races_container(mock_httpx_get, mock_datetime_today, caplog):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.text = "<html><body><div id='some-other-container'></div></body></html>"
    mock_httpx_get.return_value = mock_response

    result = geny.fetch_geny_programme()

    assert result == {"date": "2025-12-30", "meetings": []}
    assert "No 'next-races-container' found on Geny page." in caplog.text


def test_fetch_geny_programme_empty_rows(mock_httpx_get, mock_datetime_today, caplog):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.text = "<div id='next-races-container'><table><tbody></tbody></table></div>"
    mock_httpx_get.return_value = mock_response

    result = geny.fetch_geny_programme()

    assert result == {"date": "2025-12-30", "meetings": []}
    assert "Discovered 0 meetings from Geny" in caplog.text


def test_fetch_geny_programme_malformed_row_elements(mock_httpx_get, mock_datetime_today, caplog):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    # Missing th.race-name
    malformed_html = """
    <div id="next-races-container">
        <table>
            <tbody>
                <tr><td><a>C1</a></td></tr>
            </tbody>
        </table>
    </div>
    """
    mock_response.text = malformed_html
    mock_httpx_get.return_value = mock_response

    result = geny.fetch_geny_programme()
    assert result == {"date": "2025-12-30", "meetings": []}
    assert "Could not find meeting element 'th.race-name' in a row. Skipping row." in caplog.text


def test_fetch_geny_programme_httpx_request_error(mock_httpx_get, mock_datetime_today, caplog):
    mock_httpx_get.side_effect = httpx.RequestError(
        "Mock request error", request=MagicMock(url="http://mock.url")
    )

    result = geny.fetch_geny_programme()

    assert result == {"date": "2025-12-30", "meetings": []}
    assert "An error occurred while requesting 'http://mock.url'" in caplog.text


def test_fetch_geny_programme_httpx_status_error(mock_httpx_get, mock_datetime_today, caplog):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 404
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Not Found", request=MagicMock(url="http://mock.url"), response=mock_response
    )
    mock_httpx_get.return_value = mock_response

    result = geny.fetch_geny_programme()

    assert result == {"date": "2025-12-30", "meetings": []}
    assert "Error response 404 while requesting 'http://mock.url'" in caplog.text


def test_fetch_geny_programme_id_course_from_href_fallback(mock_httpx_get, mock_datetime_today):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    # HTML where id attribute is missing, but href has the ID
    html_content = """
    <div id="next-races-container">
        <table>
            <tbody>
                <tr>
                    <th class="race-name">Hippodrome X</th>
                    <td><a href="/race/some-path/99999">C1</a></td>
                </tr>
            </tbody>
        </table>
    </div>
    """
    mock_response.text = html_content
    mock_httpx_get.return_value = mock_response

    result = geny.fetch_geny_programme()

    assert len(result["meetings"]) == 1
    assert result["meetings"][0]["courses"][0]["id_course"] == "99999"
