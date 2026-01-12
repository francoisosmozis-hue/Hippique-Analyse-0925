import asyncio
from datetime import datetime

from hippique_orchestrator.plan import build_plan_async
from hippique_orchestrator.scheduler import schedule_all_races


async def main():
    today = datetime.now().strftime("%Y-%m-%d")
    plan = await build_plan_async(today)
    schedule_all_races(plan, "all", "manual-trigger", "manual-trigger")


if __name__ == "__main__":
    asyncio.run(main())
