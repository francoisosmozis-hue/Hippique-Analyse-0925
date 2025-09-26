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


def test_extract_start_time_from_additional_data_attribute() -> None:
    html = """
    <section class="race-card" data-starts-at="2024-09-25T12:15:00+02:00"></section>
    """
    assert zeturf._extract_start_time(textwrap.dedent(html)) == "12:15"


def test_extract_start_time_handles_minutes_suffix() -> None:
    html = """
    <div class="race">Départ 21h05mn</div>
    """
    assert zeturf._extract_start_time(textwrap.dedent(html)) == "21:05"


def test_extract_start_time_from_meta_tag() -> None:
    html = """
    <html>
      <head>
        <meta property="og:race:start" content="08:30" />
      </head>
    </html>
    """
    assert zeturf._extract_start_time(textwrap.dedent(html)) == "08:30"


def test_extract_start_time_from_start_time_field() -> None:
    html = """
    <html>
      <body>
        <script type="application/ld+json">
          {"startTime": "2024-09-25T10:05:00+02:00"}
        </script>
      </body>
    </html>
    """
    assert zeturf._extract_start_time(textwrap.dedent(html)) == "10:05"


def test_extract_start_time_from_jsonld_graph() -> None:
    """Nested JSON-LD structures should still expose the start time."""

    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@graph": [
            {"@type": "SportsEvent", "startDate": "2024-09-25T19:20:00+02:00"},
            {"@type": "Thing", "name": "Placeholder"}
          ]
        }
        </script>
      </head>
    </html>
    """

    assert zeturf._extract_start_time(textwrap.dedent(html)) == "19:20"


def test_extract_start_time_uses_html_regex_fallback() -> None:
    """A plain text mention without tags should still be detected."""

    html = """
    <div class="course-infos">
      Prochain départ annoncé à 9H35, restez connectés !
    </div>
    """

    assert zeturf._extract_start_time(textwrap.dedent(html)) == "09:35"
