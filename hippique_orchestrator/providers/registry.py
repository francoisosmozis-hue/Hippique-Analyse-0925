
import yaml
import importlib
from typing import Dict, List, Optional, Type
import logging
from functools import lru_cache

from hippique_orchestrator.providers.interface import ProviderInterface

# Configure logging
logger = logging.getLogger(__name__)

CONFIG_PATH = "config/providers.yaml"


class ProviderRegistry:
    """
    Manages the lifecycle and selection of data providers.

    This class reads the provider configuration, dynamically loads the necessary
    provider classes, and selects an active provider based on the defined
    primary/fallback strategy and their health status.
    """

    def __init__(self, config_path: str = CONFIG_PATH):
        self._config = self._load_config(config_path)
        self._providers: Dict[str, ProviderInterface] = self._load_providers()

    @staticmethod
    def _load_config(path: str) -> Dict:
        """Loads the YAML configuration file."""
        try:
            with open(path, "r") as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            logger.error(f"Provider config file not found at: {path}")
            return {}
        except yaml.YAMLError as e:
            logger.error(f"Error parsing provider YAML config at {path}: {e}")
            return {}

    def _load_providers(self) -> Dict[str, ProviderInterface]:
        """Dynamically imports and instantiates providers based on the config."""
        providers: Dict[str, ProviderInterface] = {}
        provider_definitions = self._config.get("providers", {})

        for name, details in provider_definitions.items():
            try:
                class_path = details["class"]
                module_path, class_name = class_path.rsplit(".", 1)
                module = importlib.import_module(module_path)
                provider_class: Type[ProviderInterface] = getattr(module, class_name)
                # Instantiate with provider-specific config if available
                instance = provider_class(**details.get("config", {}))
                providers[name] = instance
                logger.info(f"Successfully loaded provider: '{name}'")
            except (ImportError, AttributeError, KeyError) as e:
                logger.error(f"Failed to load provider '{name}': {e}. It will be unavailable.")
            except Exception as e:
                logger.error(f"An unexpected error occurred while loading provider '{name}': {e}")

        return providers

    def get_provider(self, name: str) -> Optional[ProviderInterface]:
        """Returns a specific provider instance by name."""
        return self._providers.get(name)

    def get_active_provider(self) -> Optional[ProviderInterface]:
        """
        Returns the first healthy provider based on the primary/fallback strategy.
        """
        strategy = self._config.get("strategy", {})
        primary_name = strategy.get("primary")
        fallback_names = strategy.get("fallback", [])

        # 1. Try the primary provider
        if primary_name:
            provider = self.get_provider(primary_name)
            if provider and provider.is_healthy():
                logger.info(f"Active provider selected: '{primary_name}' (Primary)")
                return provider
            elif provider:
                logger.warning(
                    f"Primary provider '{primary_name}' is unhealthy. "
                    "Attempting to use fallbacks."
                )

        # 2. Try fallback providers in order
        for fallback_name in fallback_names:
            provider = self.get_provider(fallback_name)
            if provider and provider.is_healthy():
                logger.info(f"Active provider selected: '{fallback_name}' (Fallback)")
                return provider
            elif provider:
                 logger.warning(
                    f"Fallback provider '{fallback_name}' is unhealthy. "
                    "Trying next fallback."
                )

        logger.error("No healthy provider available. System will have no data source.")
        return None


@lru_cache(maxsize=1)
def get_provider_registry() -> ProviderRegistry:
    """
    Singleton factory for the ProviderRegistry.
    Using lru_cache ensures it's instantiated only once.
    """
    return ProviderRegistry()


# Convenience function to get the active provider directly
def get_active_provider() -> Optional[ProviderInterface]:
    """
    A simple entry point to get the current active and healthy provider.
    """
    registry = get_provider_registry()
    return registry.get_active_provider()
