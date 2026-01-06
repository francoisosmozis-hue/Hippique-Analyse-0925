import pytest
from hippique_orchestrator import analysis_utils


@pytest.mark.parametrize(
    "musique_str, expected",
    [
        (
            "1p2p(23)3p4hDAI",
            {
                "raw": "1p2p(23)3p4hDAI",
                "placings": ["1", "2", "3", "4", "D", "A", "I"],
                "top3_count": 3,
                "top5_count": 4,
                "disqualified_count": 1,
                "recent_performances_numeric": [1, 2, 3, 4],
                "is_dai": True,
                "regularity_score": 2.5,
                "last_race_placing": 1,
                "num_races_in_musique": 7,
            },
        ),
        (
            "0a9a8a",
            {
                "raw": "0a9a8a",
                "placings": ["0", "9", "8"],
                "top3_count": 0,
                "top5_count": 0,
                "disqualified_count": 0,
                "recent_performances_numeric": [0, 9, 8],
                "is_dai": False,
                "regularity_score": 9.0,
                "last_race_placing": 0,
                "num_races_in_musique": 3,
            },
        ),
        (
            None,
            {
                "raw": None,
                "placings": [],
                "top3_count": 0,
                "top5_count": 0,
                "disqualified_count": 0,
                "recent_performances_numeric": [],
                "is_dai": False,
                "regularity_score": 10.0,
                "last_race_placing": None,
                "num_races_in_musique": 0,
            },
        ),
        (
            "   ",
            {
                "raw": "   ",
                "placings": [],
                "top3_count": 0,
                "top5_count": 0,
                "disqualified_count": 0,
                "recent_performances_numeric": [],
                "is_dai": False,
                "regularity_score": 10.0,
                "last_race_placing": None,
                "num_races_in_musique": 0,
            },
        ),
    ],
)
def test_parse_musique(musique_str, expected):
    """Tests the parse_musique function with various inputs."""
    parsed = analysis_utils.parse_musique(musique_str)
    assert parsed == expected


@pytest.mark.parametrize(
    "musique_data, expected_volatility",
    [
        ({"is_dai": True, "num_races_in_musique": 3}, "VOLATIL"),
        ({"disqualified_count": 1, "num_races_in_musique": 3}, "VOLATIL"),
        (
            {
                "recent_performances_numeric": [1, 10, 2, 11, 3],
                "num_races_in_musique": 5,
                "regularity_score": 5.4,
            },
            "VOLATIL",
        ),
        (
            {
                "regularity_score": 2.0,
                "top3_count": 4,
                "num_races_in_musique": 5,
            },
            "SÛR",
        ),
        (
            {
                "regularity_score": 7.0,
                "num_races_in_musique": 5,
            },
            "VOLATIL",
        ),
        ({}, "NEUTRE"),
    ],
)
def test_calculate_volatility(musique_data, expected_volatility):
    """Tests the calculate_volatility function."""
    assert analysis_utils.calculate_volatility(musique_data) == expected_volatility


@pytest.mark.parametrize(
    "odds_list, expected_probs, expected_overround",
    [
        ([2.0, 3.0, 6.0], [0.5, 0.3333, 0.1667], 1.0),
        ([], [], 0.0),
        ([4.0], [1.0], 0.25),
        ([1.0, 2.0], [0.0, 1.0], 0.5),  # Invalid odds are handled
    ],
)
def test_convert_odds_to_implied_probabilities(odds_list, expected_probs, expected_overround):
    """Tests the convert_odds_to_implied_probabilities function."""
    probs, overround = analysis_utils.convert_odds_to_implied_probabilities(odds_list)
    assert overround == expected_overround
    for p, e_p in zip(probs, expected_probs, strict=True):
        assert round(p, 4) == e_p


@pytest.mark.parametrize(
    "runner_data, expected",
    [
        ({"odds_place": 10.0, "parsed_musique": {"recent_performances_numeric": [1, 2, 3]}}, True),
        ({"odds_place": 7.0, "parsed_musique": {"recent_performances_numeric": [1, 2, 3]}}, False),
        ({"odds_place": 10.0, "parsed_musique": {"recent_performances_numeric": [4, 2, 3]}}, False),
        ({"odds_place": 10.0, "parsed_musique": {"recent_performances_numeric": [1]}}, False),
        ({}, False),
    ],
)
def test_identify_outsider_reparable(runner_data, expected):
    """Tests the identify_outsider_reparable function."""
    assert analysis_utils.identify_outsider_reparable(runner_data) == expected


@pytest.mark.parametrize(
    "runner_data, expected",
    [
        (
            {
                "p_place": 0.05,
                "parsed_musique": {"regularity_score": 3.0, "num_races_in_musique": 3},
            },
            True,
        ),
        (
            {
                "p_place": 0.2,
                "parsed_musique": {"regularity_score": 3.0, "num_races_in_musique": 3},
            },
            False,
        ),
        (
            {
                "p_place": 0.05,
                "parsed_musique": {"regularity_score": 5.0, "num_races_in_musique": 3},
            },
            False,
        ),
        (
            {
                "p_place": 0.05,
                "parsed_musique": {"regularity_score": 3.0, "num_races_in_musique": 2},
            },
            False,
        ),
        ({}, False),
    ],
)
def test_identify_profil_oublie(runner_data, expected):
    """Tests the identify_profil_oublie function."""
    assert analysis_utils.identify_profil_oublie(runner_data) == expected


@pytest.mark.parametrize(
    "musique_data, expected_score",
    [
        (
            {"top3_count": 2, "top5_count": 3, "regularity_score": 3.0, "num_races_in_musique": 5},
            pytest.approx(4.333333),
        ),
        (
            {"is_dai": True, "top3_count": 1, "regularity_score": 5.0, "num_races_in_musique": 5},
            pytest.approx(-1.333333),
        ),
        ({}, 0.0),
    ],
)
def test_score_musique_form(musique_data, expected_score):
    """Tests the score_musique_form function."""
    assert analysis_utils.score_musique_form(musique_data) == expected_score
