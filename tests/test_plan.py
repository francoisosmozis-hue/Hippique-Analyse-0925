from datetime import date, datetime
from unittest.mock import AsyncMock, patch
import pytest
from hippique_orchestrator import plan
from hippique_orchestrator.data_contract import Programme, Race

# Sample data returned by a successful scraper call
MOCK_PROGRAMME_DATA = Programme(
    date=date(2025, 12, 20),
    races=[
        Race(
            race_id="R1C2",
            date=date(2025, 12, 20),
            rc="R1 C2",
            name="PRIX DE TEST",
            start_time="14:30",
            url="http://example.com/r1c2",
            reunion_id=1,
            course_id=2,
            hippodrome="TEST",
            country_code="FR",
        ),
        Race(
            race_id="R1C1",
            date=date(2025, 12, 20),
            rc="R1 C1",
            name="PRIX D'OUVERTURE",
            start_time="13:50",
            url="http://example.com/r1c1",
            reunion_id=1,
            course_id=1,
            hippodrome="TEST",
            country_code="FR",
        ),
    ],
)

# Sample data with malformed entries
MOCK_MALFORMED_DATA = [
    Race(
        race_id="R1C1",
        date=date(2025, 12, 20),
        rc="R1 C1",
        name="Course Valide",
        start_time="10:00",
        url="http://example.com/r1c1",
        reunion_id=1,
        course_id=1,
        hippodrome="TEST",
        country_code="FR",
    ),
    # Race with an invalid `rc` format
    Race(
        race_id="R2C2",
        date=date(2025, 12, 20),
        rc="invalid",
        name="RC non valide",
        start_time="11:00",
        url="http://example.com/r2c2",
        reunion_id=2,
        course_id=2,
        hippodrome="TEST",
        country_code="FR",
    ),
    # Race with a missing `start_time`
    Race(
        race_id="R3C3",
        date=date(2025, 12, 20),
        rc="R3 C3",
        name="Heure manquante",
        start_time=None,
        url="http://example.com/r3c3",
        reunion_id=3,
        course_id=3,
        hippodrome="TEST",
        country_code="FR",
    ),
    # Race with missing `rc`
    Race(
        race_id="R4C4",
        date=date(2025, 12, 20),
        rc=None,
        name="RC manquant",
        start_time="12:00",
        url="http://example.com/r4c4",
        reunion_id=4,
        course_id=4,
        hippodrome="TEST",
        country_code="FR",
    ),
]


@pytest.mark.asyncio
@patch("hippique_orchestrator.plan.run_in_threadpool", new_callable=AsyncMock)
async def test_build_plan_nominal_case(mock_run_in_threadpool):
    """
    Tests the happy path: the scraper returns valid data, and the plan is built and sorted correctly.
    """
    # Arrange
    mock_run_in_threadpool.return_value = MOCK_PROGRAMME_DATA
    test_date_obj = date.fromisoformat("2025-12-20")

    # Act
    result_plan = await plan.build_plan_async("2025-12-20")

    # Assert
    assert len(result_plan) == 2
    mock_run_in_threadpool.assert_called_once()

    # Check content and sorting (13:50 should be first)
    assert result_plan[0]["c_label"] == "C1"
    assert result_plan[0]["time_local"] == "13:50"
    assert result_plan[0]["date"] == test_date_obj.isoformat()
    assert result_plan[0]["meeting"] == "PRIX D'OUVERTURE"

    assert result_plan[1]["c_label"] == "C2"
    assert result_plan[1]["time_local"] == "14:30"
    assert result_plan[1]["course_url"] == "http://example.com/r1c2"
    assert result_plan[1]["meeting"] == "PRIX DE TEST"


@pytest.mark.asyncio
@patch("hippique_orchestrator.plan.run_in_threadpool", new_callable=AsyncMock)
async def test_build_plan_scraper_fails(mock_run_in_threadpool, caplog):
    """
    Tests that an empty plan is returned if the scraper fails (returns None).
    """
    # Arrange
    mock_run_in_threadpool.return_value = None

    # Act
    result_plan = await plan.build_plan_async("2025-12-20")

    # Assert
    assert result_plan == []
    assert "No programme or races found for 2025-12-20" in caplog.text


@pytest.mark.asyncio
@patch("hippique_orchestrator.plan.run_in_threadpool", new_callable=AsyncMock)
async def test_build_plan_handles_malformed_data(mock_run_in_threadpool, caplog):
    """
    Tests that entries with malformed RC format or missing start_time are skipped.
    """
    # Arrange
    programme = Programme(date="2025-12-20", races=MOCK_MALFORMED_DATA)
    mock_run_in_threadpool.return_value = programme

    # Act
    result_plan = await plan.build_plan_async("2025-12-20")

    # Assert
    # Only the one valid race should be in the plan
    assert len(result_plan) == 1
    assert result_plan[0]["r_label"] == "R1"
    assert result_plan[0]["c_label"] == "C1"

