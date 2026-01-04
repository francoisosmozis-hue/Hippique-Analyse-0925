import asyncio
import sys  # Added back
from pathlib import Path

# Add the project root to the sys.path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from .logging_utils import get_logger
from .plan import build_plan_async
from .runner import run_course  # Import the function directly

# Setup a basic logger to see output
logger = get_logger("temp_plan_runner")

async def main():
    plan = await build_plan_async("today")
    logger.info("Generated Plan:")

    # No need to instantiate GPIRunner, call run_course directly
    # gpi_runner = GPIRunner()

    for race in plan:
        logger.info(f"Processing race: {race['r_label']}{race['c_label']} ({race['course_url']})")

        # Run H-30 phase
        h30_result = run_course( # Call the function directly
            course_url=race["course_url"],
            phase="H-30",
            date=race["date"], # Use 'date' instead of 'date_str'
            correlation_id=f"{race['r_label']}{race['c_label']}-H30"
        )
        logger.info(f"H-30 Result for {race['r_label']}{race['c_label']}: {h30_result}")

        # Run H-5 phase
        h5_result = run_course( # Call the function directly
            course_url=race["course_url"],
            phase="H-5",
            date=race["date"], # Use 'date' instead of 'date_str'
            correlation_id=f"{race['r_label']}{race['c_label']}-H5"
        )
        logger.info(f"H-5 Result for {race['r_label']}{race['c_label']}: {h5_result}")

if __name__ == "__main__":
    asyncio.run(main())
