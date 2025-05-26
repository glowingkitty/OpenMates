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

# Define paths relative to the container's /app directory,
# which is the working directory and root of the API service code.
# /app in the container maps to backend/core/api on the host.
# We need to reach backend/config and backend/providers on the host.

CONTAINER_APP_DIR = "/app" # Standard working directory for the api service

# Path to backend_config.yml: from /app (backend/core/api), go up to backend/, then into config/
BACKEND_CONFIG_FILE = os.path.abspath(os.path.join(CONTAINER_APP_DIR, "../../config/backend_config.yml"))

# Path to providers directory: from /app (backend/core/api), go up to backend/, then into providers/
PROVIDERS_CONFIG_DIR = os.path.abspath(os.path.join(CONTAINER_APP_DIR, "../../providers"))

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
            logger.warning(f"Providers configuration directory not found: {PROVIDERS_CONFIG_DIR}")
            # Create the directory if it doesn't exist, as per common practice for config folders
            try:
                os.makedirs(PROVIDERS_CONFIG_DIR)
                logger.info(f"Created providers configuration directory: {PROVIDERS_CONFIG_DIR}")
            except OSError as e:
                logger.error(f"Could not create providers configuration directory {PROVIDERS_CONFIG_DIR}: {e}")
            return # Return here as there will be no files to load

        for filename in os.listdir(PROVIDERS_CONFIG_DIR):
            if filename.endswith((".yml", ".yaml")):
                provider_file_path = os.path.join(PROVIDERS_CONFIG_DIR, filename)
                try:
                    with open(provider_file_path, 'r') as f:
                        config_data = yaml.safe_load(f)
                        if config_data and 'name' in config_data:
                            # Use provider name as key, or filename without extension if name not present
                            provider_key = config_data['name'].lower().replace(" ", "_")
                            self._provider_configs[provider_key] = config_data
                            logger.info(f"Successfully loaded provider configuration: {filename}")
                        elif config_data:
                            # Fallback to filename if 'name' is not in the YAML
                            provider_key_fallback = os.path.splitext(filename)[0]
                            self._provider_configs[provider_key_fallback] = config_data
                            logger.warning(f"Provider configuration {filename} loaded using filename as key (missing 'name' field).")
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

    def get_model_pricing(self, full_model_reference: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves pricing information for a specific model.
        full_model_reference is expected in "provider_id/model_id" format.
        e.g., "google/gemini-2.5-pro"
        """
        if not self._provider_configs or '/' not in full_model_reference:
            logger.warning(f"Invalid full_model_reference format or no providers loaded: {full_model_reference}")
            return None

        provider_id, model_id_to_find = full_model_reference.split('/', 1)
        provider_config = self.get_provider_config(provider_id)

        if provider_config and "models" in provider_config:
            for model in provider_config["models"]:
                if isinstance(model, dict) and model.get("id") == model_id_to_find:
                    return model.get("pricing")
        logger.warning(f"Pricing not found for model: {full_model_reference}")
        return None

# Singleton instance
config_manager = ConfigManager()

if __name__ == '__main__':
    # This block is for basic testing when running this file directly.
    # It will attempt to load configurations and print them.
    # Ensure backend/config/backend_config.yml exists.
    # For provider configs, ensure backend/providers/ directory exists
    # and contains some .yml files (e.g., a google.yml as per architecture docs).

    print("--- Backend Config ---")
    print(config_manager.get_backend_config())
    print("\n--- Enabled Apps ---")
    enabled_app_ids = config_manager.get_enabled_apps()
    if enabled_app_ids:
        for app_id in enabled_app_ids:
            print(f"  - App ID: {app_id}")
    else:
        print("No enabled apps configured or loaded.")
    print("\n--- Provider Configs ---")
    all_providers = config_manager.get_provider_configs()
    if not all_providers:
        print("No provider configurations found or loaded.")
        print(f"Ensure the directory {PROVIDERS_CONFIG_DIR} exists and contains provider YAML files.")
    else:
        for p_id, p_conf in all_providers.items():
            print(f"\nProvider ID (key): {p_id}")
            # print(f"Full Config: {p_conf}") # Can be verbose
            print(f"  Name: {p_conf.get('name', 'N/A')}")
            print(f"  Description: {p_conf.get('description', 'N/A')}")
            if "models" in p_conf:
                print("  Models:")
                for model_info in p_conf["models"]:
                    if isinstance(model_info, dict):
                        model_id = model_info.get("id", "N/A")
                        model_name = model_info.get("name", "N/A")
                        print(f"    - ID: {model_id}, Name: {model_name}")
                        pricing = config_manager.get_model_pricing(f"{p_id}/{model_id}")
                        if pricing:
                            print(f"      Pricing: {pricing}")
                        else:
                            print(f"      Pricing: Not found for {p_id}/{model_id}")
                    else:
                        print(f"    - Unexpected model format: {model_info}")
            else:
                print("  No models defined for this provider.")

    print("\n--- Example: Test get_model_pricing (assuming 'google.yml' exists with 'gemini-2.5-pro') ---")
    # This test relies on a google.yml existing in backend/config/providers/
    # with a structure similar to the architecture document.
    google_gemini_pro_pricing = config_manager.get_model_pricing('google/gemini-2.5-pro')
    if google_gemini_pro_pricing:
        print(f"Pricing for 'google/gemini-2.5-pro': {google_gemini_pro_pricing}")
    else:
        print(f"Pricing for 'google/gemini-2.5-pro': Not found. Ensure 'google.yml' exists and is correctly formatted in {PROVIDERS_CONFIG_DIR}.")

    print(f"Pricing for 'google/nonexistent-model': {config_manager.get_model_pricing('google/nonexistent-model')}")
    print(f"Pricing for 'nonexistent-provider/model': {config_manager.get_model_pricing('nonexistent-provider/model')}")