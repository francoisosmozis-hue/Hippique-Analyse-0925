import yaml
import importlib
from typing import Dict, Any, Optional, Type
from hippique_orchestrator.providers.base_provider import BaseProgrammeProvider, BaseSnapshotProvider

class SourceRegistry:
    """
    Manages and provides access to data providers based on a YAML configuration.
    """
    _instance = None

    def __new__(cls, config_path="config/providers.yaml"):
        if cls._instance is None:
            cls._instance = super(SourceRegistry, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_path="config/providers.yaml"):
        if self._initialized:
            return
        
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.providers: Dict[str, Any] = {}
        self._load_providers()
        self._initialized = True

    def _load_providers(self):
        """Dynamically imports and instantiates providers from the config."""
        provider_configs = self.config.get("providers", {})
        for name, config in provider_configs.items():
            try:
                module_path, class_name = config["class"].rsplit('.', 1)
                module = importlib.import_module(module_path)
                provider_class = getattr(module, class_name)
                # We instantiate the provider with its specific config, if any
                provider_instance = provider_class(**config.get("config", {}))
                self.providers[name] = provider_instance
            except (ImportError, AttributeError, KeyError) as e:
                raise ImportError(f"Could not load provider '{name}' from class '{config.get('class')}': {e}")

    def get_provider(self, name: str) -> Optional[Any]:
        """Gets an instantiated provider by its name."""
        return self.providers.get(name)

    def get_primary_programme_provider(self) -> Optional[BaseProgrammeProvider]:
        """
        Returns the primary provider for fetching the race programme.
        """
        primary_name = self.config.get("strategy", {}).get("primary")
        if not primary_name:
            raise ValueError("Primary programme provider not defined in strategy.")
        
        provider = self.get_provider(primary_name)
        if provider and isinstance(provider, BaseProgrammeProvider):
            return provider
        
        if provider:
             raise TypeError(f"Primary provider '{primary_name}' does not implement BaseProgrammeProvider.")
        
        raise ValueError(f"Primary provider '{primary_name}' could not be found or instantiated.")

    def get_primary_snapshot_provider(self) -> Optional[BaseSnapshotProvider]:
        """
        Returns the primary provider for fetching race snapshots.
        """
        primary_name = self.config.get("strategy", {}).get("primary")
        if not primary_name:
            raise ValueError("Primary snapshot provider not defined in strategy.")
        
        provider = self.get_provider(primary_name)
        if provider and isinstance(provider, BaseSnapshotProvider):
            return provider

        if provider:
            raise TypeError(f"Primary provider '{primary_name}' does not implement BaseSnapshotProvider.")
            
        raise ValueError(f"Primary provider '{primary_name}' could not be found or instantiated.")

# Singleton instance for easy access across the application
source_registry = SourceRegistry()
