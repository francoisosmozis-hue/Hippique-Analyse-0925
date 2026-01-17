"""
Provides a high-level, simplified interface for fetching race programs.

This module acts as the primary entry point for the application to obtain the
day's race schedule. It uses the SourceRegistry to abstract away the
complexities of data source selection and fallbacks.
"""
from datetime import date
from typing import Optional

from .data_contract import Programme
from .logging_utils import get_logger
from .providers.base_provider import BaseProgrammeProvider
from .source_registry import source_registry

logger = get_logger(__name__)


def get_programme_for_date(target_date: date) -> Optional[Programme]:
    """
    Fetches the race program for a given date using the defined provider strategy.

    It iterates through the providers (primary, then fallbacks) as defined in
    the SourceRegistry. It returns the programme from the first provider that
    succeeds.

    Args:
        target_date: The date for which to fetch the program.

    Returns:
        A validated Programme object if successful, otherwise None.
    """
    logger.info(f"Requesting race programme for date: {target_date.isoformat()}")

    providers = source_registry.get_providers_by_capability(BaseProgrammeProvider)

    if not providers:
        logger.critical("No programme providers are configured or loaded. Cannot fetch data.")
        return None

    date_str = target_date.strftime("%Y-%m-%d")

    for provider in providers:
        provider_name = provider.__class__.__name__
        logger.info(f"Attempting to fetch programme from provider: {provider_name}")
        try:
            # Each provider is responsible for returning data that can be
            # parsed into a Programme object.
            programme_data = provider.get_programme(date_str)

            if not programme_data or not programme_data.get("races"):
                logger.warning(
                    f"Provider '{provider_name}' returned no data for {date_str}."
                )
                continue

            # At the boundary, we immediately validate and parse the data
            # against our contract.
            programme = Programme.model_validate(programme_data)

            logger.info(
                f"Successfully fetched and validated programme from provider "
                f"'{provider_name}' with {len(programme.races)} races."
            )
            return programme

        except Exception as e:
            logger.error(
                f"Provider '{provider_name}' failed to deliver a valid programme "
                f"for {date_str}: {e}",
                exc_info=True,
            )
            # This provider failed, loop will continue to the next one (fallback)
            continue

    logger.critical(
        f"All configured providers failed to deliver a programme for {date_str}."
    )
    return None