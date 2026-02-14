"""
Manages and provides access to data providers based on a YAML configuration.

This registry implements a primary/fallback strategy. It identifies providers
that match a certain capability (e.g., fetching a programme) and returns them
in the order of preference defined in the configuration.
"""
import yaml
import importlib
from typing import Dict, Any, Optional, Type, List, TypeVar

from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.providers.base_provider import (
    BaseProgrammeProvider,
    BaseSnapshotProvider,
)

logger = get_logger(__name__)

T = TypeVar("T")


class SourceRegistry:
    """
    Manages and provides access to data providers based on a YAML configuration.
    """

    _instance = None

    def __new__(cls, config_path: str = "config/providers.yaml"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_path: str = "config/providers.yaml"):
        if self._initialized:
            return

        try:
            with open(config_path, "r") as f:
                self.config = yaml.safe_load(f)
        except FileNotFoundError:
            logger.error(f"Provider configuration file not found at: {config_path}")
            raise
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML configuration at {config_path}: {e}")
            raise

        self._providers: Dict[str, Any] = {}
        self._load_providers()
        self._initialized = True

    def _load_providers(self):
        """Dynamically imports and instantiates providers from the config."""
        provider_configs = self.config.get("providers", {})
        for name, config in provider_configs.items():
            try:
                module_path, class_name = config["class"].rsplit(".", 1)
                module = importlib.import_module(module_path)
                provider_class = getattr(module, class_name)
                # We instantiate the provider with its specific config, if any
                provider_instance = provider_class(**config.get("config", {}))
                self._providers[name] = provider_instance
                logger.info(f"Successfully loaded provider: '{name}'")
            except (ImportError, AttributeError, KeyError, TypeError) as e:
                logger.error(
                    f"Could not load provider '{name}' from class "
                    f"'{config.get('class')}': {e}",
                    exc_info=True,
                )
                # We continue loading other providers even if one fails
                continue

    def get_provider(self, name: str) -> Optional[Any]:
        """Gets an instantiated provider by its name."""
        return self._providers.get(name)

    def get_providers_by_capability(self, capability: Type[T]) -> List[T]:
        """
        Returns an ordered list of providers that match a given capability
        (i.e., are instances of a specific base class).

        The order is determined by the 'strategy' in the configuration:
        primary provider first, followed by fallback providers.

        Args:
            capability: The base class defining the required capability
                        (e.g., BaseProgrammeProvider).

        Returns:
            A list of provider instances matching the capability, in the
            correct strategic order.
        """
        strategy = self.config.get("strategy", {})
        primary_name = strategy.get("primary")
        fallback_names = strategy.get("fallback", [])

        ordered_provider_names = []
        if primary_name:
            ordered_provider_names.append(primary_name)
        if fallback_names:
            ordered_provider_names.extend(fallback_names)

        if not ordered_provider_names:
            logger.warning("No provider strategy defined in the configuration.")
            return []

        logger.debug(f"Provider strategy order: {ordered_provider_names}")
        
        capable_providers = []
        for name in ordered_provider_names:
            provider = self.get_provider(name)
            if provider and isinstance(provider, capability):
                capable_providers.append(provider)
            elif provider:
                logger.warning(
                    f"Provider '{name}' from strategy does not implement the "
                    f"required capability '{capability.__name__}'."
                )
            else:
                logger.warning(f"Provider '{name}' from strategy could not be found.")

        logger.info(
            f"Found {len(capable_providers)} providers for capability "
            f"'{capability.__name__}': {[p.__class__.__name__ for p in capable_providers]}"
        )
        return capable_providers

    def get_primary_programme_provider(self) -> Optional[BaseProgrammeProvider]:
        """Returns the primary programme provider, or None if not found."""
        providers = self.get_providers_by_capability(BaseProgrammeProvider)
        if providers:
            return providers[0]
        return None

    def get_primary_snapshot_provider(self) -> Optional[BaseSnapshotProvider]:
        """Returns the primary snapshot provider, or None if not found."""
        providers = self.get_providers_by_capability(BaseSnapshotProvider)
        if providers:
            return providers[0]
        return None

# Singleton instance for easy access across the application
source_registry = SourceRegistry()
