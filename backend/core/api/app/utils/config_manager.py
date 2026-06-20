# backend/core/api/app/utils/config_manager.py
#
# This module defines the ConfigManager class, responsible for loading
# and providing access to the main backend configuration (backend_config.yml)
# and provider configurations (providers/*.yml).

import yaml
import os
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

# The root of the backend project inside the container is /app/backend,
# as defined by the volume mounts in docker-compose.yml.
CONTAINER_BACKEND_ROOT = "/app/backend"

# Define absolute paths to the configuration files within the container.
# This is more robust than relative path calculations.
BACKEND_CONFIG_FILE = os.getenv(
    "BACKEND_CONFIG_FILE",
    os.path.join(CONTAINER_BACKEND_ROOT, "config/backend_config.yml"),
)
PROVIDERS_CONFIG_DIR = os.path.join(CONTAINER_BACKEND_ROOT, "providers")
PROVIDER_OVERLAY_CONFIG_DIR = os.getenv("PROVIDER_CONFIG_DIR")

class ConfigManager:
    """
    Manages loading and accessing backend and provider configurations.
    """
    _instance = None
    _backend_config: Optional[Dict[str, Any]] = None
    _provider_configs: Optional[Dict[str, Dict[str, Any]]] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._load_configs()
        return cls._instance

    def _load_configs(self):
        """Loads all configurations."""
        self._load_backend_config()
        self._load_provider_configs()

    def _load_backend_config(self):
        """Loads the main backend_config.yml file."""
        if not os.path.exists(BACKEND_CONFIG_FILE):
            logger.error(f"Backend configuration file not found: {BACKEND_CONFIG_FILE}")
            self._backend_config = {} # Default to empty if not found
            return

        try:
            with open(BACKEND_CONFIG_FILE, 'r') as f:
                self._backend_config = yaml.safe_load(f)
            if self._backend_config is None: # Handle empty YAML file
                self._backend_config = {}
            self._backend_config = self._migrate_legacy_feature_config(self._backend_config)
            logger.info(f"Successfully loaded backend configuration from {BACKEND_CONFIG_FILE}")
        except yaml.YAMLError as e:
            logger.error(f"Error parsing backend configuration file {BACKEND_CONFIG_FILE}: {e}")
            self._backend_config = {} # Default to empty on error
        except IOError as e:
            logger.error(f"Error reading backend configuration file {BACKEND_CONFIG_FILE}: {e}")
            self._backend_config = {} # Default to empty on error


    def _merge_provider_config(self, config_data: Dict[str, Any], source_name: str) -> None:
        """Merge a provider config into the loaded provider map."""
        if not config_data or 'provider_id' not in config_data:
            logger.warning(f"Provider configuration file {source_name} is missing the 'provider_id' field. Skipping.")
            return

        provider_key = config_data['provider_id']
        existing = self._provider_configs.get(provider_key) if self._provider_configs else None
        if not existing:
            self._provider_configs[provider_key] = config_data
            logger.info(f"Successfully loaded provider configuration: {source_name} for provider_id: {provider_key}")
            return

        merged = dict(existing)

        existing_models = [model for model in existing.get("models", []) if isinstance(model, dict)]
        overlay_models = [model for model in config_data.get("models", []) if isinstance(model, dict)]
        model_by_id = {model.get("id"): model for model in existing_models if model.get("id")}
        for model in overlay_models:
            model_id = model.get("id")
            if model_id:
                model_by_id[model_id] = model
        merged["models"] = list(model_by_id.values())
        self._provider_configs[provider_key] = merged
        logger.info(
            "Merged provider overlay: %s into provider_id: %s (%d overlay model(s))",
            source_name,
            provider_key,
            len(overlay_models),
        )

    def _load_provider_config_file(self, provider_file_path: str, source_name: str) -> None:
        try:
            with open(provider_file_path, 'r') as f:
                config_data = yaml.safe_load(f)
                if not config_data:
                    logger.warning(f"Provider configuration file {source_name} is empty or invalid.")
                    return
                if isinstance(config_data, dict) and isinstance(config_data.get("providers"), list):
                    for index, provider_config in enumerate(config_data["providers"]):
                        if isinstance(provider_config, dict):
                            self._merge_provider_config(provider_config, f"{source_name}#providers[{index}]")
                    return
                if isinstance(config_data, dict):
                    self._merge_provider_config(config_data, source_name)
                    return
                logger.warning(f"Provider configuration file {source_name} is not a mapping. Skipping.")
        except yaml.YAMLError as e:
            logger.error(f"Error parsing provider configuration file {source_name}: {e}")
        except IOError as e:
            logger.error(f"Error reading provider configuration file {source_name}: {e}")

    def _load_provider_configs_from_dir(self, directory: str, *, overlay: bool = False) -> None:
        if not os.path.isdir(directory):
            if overlay:
                logger.info(f"Provider overlay configuration directory not found: {directory}")
            else:
                logger.error(f"Providers configuration directory not found: {directory}")
            return

        for filename in os.listdir(directory):
            if filename.endswith((".yml", ".yaml")):
                provider_file_path = os.path.join(directory, filename)
                self._load_provider_config_file(provider_file_path, filename)

    def _load_provider_configs(self):
        """Loads built-in provider YAML files and optional runtime overlays."""
        self._provider_configs = {}
        self._load_provider_configs_from_dir(PROVIDERS_CONFIG_DIR)

        if PROVIDER_OVERLAY_CONFIG_DIR and os.path.abspath(PROVIDER_OVERLAY_CONFIG_DIR) != os.path.abspath(PROVIDERS_CONFIG_DIR):
            self._load_provider_configs_from_dir(PROVIDER_OVERLAY_CONFIG_DIR, overlay=True)

    def get_backend_config(self) -> Dict[str, Any]:
        """Returns the entire backend configuration."""
        return self._backend_config if self._backend_config is not None else {}

    @staticmethod
    def _normalize_feature_list(value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        return [item for item in (str(raw).strip() for raw in value) if item]

    def _migrate_legacy_feature_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate legacy disabled_apps into feature_overrides in memory."""
        migrated = dict(config)
        legacy_disabled_apps = self._normalize_feature_list(migrated.pop("disabled_apps", []))
        overrides = dict(migrated.get("feature_overrides") or {})
        disabled = self._normalize_feature_list(overrides.get("disabled"))
        enabled = self._normalize_feature_list(overrides.get("enabled"))
        for app_id in legacy_disabled_apps:
            feature_id = app_id if app_id.startswith("app:") else f"app:{app_id}"
            if feature_id not in disabled:
                disabled.append(feature_id)
        overrides["enabled"] = enabled
        overrides["disabled"] = disabled
        migrated["feature_overrides"] = overrides
        return migrated

    def get_feature_overrides(self) -> Dict[str, List[str]]:
        """Returns admin feature override lists from backend_config.yml."""
        config = self.get_backend_config()
        overrides = config.get("feature_overrides") if isinstance(config, dict) else {}
        if not isinstance(overrides, dict):
            logger.warning("'feature_overrides' in backend_config.yml is not a mapping. Returning empty overrides.")
            return {"enabled": [], "disabled": []}
        return {
            "enabled": self._normalize_feature_list(overrides.get("enabled")),
            "disabled": self._normalize_feature_list(overrides.get("disabled")),
        }

    def get_disabled_apps(self) -> List[str]:
        """
        Returns the list of disabled app IDs (service names).
        Apps are enabled by default - this is an opt-out list for temporarily disabling problematic apps.
        Assumes 'disabled_apps' in backend_config.yml is a simple list of strings.
        """
        disabled_features = self.get_feature_overrides().get("disabled", [])
        return [feature_id.removeprefix("app:") for feature_id in disabled_features if feature_id.startswith("app:")]

    def get_provider_configs(self) -> Dict[str, Dict[str, Any]]:
        """Returns all loaded provider configurations."""
        return self._provider_configs if self._provider_configs is not None else {}

    def get_provider_config(self, provider_id: str) -> Optional[Dict[str, Any]]:
        """
        Returns the configuration for a specific provider.
        The provider_id should match the key used during loading (lowercase name or filename).
        """
        return self._provider_configs.get(provider_id) if self._provider_configs else None

    def get_model_pricing(self, provider_id: str, model_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves all details (pricing, costs, etc.) for a specific model ID 
        from a specific provider.
        """
        provider_config = self.get_provider_config(provider_id)
        if not provider_config:
            logger.warning(f"Provider '{provider_id}' not found when searching for model '{model_id}'.")
            return None

        for model in provider_config.get("models", []):
            if isinstance(model, dict) and (model.get("id") == model_id or model_id in model.get("aliases", [])):
                # Return the entire model block, as it contains costs and other details needed for billing.
                return model
        
        logger.warning(f"Model '{model_id}' not found in provider config for '{provider_id}'.")
        return None

    def find_provider_for_model(self, model_id: str) -> Optional[str]:
        """
        Searches all provider configurations to find which provider defines a given model ID.
        
        This is useful when a user specifies a model without a provider prefix (e.g., 
        "claude-haiku-4-5-20251001" instead of "anthropic/claude-haiku-4-5-20251001").
        
        Args:
            model_id: The model ID to search for (without provider prefix).
            
        Returns:
            The provider_id if found, None otherwise.
        """
        if not self._provider_configs:
            logger.warning(f"No provider configurations loaded when searching for model '{model_id}'.")
            return None
        
        for provider_id, provider_config in self._provider_configs.items():
            for model in provider_config.get("models", []):
                if isinstance(model, dict) and (model.get("id") == model_id or model_id in model.get("aliases", [])):
                    logger.info(f"Found model '{model_id}' in provider '{provider_id}'.")
                    return provider_id
        
        logger.warning(f"Model '{model_id}' not found in any provider configuration.")
        return None

    def get_model_display_name(self, model_id: str, provider_id: Optional[str] = None) -> Optional[str]:
        """
        Gets the human-readable display name for a model ID.
        
        This is useful for showing friendly names like "Claude Haiku 4.5" instead of 
        technical IDs like "claude-haiku-4-5-20251001" in the UI.
        
        Args:
            model_id: The model ID to look up (without provider prefix).
            provider_id: Optional provider ID to search within. If not provided,
                        searches all providers.
            
        Returns:
            The human-readable model name if found, None otherwise.
        """
        if not self._provider_configs:
            logger.warning(f"No provider configurations loaded when looking up name for model '{model_id}'.")
            return None
        
        # If provider_id is specified, search only that provider
        if provider_id:
            provider_config = self.get_provider_config(provider_id)
            if provider_config:
                for model in provider_config.get("models", []):
                    if isinstance(model, dict) and (model.get("id") == model_id or model_id in model.get("aliases", [])):
                        model_name = model.get("name")
                        if model_name:
                            logger.debug(f"Found display name '{model_name}' for model '{model_id}' in provider '{provider_id}'.")
                            return model_name
            return None
        
        # Search all providers
        for pid, provider_config in self._provider_configs.items():
            for model in provider_config.get("models", []):
                if isinstance(model, dict) and (model.get("id") == model_id or model_id in model.get("aliases", [])):
                    model_name = model.get("name")
                    if model_name:
                        logger.debug(f"Found display name '{model_name}' for model '{model_id}' in provider '{pid}'.")
                        return model_name
        
        logger.debug(f"No display name found for model '{model_id}'.")
        return None

# Create a singleton instance for easy import across the application.
config_manager = ConfigManager()
