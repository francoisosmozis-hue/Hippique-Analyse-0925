from __future__ import annotations

import pytest

from fetch_je_stats import (
    discover_horse_url_by_name,
    extract_links_from_horse_page,
    extract_rate_from_profile,
    parse_horse_percentages,
)


def test_extract_links_from_horse_page_identifies_profiles() -> None:
    html = """
    <html>
      <body>
        <div class="links">
          <a href="/professionnels/jockeys/john-doe">Jockey : John Doe</a>
          <a href="https://www.geny.com/professionnels/entraineurs/jane-smith">
            Entraîneur Jane Smith
          </a>
        </div>
      </body>
    </html>
    """

    links = extract_links_from_horse_page(html)

    assert links["jockey"] == "https://www.geny.com/professionnels/jockeys/john-doe"
    assert (
        links["trainer"]
        == "https://www.geny.com/professionnels/entraineurs/jane-smith"
    )


@pytest.mark.parametrize(
    "html,expected",
    [
        ("<div>Taux de réussite : 43 %</div>", pytest.approx(43.0)),
        ("<span>Victoires: 5/20</span>", pytest.approx(25.0)),
        ("<p>ratio 0.4</p>", pytest.approx(40.0)),
    ],
)
def test_extract_rate_from_profile_parses_common_formats(html: str, expected: float) -> None:
    assert extract_rate_from_profile(html) == expected


def test_discover_horse_url_by_name_picks_best_match() -> None:
    search_html = """
    <html>
      <body>
        <a href="/chevaux/alpha-horse">Alpha Horse</a>
        <a href="/chevaux/alphabet">Alphabet</a>
      </body>
    </html>
    """

    def fake_get(url: str) -> str:
        assert "recherche" in url
        return search_html

    url = discover_horse_url_by_name("Alpha Horse", get=fake_get)

    assert url == "https://www.geny.com/chevaux/alpha-horse"


def test_parse_horse_percentages_fetches_profiles() -> None:
    search_html = """
    <a href="/chevaux/alpha">Alpha</a>
    """
    horse_html = """
    <div>
      <a href="/professionnels/jockeys/john">Jockey John</a>
      <a href="/professionnels/entraineurs/jane">Entraîneur Jane</a>
    </div>
    """
    jockey_html = "<div>Taux de réussite : 52 %</div>"
    trainer_html = "<div>Réussite 3/8</div>"

    responses = {
        "https://www.geny.com/recherche?query=Alpha": search_html,
        "https://www.geny.com/chevaux/alpha": horse_html,
        "https://www.geny.com/professionnels/jockeys/john": jockey_html,
        "https://www.geny.com/professionnels/entraineurs/jane": trainer_html,
    }

    def fake_get(url: str) -> str:
        return responses[url]

    jockey_rate, trainer_rate = parse_horse_percentages("Alpha", get=fake_get)

    assert jockey_rate == pytest.approx(52.0)
    assert trainer_rate == pytest.approx(37.5)
