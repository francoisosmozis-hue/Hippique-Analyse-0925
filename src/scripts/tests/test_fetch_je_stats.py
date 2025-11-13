import pytest
from bs4 import BeautifulSoup
from scripts.fetch_je_stats import (
    RunnerIndex,
    RunnerStat,
    _extract_percentage_from_node,
    _parse_percentage,
    extract_stats_from_json,
    extract_stats_from_table,
    map_stats_to_ids,
)


def test_parse_percentage_handles_common_formats():
    assert _parse_percentage("Jean (12 % de victoires)") == pytest.approx(12.0)
    assert _parse_percentage("3/10") == pytest.approx(30.0)
    assert _parse_percentage("Victoires: 5") == pytest.approx(5.0)
    assert _parse_percentage("Sans info") is None


def test_extract_stats_from_table_parses_rows():
    html = """
    <table>
      <tr><th>No</th><th>Cheval</th><th>Jockey</th><th>Entraîneur</th></tr>
      <tr>
        <td>01</td>
        <td>Alpha</td>
        <td>Dupont (18 %)</td>
        <td>Martin (4/20)</td>
      </tr>
      <tr>
        <td>2</td>
        <td>Bravo</td>
        <td>Claire (victoires: 5)</td>
        <td>Test</td>
      </tr>
    </table>
    """
    soup = BeautifulSoup(html, "html.parser")
    stats = extract_stats_from_table(soup)
    assert len(stats) == 2
    first = stats[0]
    assert first.num == "1"
    assert first.name == "Alpha"
    assert first.j_win == pytest.approx(18.0)
    assert first.e_win == pytest.approx(20.0)

    second = stats[1]
    assert second.num == "2"
    assert second.j_win == pytest.approx(5.0)
    assert second.e_win is None


def test_extract_stats_from_json_handles_embedded_blob():
    html = """
    <html><head><script>
    window.__NUXT__={"data":[{"horse":{"name":"Charlie","number":3},
    "jockey":{"stats":{"victoryRate":42}},
    "trainer":{"ratio":0.25}}]};
    </script></head></html>
    """
    stats = extract_stats_from_json(html)
    assert len(stats) == 1
    stat = stats[0]
    assert stat.name == "Charlie"
    assert stat.num == "3"
    assert stat.j_win == pytest.approx(42.0)
    assert stat.e_win == pytest.approx(25.0)


def test_extract_percentage_from_node_prefers_ratio():
    node = {"ratio": 0.4}
    assert _extract_percentage_from_node(node) == pytest.approx(40.0)


@pytest.mark.parametrize(
    "stat,expected",
    [
        (RunnerStat(num="1", name="Alpha", j_win=10.0, e_win=20.0), "101"),
        (RunnerStat(num="", name="Bravo", j_win=15.0, e_win=None), "202"),
    ],
)
def test_map_stats_to_ids_uses_number_and_name(stat, expected):
    index = RunnerIndex([
        {"id": 101, "num": 1, "name": "Alpha"},
        {"id": 202, "num": 2, "name": "Bravo"},
    ])
    coverage, mapped, unmatched = map_stats_to_ids([stat], index)
    assert expected in mapped
    assert coverage == pytest.approx(50.0)
    assert not unmatched


def test_map_stats_to_ids_skips_entries_without_stats():
    index = RunnerIndex([
        {"id": 1, "num": 1, "name": "Alpha"},
        {"id": 2, "num": 2, "name": "Bravo"},
    ])
    stats = [RunnerStat(num="1", name="Alpha", j_win=None, e_win=None)]
    coverage, mapped, unmatched = map_stats_to_ids(stats, index)
    assert mapped == {}
    assert coverage == 0.0
    assert unmatched == stats
