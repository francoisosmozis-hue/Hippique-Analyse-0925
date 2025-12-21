import pytest
from pytest_mock import MockerFixture
from datetime import datetime # New import


# NOTE: The client fixture is now provided by conftest.py


def test_healthz_endpoint(client):
    """Tests if the /healthz endpoint is reachable and returns OK."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_api_pronostics_no_data(client, mocker):
    """
    Tests that the /pronostics endpoint returns an OK response (but with no data)
    when no pronostics are found in Firestore for the given date.
    """
    mocker.patch("hippique_orchestrator.firestore_client.get_races_by_date_prefix", return_value=[])
    mock_date_str = "2025-12-07"

    # Test without date parameter (uses default today)
    response = client.get("/api/pronostics")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["total_races"] == 0
    assert data["pronostics"] == []
    assert "date" in data  # Ensure date used is returned

    response = client.get(f"/api/pronostics?date={mock_date_str}")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["total_races"] == 0
    assert data["pronostics"] == []
    assert data["date"] == mock_date_str


def test_api_pronostics_with_mock_data(client, mocker):
    """
    Tests that the /pronostics endpoint successfully returns data
    when a valid pronostics document is present in Firestore, matching the new API structure.
    """
    mock_date_str = "2025-12-07"

    mock_firestore_doc = {
        "id": f"{mock_date_str}_R1C1",
        "rc": "R1C1",
        "tickets_analysis": {
            "gpi_decision": "Play",
            "tickets": [{"type": "SP", "cheval": "1"}],
            "roi_global_est": 0.2,
        },
    }
    mocker.patch(
        "hippique_orchestrator.firestore_client.get_races_by_date_prefix",
        return_value=[mock_firestore_doc],
    )

    response = client.get(f"/api/pronostics?date={mock_date_str}")
    assert response.status_code == 200

    data = response.json()
    assert data["ok"] is True
    assert data["total_races"] == 1
    assert data["date"] == mock_date_str

    pronostic = data["pronostics"][0]
    assert pronostic["rc"] == "R1C1"
    assert pronostic["gpi_decision"] == "Play"
    assert len(pronostic["tickets"]) == 1
    assert pronostic["tickets"][0]["type"] == "SP"


def test_api_pronostics_handles_malformed_doc(client, mocker):
    """
    Tests that the /pronostics endpoint gracefully handles Firestore documents
    that do not contain the expected 'tickets_analysis' field.
    """
    mock_date_str = "2025-12-07"

    valid_doc = {
        "id": f"{mock_date_str}_R1C1",
        "rc": "R1C1",
        "tickets_analysis": {"gpi_decision": "Play", "tickets": [{"type": "SP", "horses": ["1"]}]},
    }
    malformed_doc = {
        "id": f"{mock_date_str}_R1C2",
        "rc": "R1C2",
        "some_other_field": {},  # Missing 'tickets_analysis'
    }
    mocker.patch(
        "hippique_orchestrator.firestore_client.get_races_by_date_prefix",
        return_value=[valid_doc, malformed_doc],
    )

    response = client.get(f"/api/pronostics?date={mock_date_str}")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["total_races"] == 1  # Only the valid doc is processed
    assert len(data["pronostics"]) == 1
    assert data["pronostics"][0]["rc"] == "R1C1"


def test_api_pronostics_aggregates_multiple_docs(client, mocker):
    """
    Tests that the /pronostics endpoint correctly aggregates multiple valid
    documents from Firestore for the same date.
    """
    mock_date_str = "2025-12-07"

    doc1 = {
        "id": f"{mock_date_str}_R1C1",
        "rc": "R1C1",
        "tickets_analysis": {"gpi_decision": "Play", "tickets": [{"type": "SP", "horses": ["1"]}]},
    }
    doc2 = {
        "id": f"{mock_date_str}_R1C2",
        "rc": "R1C2",
        "tickets_analysis": {
            "gpi_decision": "Abstain",
            "tickets": [{"type": "TRIO", "horses": ["1", "2", "3"]}],
        },
    }

    mocker.patch(
        "hippique_orchestrator.firestore_client.get_races_by_date_prefix", return_value=[doc1, doc2]
    )

    response = client.get(f"/api/pronostics?date={mock_date_str}")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["total_races"] == 2
    assert len(data["pronostics"]) == 2
    assert data["pronostics"][0]["rc"] == "R1C1"
    assert data["pronostics"][1]["rc"] == "R1C2"


def test_api_pronostics_invalid_date_format(client):
    """
    Tests that the /pronostics endpoint returns a 422 error for an invalid
    date format.
    """
    response = client.get("/api/pronostics?date=not-a-date")
    assert response.status_code == 422
    assert "invalid date format" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_tasks_bootstrap_day(client, mocker):
    mocker.patch(
        "hippique_orchestrator.plan.build_plan_async",
        return_value=[
            {
                "date": "2025-11-24",
                "r_label": "R1",
                "c_label": "C1",
                "time_local": "12:00",
                "course_url": "http://example.com/c1",
            }
        ],
    )
    mocker.patch(
        "hippique_orchestrator.scheduler.schedule_all_races",
        return_value=[
            {"race": "R1C1", "phase": "H30", "ok": True, "task_name": "task-r1c1-h30"},
            {"race": "R1C1", "phase": "H5", "ok": True, "task_name": "task-r1c1-h5"},
        ],
    )

    response = client.post("/tasks/bootstrap-day", json={"date": "2025-11-24", "mode": "tasks"})
    assert response.status_code == 202
    assert response.json()["ok"] is True
    assert "initiated in background" in response.json()["message"]


@pytest.mark.asyncio
async def test_tasks_run_phase(client, mocker):
    mocker.patch(
        "hippique_orchestrator.runner.run_course",
        return_value={"ok": True, "phase": "H30", "artifacts": ["path/to/artifact"]},
    )

    payload = {
        "course_url": "http://example.com/r1c1-course",
        "phase": "H30",
        "date": "2025-11-24",
        "trace_id": "test-trace-id",
    }
    response = client.post("/tasks/run-phase", json=payload)
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["phase"] == "H30"
    assert "artifacts" in response.json()


@pytest.mark.asyncio
async def test_analyse_gpi_v52_endpoint_success(client, mocker):
    """
    Tests the /api/analyse-gpi-v52 endpoint for a successful analysis.
    Mocks all internal dependencies to simulate the full pipeline.
    """
    mock_race_url = "https://www.boturfers.fr/course/123456-R1C2-vincennes-prix-de-tarbes/partant"
    mock_date = "2025-12-21"
    mock_budget = 5.0

    # --- Mock external data fetching and internal processing steps ---

    # 1. Mock data_source.fetch_programme
    mocker.patch(
        "hippique_orchestrator.data_source.fetch_programme",
        return_value={
            "races": [
                {
                    "rc": "R1C2",
                    "reunion": "R1",
                    "name": "Prix de Tarbes",
                    "url": mock_race_url,
                    "runners_count": 4,
                }
            ]
        },
    )

    # 2. Mock data_source.fetch_race_details
    mocker.patch(
        "hippique_orchestrator.data_source.fetch_race_details",
        return_value={
            "source": "boturfers",
            "type": "race_details",
            "url": mock_race_url,
            "scraped_at": datetime.utcnow().isoformat(),
            "race_metadata": {
                "type_course": "Attelé",
                "distance": 2100,
                "corde": "Gauche",
                "conditions": "Conditions mockées",
            },
                            "runners": [
                                {
                                    "num": "1",
                                    "nom": "Cheval A",
                                    "jockey": "Jockey A",
                                    "entraineur": "Trainer A",
                                    "odds_win": 2.5,
                                    "odds_place": 2.8, # Good odds for SP
                                    "musique": "1p(23)2p3p",
                                    "gains": 10000,
                                    "p_no_vig": 0.5, # p_no_vig will be ignored, but keep for consistency
                                },
                                {
                                    "num": "2",
                                    "nom": "Cheval B",
                                    "jockey": "Jockey B",
                                    "entraineur": "Trainer B",
                                    "odds_win": 3.0,
                                    "odds_place": 3.5, # Good odds for SP
                                    "musique": "4p1pD",
                                    "gains": 8000,
                                    "p_no_vig": 0.4, # p_no_vig will be ignored
                                },
                                {
                                    "num": "3",
                                    "nom": "Cheval C",
                                    "jockey": "Jockey C",
                                    "entraineur": "Trainer C",
                                    "odds_win": 5.0,
                                    "odds_place": 6.0, # Good odds, potentially 4-7 range target
                                    "musique": "1p1p2p",
                                    "gains": 5000,
                                    "p_no_vig": 0.25, # p_no_vig will be ignored
                                },
                                {
                                    "num": "4",
                                    "nom": "Cheval D",
                                    "jockey": "Jockey D",
                                    "entraineur": "Trainer D",
                                    "odds_win": 10.0,
                                    "odds_place": 8.0, # Outsider
                                    "musique": "5p6p7p",
                                    "gains": 3000,
                                    "p_no_vig": 0.15, # p_no_vig will be ignored
                                },
                            ],        },
    )

    # 3. Mock storage operations
    mocker.patch("hippique_orchestrator.storage.save_snapshot", return_value="gs://mock-path")
    mocker.patch("hippique_orchestrator.storage.save_snapshot_metadata")
    mocker.patch("hippique_orchestrator.storage.update_race_document")
    mocker.patch("hippique_orchestrator.storage.get_latest_snapshot_metadata", return_value=None) # No H30 for simplicity
    mocker.patch("hippique_orchestrator.storage.load_snapshot_from_gcs", return_value={}) # Return empty for H30 data
    
    # 4. Mock stats_fetcher.collect_stats
    mocker.patch(
        "hippique_orchestrator.stats_fetcher.collect_stats",
        return_value="gs://mock-stats-path",
    )
    mocker.patch(
        "hippique_orchestrator.storage.load_snapshot_from_gcs",
        side_effect=[
            {}, # For H30 snapshot load
            {"coverage": 1.0, "rows": [ # For stats snapshot
                {"num": "1", "name": "Cheval A", "j_rate": 10.0, "e_rate": 13.0, "last_3_chrono": [70.0, 71.0, 72.0]},
                {"num": "2", "name": "Cheval B", "j_rate": 15.0, "e_rate": 18.0, "last_3_chrono": [68.0, 69.0, 70.0]},
                {"num": "3", "name": "Cheval C", "j_rate": 5.0, "e_rate": 7.0, "last_3_chrono": [75.0, 76.0, 77.0]},
                {"num": "4", "name": "Cheval D", "j_rate": 12.0, "e_rate": 15.0, "last_3_chrono": [80.0, 81.0, 82.0]},
            ]}
        ]
    )


    # 5. Mock config and calibration data
    mock_gpi_config = {
        "budget": mock_budget,
        "max_vol_per_horse": 0.6,
        "roi_min_sp": 0.05, # Adjusted for a playable test
        "roi_min_global": 0.05, # Adjusted for a playable test
        "overround_max_exotics": 1.25, # Added missing key
        "overround_max": 1.25, # Add this as well, it's used directly in _generate_exotic_tickets
        "ev_min_combo": 0.01, # Adjusted for a playable test
        "payout_min_combo": 1.0, # Adjusted for a playable test
        "weights": {
            "base": {
                "je_bonus": 1.10, "je_malus": 0.90,
                "j_rate_bonus_threshold": 12.0, "e_rate_bonus_threshold": 15.0,
                "j_rate_malus_threshold": 6.0, "e_rate_malus_threshold": 8.0,
            },
            "horse_stats": {},
        },
        "adjustments": {
            "chrono": {"k_c": 0.18},
            "drift": {"k_d": 0.70},
            "volatility": {"sure_bonus": 1.05, "volatile_malus": 0.90, "musique_score_weight": 0.02},
        },
        "tickets": {
            "sp_dutching": {
                "budget_ratio": 0.6,
                "legs_min": 2,
                "odds_range": [1.1, 999], # Using general range for mock to be flexible
                "kelly_frac": 0.25,
                "legs_max": 3,
            },
            "exotics": {"type": "TRIO", "allowed": ["TRIO"]},
        },
    }
    mocker.patch("hippique_orchestrator.storage.get_gpi_config", return_value=mock_gpi_config)
    mocker.patch("hippique_orchestrator.storage.get_calibration_config", return_value={"TRIO": {"payout_factor": 1.0}}) # Mock calibration

    # 6. Mock pipeline_run.evaluate_combo (for exotic tickets)
    mocker.patch(
        "hippique_orchestrator.pipeline_run.evaluate_combo",
        return_value={"status": "ok", "roi": 0.5, "payout_expected": 20.0},
    )

    payload = {
        "race_url": mock_race_url,
        "date": mock_date,
        "budget": mock_budget,
    }

    response = client.post("/api/analyse-gpi-v52", json=payload)
    assert response.status_code == 200
    result = response.json()

    assert result["success"] is True
    assert result["analysis_result"]["gpi_decision"] == "Play"
    assert len(result["analysis_result"]["tickets"]) >= 1 # Expect at least SP Dutching

    # Assert Top 5 Pronostic
    assert "top5_pronostic" in result["analysis_result"]
    assert len(result["analysis_result"]["top5_pronostic"]) > 0
    assert result["analysis_result"]["top5_pronostic"][0]["num"] == "1" # Assuming Cheval A is top

    # Assert Market Analysis Table
    assert "market_analysis_table" in result["analysis_result"]
    assert len(result["analysis_result"]["market_analysis_table"]) == 4
    assert result["analysis_result"]["market_analysis_table"][0]["nom"] == "Cheval A"
    assert result["analysis_result"]["market_analysis_table"][0]["odds_place"] == 2.8
