"""Tests for start time extraction from ZEturf HTML fragments."""

from __future__ import annotations

import textwrap

from scripts import online_fetch_zeturf as zeturf


def test_extract_start_time_from_time_tag() -> None:
    html = """
    <html>
      <body>
        <div class="race">
          <time datetime="2024-09-25T14:05:00+02:00">14h05</time>
        </div>
      </body>
    </html>
    """
    assert zeturf._extract_start_time(textwrap.dedent(html)) == "14:05"


def test_extract_start_time_from_json_ld_script() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {"@type": "SportsEvent", "startDate": "2024-09-25T15:10:00+02:00"}
        </script>
      </head>
    </html>
    """
    assert zeturf._extract_start_time(textwrap.dedent(html)) == "15:10"


def test_extract_start_time_from_text_fallback() -> None:
    html = """
    <div class="infos-course">
      Départ prévu à 21 h
    </div>
    """
    assert zeturf._extract_start_time(textwrap.dedent(html)) == "21:00"


def test_extract_start_time_returns_none_when_missing() -> None:
    assert zeturf._extract_start_time("<html><body>Aucune heure ici</body></html>") is None


def test_extract_start_time_from_accessibility_label() -> None:
    html = """
    <button class="cta" aria-label="Départ 18h30"></button>
    """
    assert zeturf._extract_start_time(textwrap.dedent(html)) == "18:30"


def test_extract_start_time_from_data_attribute() -> None:
    html = """
    <div class="race" data-start-time="1305" data-time="13h05"></div>
    """
    assert zeturf._extract_start_time(textwrap.dedent(html)) == "13:05"
