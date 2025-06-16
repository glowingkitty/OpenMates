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
BACKEND_CONFIG_FILE = os.path.join(CONTAINER_BACKEND_ROOT, "config/backend_config.yml")
PROVIDERS_CONFIG_DIR = os.path.join(CONTAINER_BACKEND_ROOT, "providers")

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
            logger.info(f"Successfully loaded backend configuration from {BACKEND_CONFIG_FILE}")
        except yaml.YAMLError as e:
            logger.error(f"Error parsing backend configuration file {BACKEND_CONFIG_FILE}: {e}")
            self._backend_config = {} # Default to empty on error
        except IOError as e:
            logger.error(f"Error reading backend configuration file {BACKEND_CONFIG_FILE}: {e}")
            self._backend_config = {} # Default to empty on error


    def _load_provider_configs(self):
        """Loads all provider YAML files from the providers directory."""
        self._provider_configs = {}
        if not os.path.isdir(PROVIDERS_CONFIG_DIR):
            logger.error(f"Providers configuration directory not found: {PROVIDERS_CONFIG_DIR}")
            # Do not try to create it, as it should be mounted by Docker.
            return

        for filename in os.listdir(PROVIDERS_CONFIG_DIR):
            if filename.endswith((".yml", ".yaml")):
                provider_file_path = os.path.join(PROVIDERS_CONFIG_DIR, filename)
                try:
                    with open(provider_file_path, 'r') as f:
                        config_data = yaml.safe_load(f)
                        if config_data and 'provider_id' in config_data:
                            provider_key = config_data['provider_id']
                            self._provider_configs[provider_key] = config_data
                            logger.info(f"Successfully loaded provider configuration: {filename} for provider_id: {provider_key}")
                        elif config_data:
                            logger.warning(f"Provider configuration file {filename} is missing the 'provider_id' field. Skipping.")
                        else:
                            logger.warning(f"Provider configuration file {filename} is empty or invalid.")
                except yaml.YAMLError as e:
                    logger.error(f"Error parsing provider configuration file {filename}: {e}")
                except IOError as e:
                    logger.error(f"Error reading provider configuration file {filename}: {e}")

    def get_backend_config(self) -> Dict[str, Any]:
        """Returns the entire backend configuration."""
        return self._backend_config if self._backend_config is not None else {}

    def get_enabled_apps(self) -> List[str]:
        """
        Returns the list of enabled app IDs (service names).
        Assumes 'enabled_apps' in backend_config.yml is a simple list of strings.
        """
        if self._backend_config and "enabled_apps" in self._backend_config:
            apps = self._backend_config["enabled_apps"]
            if isinstance(apps, list):
                # Ensure all items are strings
                valid_apps = [str(app_id) for app_id in apps if isinstance(app_id, (str, int))] # Allow int for convenience, convert to str
                if len(valid_apps) != len(apps):
                    logger.warning("Some items in 'enabled_apps' were not strings and have been filtered or converted.")
                if not valid_apps:
                    logger.info("'enabled_apps' list is empty after validation.")
                return valid_apps
            else:
                logger.warning(f"'enabled_apps' in backend_config.yml is not a list. Found: {type(apps)}. Returning empty list.")
        else:
            logger.info("'enabled_apps' key not found in backend_config.yml or backend_config not loaded. Returning empty list.")
        return []

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
            if isinstance(model, dict) and model.get("id") == model_id:
                # Return the entire model block, as it contains costs and other details needed for billing.
                return model
        
        logger.warning(f"Model '{model_id}' not found in provider config for '{provider_id}'.")
        return None

# Create a singleton instance for easy import across the application.
config_manager = ConfigManager()
