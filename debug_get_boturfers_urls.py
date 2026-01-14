import asyncio

from hippique_orchestrator.sources.boturfers_provider import BoturfersProvider

async def main():
    """
    Calls the fetch_programme method to get a list of race URLs.
    """
    provider = BoturfersProvider()
    programme_url = "https://www.boturfers.fr/programme-pmu-du-jour"
    races = await provider.fetch_programme(programme_url)
    
    if races:
        print("Races found:")
        for race in races:
            print(f"- {race.get('rc')}: {race.get('url')}")
    else:
        print("No races found.")

if __name__ == "__main__":
    asyncio.run(main())
