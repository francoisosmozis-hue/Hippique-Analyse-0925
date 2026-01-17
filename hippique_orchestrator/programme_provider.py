"""
Provides a high-level, simplified interface for fetching race programs.

This module acts as the primary entry point for the application to obtain the
day's race schedule. It uses the SourceRegistry to abstract away the
complexities of data source selection and fallbacks.
"""
import logging
from datetime import date
from typing import List, Dict, Any

from .source_registry import source_registry
from .data_contract import Race, Meeting
# Assuming data_contract.py will define Pydantic models, but for now, we handle dicts.
# from .data_contract import Race 

logger = logging.getLogger(__name__)


def get_races_for_date(target_date: date) -> List[Dict[str, Any]]:
    """
    Fetches the race program for a given date using the active provider
    from the source registry.

    Args:
        target_date: The date for which to fetch the program.

    Returns:
        A list of race dictionaries. Returns an empty list if no provider is
        available or if the provider fails.
    """
    logger.info(f"Requesting race program for date: {target_date}")
    
    try:
        provider = source_registry.get_primary_programme_provider()
    except (ValueError, TypeError) as e:
        logger.critical(f"Could not get a primary programme provider: {e}")
        return []

    if not provider:
        logger.critical("No active provider available to fetch race program.")
        return []

    date_str = target_date.strftime("%Y-%m-%d")
    
    try:
        races_data = provider.get_programme(date_str)
    except NotImplementedError:
        logger.error(f"Provider '{provider.__class__.__name__}' has not implemented get_programme.")
        return []
    except Exception as e:
        logger.error(f"Provider '{provider.__class__.__name__}' failed to fetch race data for {date_str}: {e}", exc_info=True)
        return []


    if not races_data:
        logger.warning(f"Provider '{provider.__class__.__name__}' returned no race data for {date_str}.")
        return []

    # The plan builder expects a list of dicts. If the provider returns objects, they need to be converted.
    # For now, we assume the mock provider returns dicts.
    logger.info(f"Successfully retrieved {len(races_data)} races for {target_date} via provider '{provider.__class__.__name__}'.")
    return races_data


def get_meetings_for_date(target_date: date) -> List[Meeting]:
    """
    Fetches the race program for a given date and organizes it into meetings.

    Args:
        target_date: The date for which to fetch the program.

    Returns:
        A list of Meeting objects, each containing its respective races.
        Returns an empty list on failure.
    """
    logger.info(f"Requesting meetings for date: {target_date}")
    races_dicts = get_races_for_date(target_date)

    if not races_dicts:
        return []

    # Convert dicts to Race models for processing
    races = [Race(**race_dict) for race_dict in races_dicts]

    meetings: Dict[str, Meeting] = {}
    for race in races:
        # Create a unique key for the meeting based on hippodrome and country
        if not race.hippodrome:
            continue
        meeting_key = f"{race.hippodrome.upper()}_{race.country_code}"

        if meeting_key not in meetings:
            meetings[meeting_key] = Meeting(
                hippodrome=race.hippodrome,
                country_code=race.country_code,
                date=target_date,
            )

        meetings[meeting_key].races.append(race)
        meetings[meeting_key].races_count += 1

    meeting_list = list(meetings.values())
    logger.info(f"Organized races into {len(meeting_list)} meetings for {target_date}.")
    return meeting_list