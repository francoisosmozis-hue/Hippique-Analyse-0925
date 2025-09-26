import pytest

from scripts import online_fetch_zeturf as zeturf


def test_extract_start_time_from_time_tag(monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    html = """
    <html>
      <body>
        <time datetime="2023-09-25T13:45:00+00:00"></time>
      </body>
    </html>
    """
    assert zeturf._extract_start_time(html) == "13:45"


def test_extract_start_time_from_text(monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    html = """
    <div class="course-header">
      Heure de départ : <strong>14h35</strong>
    </div>
    """
    assert zeturf._extract_start_time(html) == "14:35"


def test_extract_start_time_from_plain_html(monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    html = """
    <html>
      <head>
        <title>Course</title>
      </head>
      <body>
        Départ prévu à 9h.
      </body>
    </html>
    """
    assert zeturf._extract_start_time(html) == "09:00"
