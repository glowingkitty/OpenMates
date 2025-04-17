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
        # Prefix for API secrets in environment variables
        self.secrets_imported = False
        self.secret_prefix = "SECRET__" # Use a generic prefix
    
    async def check_secrets_migration_status(self) -> bool:
        """Check if secrets have been migrated to Vault.
        
        Returns:
            True if already migrated, False otherwise
        """
        try:
            # Look for a marker in Vault that indicates we've already imported secrets
            imported_marker = await self.client.vault_request("get", "kv/data/system/secrets_imported")
            if imported_marker and imported_marker.get("data", {}).get("data", {}).get("imported") == True:
                logger.info("Secrets have already been migrated to Vault")
                self.secrets_imported = True
                return True
            return False
        except Exception as e:
            logger.debug(f"Error checking secrets migration status: {str(e)}")
            return False
    
    def find_secrets_in_env(self) -> List[str]:
        """Find all environment variables starting with the defined secret prefix.
        
        Returns:
            List of API secret keys found in the environment
        """
        # Get all environment variables with the generic secret prefix
        return [key for key in os.environ.keys() if key.startswith(self.secret_prefix)]
    
    async def migrate_secrets_to_vault(self) -> bool:
        """Migrate API keys and secrets from .env file to Vault.
        
        Returns:
            True if secrets were migrated or already migrated, False otherwise
        """
        logger.info("Checking for secrets to migrate to Vault...")
        
        # Check if secrets have been imported to Vault before
        already_imported = await self.check_secrets_migration_status()
        if already_imported:
            return True
        
        try:
            # Find all secret keys in the environment using the generic prefix
            all_secret_keys = self.find_secrets_in_env()
            logger.info(f"Found {len(all_secret_keys)} potential secrets (starting with '{self.secret_prefix}') in the environment")
            
            # Collect all secrets from environment
            secrets_to_store = {}
            for key in all_secret_keys:
                value = os.environ.get(key)
                if value and value != "IMPORTED_TO_VAULT":
                    secrets_to_store[key] = value
            
            if not secrets_to_store:
                logger.info("No secrets found to migrate")
                return False
                
            # Get existing secrets from Vault to check for conflicts
            try:
                existing_secrets = await self.client.vault_request("get", "kv/data/api-keys")
                existing_data = existing_secrets.get("data", {}).get("data", {}) if existing_secrets else {}
                
                # Detect conflicts (keys with different values)
                conflicts = []
                for key, value in secrets_to_store.items():
                    if key in existing_data and existing_data[key] != value:
                        conflicts.append(key)
                
                if conflicts:
                    logger.warning(f"Found conflicts for keys: {', '.join(conflicts)}")
                    logger.warning("These keys will not be overwritten to prevent data loss")
                    logger.warning("To update these values, use the Vault CLI or API directly")
                    
                    # Remove conflicting keys from the migration
                    for key in conflicts:
                        del secrets_to_store[key]
                
                # Merge with existing secrets (without overwriting conflicts)
                merged_secrets = {**existing_data, **secrets_to_store}
                
                # Store merged secrets in Vault
                await self.client.vault_request("post", "kv/data/api-keys", {"data": merged_secrets})
                if secrets_to_store:
                    logger.info(f"Successfully migrated/updated {len(secrets_to_store)} secrets in Vault (kv/data/api-keys):")
                    for key in secrets_to_store.keys():
                        logger.info(f"  - {key}")
                # No else needed, already logged if no secrets found earlier
                
            except Exception as e:
                logger.error(f"Error checking existing secrets: {str(e)}")
                # Fallback to just storing the new secrets
                await self.client.vault_request("post", "kv/data/api-keys", {"data": secrets_to_store})
                if secrets_to_store:
                    logger.info(f"Successfully migrated {len(secrets_to_store)} secrets to Vault (kv/data/api-keys):")
                    for key in secrets_to_store.keys():
                        logger.info(f"  - {key}")
                else:
                    logger.info("No secrets needed migration.")
            
            # Mark as imported in Vault
            await self.client.vault_request("post", "kv/data/system/secrets_imported", {"data": {"imported": True}})
            
            # Secrets are now managed directly via environment variables, no need to update .env
            self.secrets_imported = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to migrate secrets to Vault: {str(e)}")
            return False
    
    async def add_new_secrets_to_vault(self) -> bool:
        """Check for new secrets (starting with SECRET__) in the environment and add them to Vault.
        
        This function looks for variables with the defined prefix that
        are not yet in Vault and adds them. It doesn't overwrite existing secrets.
        
        Returns:
            True if successful (or no new secrets), False on error
        """
        try:
            # Find all secret keys in the environment using the generic prefix
            all_secret_keys = self.find_secrets_in_env()
            
            if not all_secret_keys:
                logger.info(f"No secrets starting with '{self.secret_prefix}' found in environment")
                return True
                
            # Get existing secrets from Vault
            existing_secrets = await self.client.vault_request("get", "kv/data/api-keys")
            existing_data = existing_secrets.get("data", {}).get("data", {}) if existing_secrets else {}
            
            # Identify new secrets that aren't in Vault yet
            new_secrets_to_store = {}
            for key in all_secret_keys:
                value = os.environ.get(key)
                if not value or value == "IMPORTED_TO_VAULT":
                    continue
            
                if key in existing_data:
                    logger.debug(f"Secret '{key}' already exists in Vault, skipping.") # Changed to debug
                else:
                    new_secrets_to_store[key] = value
                    logger.info(f"New secret '{key}' identified for Vault.")
            
            if not new_secrets_to_store:
                logger.info("No new secrets found in environment to add to Vault")
                return True
                
            logger.info(f"Found {len(new_secrets_to_store)} new secrets to add to Vault (kv/data/api-keys)")
            
            # Merge with existing secrets
            merged_secrets = {**existing_data, **new_secrets_to_store}
            
            # Store merged secrets back to Vault
            await self.client.vault_request("post", "kv/data/api-keys", {"data": merged_secrets})
            
            # Secrets are now managed directly via environment variables, no need to update .env
            
            if new_secrets_to_store:
                logger.info(f"Successfully added {len(new_secrets_to_store)} new secrets to Vault (kv/data/api-keys):")
                for key in new_secrets_to_store.keys():
                    logger.info(f"  - {key}")
            # No else needed, already logged "No new secrets to add" earlier
            return True
            
        except Exception as e:
            logger.error(f"Failed to add new secrets to Vault: {str(e)}")
            return False