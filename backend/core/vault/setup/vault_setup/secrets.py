"""
Functions for managing secrets in Vault.
"""

import os
import re
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("vault-setup.secrets")

class SecretsManager:
    """Manages secrets in Vault, including migration from .env files."""

    def __init__(self, vault_client):
        """Initialize with a vault client instance.

        Args:
            vault_client: The VaultClient instance
        """
        self.client = vault_client
        self.secrets_imported_flag_path = "kv/data/system_flags/migration_status"
        self.secrets_imported_flag_key = "initial_env_secrets_migrated_to_providers_paths" # New flag key
        self.secret_prefix = "SECRET__"
        self.initial_migration_processed_count = 0  # Tracks secrets processed in initial migration

    def _parse_env_var_name(self, env_var_name: str) -> Optional[tuple[str, str, str]]:
        """
        Parses an environment variable name like SECRET__{PROVIDER_NAME}__{KEY_NAME}
        into (vault_path, vault_key_name, original_env_key_name).
        Returns None if parsing fails.
        """
        if not env_var_name.startswith(self.secret_prefix):
            return None

        parts = env_var_name[len(self.secret_prefix):].split("__", 1)
        if len(parts) != 2:
            logger.warning(f"Could not parse env var '{env_var_name}'. Expected format: SECRET__PROVIDERNAME__KEYNAME.")
            return None

        provider_name_original = parts[0]
        key_name_original = parts[1]

        if not provider_name_original or not key_name_original:
            logger.warning(f"Empty provider name or key name in env var '{env_var_name}'.")
            return None

        provider_name_lower = provider_name_original.lower()
        key_name_lower = key_name_original.lower() # Key in vault will be lowercase

        vault_path = f"kv/data/providers/{provider_name_lower}"
        return vault_path, key_name_lower, env_var_name # Return original env_var_name for logging

    async def _write_secret_to_vault(self, vault_path: str, secret_key: str, secret_value: str, env_var_name_for_logging: str) -> bool:
        """
        Writes a single secret to a specific path and key in Vault.
        It fetches existing secrets at the path and merges.
        If the specific secret_key already exists with a *different* value, it logs a warning and overwrites.
        """
        try:
            existing_data_at_path = {}
            try:
                response = await self.client.vault_request("get", vault_path)
                if response and "data" in response and "data" in response["data"]:
                    existing_data_at_path = response["data"]["data"]
            except Exception: # Path might not exist yet, which is fine
                logger.debug(f"Path {vault_path} not found or no existing data. Will create if needed.")

            if secret_key in existing_data_at_path and existing_data_at_path[secret_key] != secret_value:
                logger.warning(f"Secret '{secret_key}' at path '{vault_path}' (from env var '{env_var_name_for_logging}') "
                               f"already exists with a different value. It will be OVERWRITTEN.")
            
            # Update or add the specific secret key
            existing_data_at_path[secret_key] = secret_value

            await self.client.vault_request("post", vault_path, {"data": existing_data_at_path})
            logger.info(f"Successfully wrote secret '{secret_key}' (from env var '{env_var_name_for_logging}') to Vault path '{vault_path}'.")
            return True
        except Exception as e:
            logger.error(f"Failed to write secret '{secret_key}' (from env var '{env_var_name_for_logging}') to Vault path '{vault_path}': {e}", exc_info=True)
            return False

    async def check_secrets_migration_status(self) -> bool:
        """Check if secrets have been migrated to Vault using the new path structure flag."""
        try:
            response = await self.client.vault_request("get", self.secrets_imported_flag_path)
            if response and response.get("data", {}).get("data", {}).get(self.secrets_imported_flag_key) == True:
                logger.info(f"Secrets migration flag '{self.secrets_imported_flag_key}' is set. Assuming migration to provider paths already performed.")
                return True
            return False
        except Exception: # Path or flag might not exist
            return False

    def find_secrets_in_env(self) -> Dict[str, str]:
        """Finds all environment variables starting with the defined secret prefix and returns them as a dict."""
        secrets = {}
        for env_var_key, value in os.environ.items():
            if env_var_key.startswith(self.secret_prefix):
                if value and value.strip() and value != "IMPORTED_TO_VAULT": # Ensure value is not empty or placeholder
                    secrets[env_var_key] = value
        return secrets

    async def _process_env_secrets(self, is_initial_migration: bool) -> int:
        """
        Finds, parses, and writes/updates secrets from environment variables to Vault.
        Returns the count of successfully processed (written/updated) secrets.
        """
        secrets_from_env = self.find_secrets_in_env()
        if not secrets_from_env:
            logger.info("No secrets found in environment matching prefix.")
            return 0

        logger.info(f"Found {len(secrets_from_env)} potential secrets in environment with prefix '{self.secret_prefix}'.")
        processed_count = 0

        for env_var_name, env_var_value in secrets_from_env.items():
            parsed = self._parse_env_var_name(env_var_name)
            if not parsed:
                logger.warning(f"Skipping env var '{env_var_name}' due to parsing failure.")
                continue
            
            vault_path, vault_key, _ = parsed

            # During initial migration, we always attempt to write.
            # For "add_new_secrets" (is_initial_migration=False), the behavior is the same:
            # ensure current env state is reflected in Vault.
            # The _write_secret_to_vault handles logging if overwriting different existing value.
            if await self._write_secret_to_vault(vault_path, vault_key, env_var_value, env_var_name):
                processed_count += 1
        
        return processed_count

    async def migrate_secrets_to_vault(self) -> bool:
        """Migrate secrets from .env to Vault using the SECRET__{PROVIDER}__{KEY} convention."""
        logger.info("Checking for secrets to migrate to Vault (provider path structure)...")
        self.initial_migration_processed_count = 0 # Reset for this call

        if await self.check_secrets_migration_status():
            logger.info("Initial secrets migration to provider paths already performed (flag found).")
            return True # Already migrated

        migrated_count = await self._process_env_secrets(is_initial_migration=True)
        self.initial_migration_processed_count = migrated_count # Store count for this run

        if migrated_count > 0:
            logger.info(f"Successfully migrated {migrated_count} secrets to their respective Vault provider paths.")
        else:
            logger.info("No secrets were actively migrated from environment (either none found or all failed).")

        # Mark migration as completed
        try:
            await self.client.vault_request("post", self.secrets_imported_flag_path, {"data": {self.secrets_imported_flag_key: True}})
            logger.info(f"Set migration flag '{self.secrets_imported_flag_key}' at '{self.secrets_imported_flag_path}'.")
        except Exception as e:
            logger.error(f"Failed to set migration flag: {e}", exc_info=True)
            # If setting flag fails, migration might run again, but _write_secret_to_vault should handle it.
        return True

    async def add_new_secrets_to_vault(self) -> bool:
        """
        Ensures all current `SECRET__*` environment variables are reflected in Vault
        according to the `SECRET__{PROVIDER}__{KEY}` convention.
        This effectively acts as an "update" or "sync" from env to Vault based on current env vars.
        """
        logger.info("Synchronizing current environment secrets (SECRET__*) to Vault provider paths...")
        
        # Re-process all current env secrets. _process_env_secrets handles writing/overwriting.
        processed_count = await self._process_env_secrets(is_initial_migration=False)

        if processed_count > 0:
            logger.info(f"Successfully processed (added/updated) {processed_count} secrets in Vault from current environment variables.")
        else:
            logger.info("No secrets from environment were newly added or updated in Vault.")
            
        return True