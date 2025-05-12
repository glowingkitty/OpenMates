"""
Functions for managing Vault access policies.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("vault-setup.policies")

class PolicyManager:
    """Manages Vault access policies."""
    
    def __init__(self, vault_client):
        """Initialize with a vault client instance.
        
        Args:
            vault_client: The VaultClient instance
        """
        self.client = vault_client
        
    async def create_api_policy(self) -> bool:
        """Create the policy for general API service needs (KV, system).
        
        Returns:
            True if successful, False otherwise
        """
        logger.info("Creating API service policy (for KV and general system access)")
        
        # Define the policy for non-transit related API needs
        policy_hcl = """
        # API service policy for OpenMates (General - KV, System)

        # Allow reading system mount information
        path "sys/mounts" {
          capabilities = ["read"]
        }

        # Allow API service to read/write general secrets from KV store
        path "kv/data/system/*" { # More specific path for general system secrets if needed
          capabilities = ["read", "list"]
        }
        # Allow reading the specific api-keys secret path itself
        path "kv/data/api-keys" {
          capabilities = ["read"]
        }
        path "kv/data/api-keys/*" { # Path for API keys (redundant if above works, but safe to keep)
          capabilities = ["read", "list"]
        }

        # Allow API service to manage (CRUDL) user-specific raw AES keys for draft encryption
        path "kv/data/user-draft-aes-keys/*" {
          capabilities = ["create", "read", "update", "delete", "list"]
        }

        # Allow API service to manage (CRUDL) chat-specific raw AES keys
        path "kv/data/chat-aes-keys/*" {
          capabilities = ["create", "read", "update", "delete", "list"]
        }

        # Allow token self-lookup (important for token validation)
        path "auth/token/lookup-self" {
          capabilities = ["read"]
        }
        """
        
        try:
            await self.client.vault_request("post", "sys/policies/acl/api-service", {
                "policy": policy_hcl
            })
            logger.info("API service policy (api-service) created/updated successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to create API service policy (api-service): {str(e)}")
            return False
    
    async def create_api_encryption_policy(self) -> bool:
        """Create a comprehensive policy for all API service's encryption/transit needs.

        Returns:
            True if successful, False otherwise
        """
        logger.info("Creating API encryption policy (for all transit operations)")

        # Define policy with all permissions needed by EncryptionService for transit operations
        policy_hcl = """
        # API encryption policy for OpenMates (All Transit Needs)

        # Allow checking, enabling, and managing the transit secrets engine mount
        path "sys/mounts/transit" {
          capabilities = ["create", "read", "update", "delete"] # For enabling/disabling/reading config
        }

        # Allow managing (CRUDL) all keys under transit
        # This covers user_*, chat_*, email-hmac-key, and any future keys.
        path "transit/keys/*" {
          capabilities = ["create", "read", "update", "delete", "list"]
        }
        
        # Explicitly allow encrypt/decrypt for user_ and chat_ keys
        path "transit/encrypt/user_*" {
          capabilities = ["update"]
        }
        path "transit/decrypt/user_*" {
          capabilities = ["update"]
        }
        path "transit/encrypt/chat_*" {
          capabilities = ["update"]
        }
        path "transit/decrypt/chat_*" {
          capabilities = ["update"]
        }

        # Allow encrypt/decrypt operations for any other key under transit (fallback/general)
        path "transit/encrypt/*" {
          capabilities = ["update"]
        }
        path "transit/decrypt/*" {
          capabilities = ["update"]
        }

        # Allow HMAC operations for any key under transit (covers email-hmac-key)
        path "transit/hmac/*" {
          capabilities = ["update"]
        }
        """

        try:
            await self.client.vault_request("post", "sys/policies/acl/api-encryption", {
                "policy": policy_hcl
            })
            logger.info("API encryption policy (api-encryption) created/updated successfully")
            return True
        except Exception as e:
            # Handle potential race condition if policy already exists
            if "existing policy" in str(e).lower() or "already exists" in str(e).lower():
                 logger.info("API encryption policy (api-encryption) already exists.")
                 return True
            logger.error(f"Failed to create API encryption policy (api-encryption): {str(e)}")
            return False