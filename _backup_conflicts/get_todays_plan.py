import asyncio
import json

from hippique_orchestrator.plan import build_plan_async


async def main():
    plan = await build_plan_async("today")
    print(json.dumps(plan, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