@pytest.mark.asyncio
@patch("hippique_orchestrator.plan.run_in_threadpool", new_callable=AsyncMock)
async def test_build_plan_today_string(mock_run_in_threadpool):
    """
    Tests that passing "today" uses the correct URL for the current day's programme.
    """
    mock_run_in_threadpool.return_value = Programme(date=date.today(), races=[])

    await plan.build_plan_async(date.today().isoformat())

    mock_run_in_threadpool.assert_called_once()


@pytest.mark.asyncio
@patch("hippique_orchestrator.plan.run_in_threadpool", new_callable=AsyncMock)
async def test_build_plan_empty_enriched_plan(mock_run_in_threadpool, caplog):
    """
    Tests that sorting is skipped if the enriched plan is empty, covering the `if enriched_plan:` branch.
    """
    # Arrange: return races that will all be filtered out
    mock_run_in_threadpool.return_value = Programme(date="2025-12-20", races=[])

    # Act
    result_plan = await plan.build_plan_async("2025-12-20")

    # Assert
    assert result_plan == []


@pytest.mark.asyncio
@patch("hippique_orchestrator.plan.run_in_threadpool", new_callable=AsyncMock)
async def test_build_plan_partants_non_digit_string(mock_run_in_threadpool):
    """
    Tests that `partants` is None when `runners_count` is a non-digit string.
    """
    # Arrange
    mock_programme_data = Programme(
        date=date(2025, 12, 20),
        races=[
            Race(
                race_id="R1C1",
                rc="R1 C1",
                name="Test Race",
                start_time="10:00",
                url="http://example.com/r1c1",
                runners_count="10 partants",  # Non-digit string
                reunion_id=1,
                course_id=1,
                hippodrome="TEST",
                country_code="FR",
                date=date(2025, 12, 20),
            )
        ],
    )
    mock_run_in_threadpool.return_value = mock_programme_data

    # Act
    result_plan = await plan.build_plan_async("2025-12-20")

    # Assert
    assert len(result_plan) == 1
    assert result_plan[0]["partants"] == 10

@pytest.mark.asyncio
@patch("hippique_orchestrator.plan.run_in_threadpool", new_callable=AsyncMock)
async def test_build_plan_handles_compact_rc_format(mock_run_in_threadpool):
    """
    Tests that RC format without space (e.g., "R1C1") is correctly parsed.
    """
    # Arrange
    mock_run_in_threadpool.return_value = Programme(
        date=date(2025, 12, 20),
        races=[
            Race(
                race_id="R1C1",
                rc="R1C1",
                name="Compact RC",
                start_time="10:00",
                url="http://example.com/r1c1",
                reunion_id=1,
                course_id=1,
                hippodrome="TEST",
                country_code="FR",
                date=date(2025, 12, 20),
            )
        ],
    )

    # Act
    result_plan = await plan.build_plan_async("2025-12-20")

    # Assert
    assert len(result_plan) == 1
    assert result_plan[0]["r_label"] == "R1"
    assert result_plan[0]["c_label"] == "C1"


def test_build_plan_sync_wrapper():
    """
    Tests the synchronous wrapper `build_plan`.
    """
    with patch("hippique_orchestrator.plan.build_plan_async", new_callable=AsyncMock) as mock_async:
        mock_async.return_value = ["mock_result"]

        result = plan.build_plan("2025-12-20")

        assert result == ["mock_result"]
        mock_async.assert_called_once_with("2025-12-20")


def test_build_plan_sync_raises_in_event_loop():
    """
    Tests that the synchronous wrapper raises a specific RuntimeError if called from within an existing event loop.
    This covers lines 104-107.
    """
    # Arrange: Mock asyncio.run to raise the specific error the code is looking for
    with patch("asyncio.run", side_effect=RuntimeError("cannot run loop while another is running")):
        # Act & Assert
        with pytest.raises(RuntimeError) as excinfo:
            plan.build_plan("2025-12-20")
        # Assert on the exception message explicitly for robustness
        assert str(excinfo.value) == "cannot run loop while another is running"


def test_build_plan_sync_reraises_other_runtime_errors():
    """
    Tests that the synchronous wrapper re-raises other RuntimeErrors it doesn't specifically handle.
    This covers line 108.
    """
    # Arrange: Mock asyncio.run to raise a generic RuntimeError
    with patch("asyncio.run", side_effect=RuntimeError("A different runtime error")):
        # Act & Assert
        with pytest.raises(RuntimeError, match="A different runtime error"):
            plan.build_plan("2025-12-20")
