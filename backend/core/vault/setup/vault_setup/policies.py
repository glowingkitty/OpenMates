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
        """Create the complete policy for the API service, including transit and KV access.
        
        Returns:
            True if successful, False otherwise
        """
        logger.info("Creating API service policy")
        
        # Define the complete policy with transit and KV permissions
        policy_hcl = """
        # API service policy for OpenMates
        
        # Allow managing the transit secrets engine
        path "transit/*" {
          capabilities = ["create", "read", "update", "delete", "list"]
        }
        
        # Allow managing transit keys
        path "transit/keys/*" {
          capabilities = ["create", "read", "update", "delete", "list"]
        }
        
        # Allow encrypting/decrypting with any key
        path "transit/encrypt/*" {
          capabilities = ["update"]
        }
        
        path "transit/decrypt/*" {
          capabilities = ["update"]
        }
        
        # Allow basic system access
        path "sys/mounts" {
          capabilities = ["read"]
        }
        
        path "sys/mounts/transit" {
          capabilities = ["create", "read", "update", "delete"]
        }

        # Allow API service to read secrets from KV store
        path "kv/data/*" {
          capabilities = ["read"]
        }
        """
        
        try:
            await self.client.vault_request("post", "sys/policies/acl/api-service", {
                "policy": policy_hcl
            })
            logger.info("API service policy created successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to create API service policy: {str(e)}")
            return False
    
    async def create_api_encryption_policy(self) -> bool:
        """Create a policy specifically for the API service's encryption needs.

        Returns:
            True if successful, False otherwise
        """
        logger.info("Creating API encryption policy")

        # Define policy with permissions needed by EncryptionService
        policy_hcl = """
        # API encryption policy for OpenMates

        # Allow creating/reading/managing user and chat keys
        path "transit/keys/user_*" {
          capabilities = ["create", "read", "update", "delete", "list"]
        }
        path "transit/keys/chat_*" {
          capabilities = ["create", "read", "update", "delete", "list"]
        }

        # Allow encrypting/decrypting with user and chat keys
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

        # Allow managing and using the email HMAC key
        path "transit/keys/email-hmac-key" {
          capabilities = ["create", "read", "update", "delete", "list"]
        }
        path "transit/hmac/email-hmac-key" {
          capabilities = ["update"] # 'update' is used for HMAC generation
        }

        # Allow reading mount info (needed by EncryptionService.ensure_keys_exist)
        path "sys/mounts/transit" {
           capabilities = ["read"]
        }
        """

        try:
            await self.client.vault_request("post", "sys/policies/acl/api-encryption", {
                "policy": policy_hcl
            })
            logger.info("API encryption policy created successfully")
            return True
        except Exception as e:
            # Handle potential race condition if policy already exists
            if "existing policy" in str(e).lower() or "already exists" in str(e).lower():
                 logger.info("API encryption policy already exists.")
                 return True
            logger.error(f"Failed to create API encryption policy: {str(e)}")
            return False
    