"""Tests for start time extraction from Boturfers HTML fragments."""

from __future__ import annotations

import textwrap

import pytest
from bs4 import BeautifulSoup

from hippique_orchestrator.scrapers.boturfers import BoturfersFetcher


@pytest.mark.parametrize(
    "time_html, expected_time",
    [
        ("<td class='hour'>14h05</td>", "14:05"),
        ("<td class='hour'> 9h30 </td>", "09:30"),
        ("<td class='hour'>21:45</td>", "21:45"),
        ("<td class='hour'>08:15</td>", "08:15"),
        ("<td class='hour'>12h00</td>", "12:00"),
        ("<td class='hour'>No time here</td>", None),
        ("<td></td>", None),
    ],
)
def test_extract_start_time_from_programme_row(time_html: str, expected_time: str | None) -> None:
    """The `_parse_programme` method should correctly extract start times."""
    html_row = f"""
    <tr>
      <th class="num">
        <span class="rxcx">R1C1</span>
      </th>
      {time_html}
      <td class="crs">
        <a class="link" href="/fr/course/12345">Prix d'Exemple</a>
      </td>
      <td class="nb">16</td>
    </tr>
    """
    html = f"""
    <div class="tab-content">
      <div class="tab-pane active" id="r1">
        <h3 class="reu-title">R1 - VINCENNES</h3>
        <table class="table data prgm">
          <tbody>
            {html_row}
          </tbody>
        </table>
      </div>
    </div>
    """
    soup = BeautifulSoup(textwrap.dedent(html), "lxml")

    fetcher = BoturfersFetcher("https://www.boturfers.fr/programme-pmu-du-jour")
    fetcher.soup = soup

    races = fetcher._parse_programme()

    assert len(races) == 1
    assert races[0]["start_time"] == expected_time
