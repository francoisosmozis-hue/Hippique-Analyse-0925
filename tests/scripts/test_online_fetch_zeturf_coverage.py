# tests/scripts/test_online_fetch_zeturf_coverage.py

import pytest
from bs4 import BeautifulSoup
from hippique_orchestrator.scripts.online_fetch_zeturf import (
    _normalise_rc_tag,
    _slugify_hippodrome,
    _normalize_decimal,
    _fallback_parse_html,
)

@pytest.mark.parametrize("reunion, course, expected", [
    (1, 2, "R1C2"),
    ("R1", "C2", "R1C2"),
    ("R3", 10, "R3C10"),
    ("4", "5", "R4C5"),
])
def test_normalise_rc_tag_valid(reunion, course, expected):
    """Teste la normalisation des tags de réunion/course."""
    assert _normalise_rc_tag(reunion, course) == expected

def test_slugify_hippodrome():
    """Teste la slugification des noms d'hippodromes."""
    assert _slugify_hippodrome("CAGNES SUR MER") == "cagnes-sur-mer"
    assert _slugify_hippodrome("SAINT-CLOUD") == "saint-cloud"
    assert _slugify_hippodrome("  Deauville ") == "deauville"
    assert _slugify_hippodrome(None) is None

@pytest.mark.parametrize("value, expected", [
    ("12,5", 12.5),
    ("15.5", 15.5),
    (20, 20.0),
    ("abc", None),
    (None, None),
])
def test_normalize_decimal(value, expected):
    """Teste la conversion de valeurs en décimal."""
    assert _normalize_decimal(value) == expected

# def test_fallback_parse_html_extracts_data():

#     """

#     Teste le parsing de la fonction fallback en utilisant une fixture HTML

#     qui contient à la fois la table des partants et le script des cotes.

#     """

#     html_content = """

#     <html>

#         <body>

#             <table class="table-runners">

#                 <tbody>

#                     <tr data-runner="1">

#                         <td class="numero">1</td>

#                         <td class="cheval">

#                             <a class="horse-name">TEST HORSE</a>

#                         </td>

#                     </tr>

#                     <tr data-runner="2">

#                         <td class="numero">2</td>

#                         <td class="cheval">

#                             <a class="horse-name">ANOTHER HORSE</a>

#                         </td>

#                     </tr>

#                 </tbody>

#             </table>

#             <script>

#                 var cotesInfos = {

#                     "1": {"cote": "12,5"},

#                     "2": {"cote": "8.0"}

#                 };

#             </script>

#         </body>

#     </html>

#     """

#     # Utiliser 'lxml' et passer str(soup), comme dans les tests existants

#     soup = BeautifulSoup(html_content, "lxml")

#     data = _fallback_parse_html(str(soup))



#     assert isinstance(data, dict)

#     assert "runners" in data

#     runners = data["runners"]

#     assert isinstance(runners, list)

#     assert len(runners) == 2

    

#     # Vérification du premier partant

#     runner1 = runners[0]

#     assert runner1.get("num") == "1"

#     assert runner1.get("name") == "TEST HORSE"

#     assert runner1.get("odds") == 12.5


