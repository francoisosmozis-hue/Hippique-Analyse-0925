import json
from unittest.mock import MagicMock, patch

import pytest
from hippique_orchestrator import plan
from hippique_orchestrator.plan import Race, Meeting, build_plan_sync

# Contenu HTML brut pour simuler la réponse de fetch_geny_programme
GENY_HTML = """
{
    "meetings": [
        {
            "r": "R1", "hippo": "Vincennes", "num": 1,
            "courses": [
                {
                    "c": "C1", "id_course": "123", "partants": 14, "discipline": "Attelé",
                    "h": "13:50", "prix": "100000", "details": "Prix d'Amérique"
                }
            ]
        }
    ]
}
"""

@pytest.mark.asyncio
@pytest.mark.skip(reason="Refactored: fetch_geny_programme is obsolete.")
async def test_build_plan_async(mocker): # Use mocker instead of monkeypatch for patching functions
    """Test complete plan building with Boturfers data."""

    # Mock fetch_geny_programme
    mocker.patch(
        "hippique_orchestrator.plan.fetch_geny_programme",
        return_value=json.loads(GENY_HTML)
    )

    # Mock `get_boturfers_start_time`
    async def mock_get_start_time(course_url, session):
        return "14:30"  # Simuler un temps de départ fixe
    mocker.patch(
        "hippique_orchestrator.scrapers.boturfers.get_boturfers_start_time",
        new=mock_get_start_time
    )

    # Mock `get_boturfers_race_details`
    async def mock_get_race_details(race_url, session):
        # Simuler les détails d'une course, y compris les partants
        return {
            "partants": 16,
            "discipline": "TROT",
            "conditions": "Pour 5 ans",
            "distance": "2700m"
        }
    mocker.patch(
        "hippique_orchestrator.scrapers.boturfers.get_boturfers_race_details",
        new=mock_get_race_details
    )

    # Date pour laquelle le plan est construit
    test_date = "2025-10-26"
    result_plan = await plan.build_plan_async(date=test_date)

    assert len(result_plan) == 1
    race_obj = result_plan[0]
    assert isinstance(race_obj, Race)

    # Vérification des détails de la course
    assert race_obj.r_label == "R1"
    assert race_obj.c_label == "C1"
    assert race_obj.date == test_date
    assert race_obj.discipline == "TROT"
    assert race_obj.partants == 16  # Vérifie que les détails de Boturfers sont utilisés

    # Vérification des détails de la réunion
    meeting_obj = race_obj.meeting
    assert isinstance(meeting_obj, Meeting)
    assert meeting_obj.r_label == "R1"
    assert meeting_obj.hippodrome == "Vincennes"

    # Vérification des horaires (doit utiliser la valeur mockée de Boturfers)
    assert race_obj.time_local == "14:30"

def test_build_plan_sync_wrapper():
    """Tests that the sync wrapper correctly runs the async function."""

    # Mock la fonction async
    async def mock_async_build(date):
        return [Race(r_label="R1", c_label="C1", date=date, time_local="10:00")]

    with patch("hippique_orchestrator.plan.build_plan_async", new=mock_async_build):
        result = build_plan_sync(date="2025-01-01")
        assert len(result) == 1
        assert result[0].r_label == "R1"

def test_build_plan_sync_wrapper_raises_in_event_loop():
    """Tests that exceptions from the async function are propagated."""

    async def mock_async_build_with_error(date):
        raise ValueError("Test error from async")

    with patch("hippique_orchestrator.plan.build_plan_async", new=mock_async_build_with_error):
        with pytest.raises(ValueError, match="Test error from async"):
            build_plan_sync(date="2025-01-01")


@pytest.mark.skip(reason="Refactored: _build_plan_structure is obsolete.")
def test_build_plan_structure():
    """Tests the construction of the plan from Geny data, including deduplication."""
    geny_data = {
        "meetings": [
            {
                "r": "R1", "hippo": "Hippo1",
                "courses": [
                    {"c": "C1", "id_course": "11"},
                    {"c": "C2", "id_course": "12"},
                ]
            },
            {
                "r": "R1", "hippo": "Hippo1", # Duplicate meeting, should be handled
                "courses": [
                    {"c": "C2", "id_course": "12_dup"}, # Duplicate course, should be skipped
                ]
            }
        ]
    }
    date = "2025-01-01"

    # Directly test the internal function
    result_plan = plan._build_plan_structure(geny_data, date)

    # Should have 2 races from the first meeting, with duplicates ignored
    assert len(result_plan) == 2
    assert {r.c_label for r in result_plan} == {"C1", "C2"}
    assert result_plan[0].r_label == "R1"
    assert result_plan[0].meeting.hippodrome == "Hippo1"