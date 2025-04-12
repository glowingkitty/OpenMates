"""
Secrets Manager for accessing API keys and other secrets from Vault.

This module provides a utility for retrieving secrets from HashiCorp Vault
instead of environment variables. It should be used for all sensitive data
that was previously stored in .env files.
"""

import os
import logging
import httpx
from typing import Optional, Dict, Any, List
import asyncio

logger = logging.getLogger(__name__)

class SecretsManager:
    """
    A utility for retrieving secrets from HashiCorp Vault.
    
    This class provides methods to access secrets that were previously stored
    in environment variables but now are securely stored in Vault.
    """
    
    def __init__(self, cache_service=None):
        """Initialize the SecretsManager with Vault connection details."""
        self.vault_url = os.environ.get("VAULT_URL", "http://vault:8200")
        self.vault_token = os.environ.get("VAULT_TOKEN", "root")
        self._client = None
        self.cache = cache_service
        
        # Path where vault-setup saves the token
        self.token_file_paths = [
            "/vault-data/root.token",
            "/vault-data/api.token",
            "/app/data/root.token",
        ]
        
        # Cache settings
        self._cache_ttl = 300  # 5 minutes
        self._secrets_cache = {}
        
    async def _get_client(self):
        """Get or create httpx client."""
        if not self._client:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client
            
    def _get_token_from_file(self):
        """Try to read the token from the file created by vault-setup."""
        for path in self.token_file_paths:
            try:
                if os.path.exists(path):
                    with open(path, 'r') as f:
                        token = f.read().strip()
                        logger.debug(f"Token loaded from file: {path}")
                        return token
            except Exception as e:
                logger.error(f"Error reading token from {path}: {str(e)}")
        return None
    
    async def initialize(self):
        """Initialize the secrets manager and validate Vault connection."""
        # Try to get token from file if not provided in env
        file_token = self._get_token_from_file()
        if file_token:
            self.vault_token = file_token
            masked_token = f"{self.vault_token[:4]}...{self.vault_token[-4:]}" if len(self.vault_token) >= 8 else "****"
            logger.info(f"Using token from file for Vault authentication: {masked_token}")
        
        # Try to validate connection to Vault
        try:
            client = await self._get_client()
            response = await client.get(
                f"{self.vault_url}/v1/sys/health",
                headers={"X-Vault-Token": self.vault_token}
            )
            
            if response.status_code == 200:
                logger.info("Successfully connected to Vault")
                # Fetch and log all secrets during initialization
                await self.get_all_secrets()
                return True
            else:
                logger.warning(f"Connection to Vault returned status code: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to connect to Vault: {str(e)}")
            return False
    
    async def _vault_request(self, method: str, path: str, data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make a request to the Vault API."""
        url = f"{self.vault_url}/v1/{path}"
        headers = {"X-Vault-Token": self.vault_token}
        
        try:
            client = await self._get_client()
            
            if method.lower() == "get":
                response = await client.get(url, headers=headers)
            elif method.lower() == "post":
                response = await client.post(url, headers=headers, json=data)
            else:
                response = await getattr(client, method.lower())(url, headers=headers, json=data)
                
            response.raise_for_status()
            return response.json() if response.text else {}
            
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code} in Vault request to {path}: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error in Vault request to {path}: {str(e)}")
            raise
    
    async def get_secret(self, key: str) -> Optional[str]:
        """
        Get a secret from Vault.
        
        Args:
            key: The key of the secret to retrieve (corresponds to environment variable name)
            
        Returns:
            The secret value or None if not found
        """
        # Check cache first
        if key in self._secrets_cache and self._secrets_cache[key]["expires"] > asyncio.get_event_loop().time():
            return self._secrets_cache[key]["value"]
        
        # No longer use environment variables - always get from Vault
        try:
            # Get the secret from the KV store
            response = await self._vault_request("get", "kv/data/api-keys")
            
            if response and "data" in response and "data" in response["data"]:
                secrets = response["data"]["data"]
                if key in secrets:
                    secret_value = secrets[key]
                    # Log masked secret for debugging
                    if secret_value:
                        masked_secret = f"{secret_value[0]}****" if len(secret_value) < 6 else f"{secret_value[:4]}****"
                        logger.info(f"Loaded secret '{key}': {masked_secret}")
                    else:
                        logger.info(f"Loaded secret '{key}': (empty value)")
                        
                    # Cache the secret
                    self._secrets_cache[key] = {
                        "value": secret_value,
                        "expires": asyncio.get_event_loop().time() + self._cache_ttl
                    }
                    return secret_value
            
            # If we get here, the secret was not found in Vault
            logger.warning(f"Secret not found in Vault: {key}")
            
            # Check if environment has the variable with IMPORTED_TO_VAULT value,
            # which indicates it should be in Vault but wasn't found
            env_value = os.environ.get(key)
            if env_value == "IMPORTED_TO_VAULT":
                logger.error(f"Secret {key} was marked as imported to Vault but not found there!")
            
            return None
            
        except Exception as e:
            logger.error(f"Error retrieving secret from Vault: {str(e)}")
            return None
    
    async def get_all_secrets(self) -> Dict[str, Any]:
        """
        Get all secrets from Vault.
        
        Returns:
            A dictionary of all secrets stored in Vault
        """
        try:
            # Try to get all secrets from the KV store
            response = await self._vault_request("get", "kv/data/api-keys")
            
            if response and "data" in response and "data" in response["data"]:
                secrets = response["data"]["data"]
                
                # Cache all secrets
                now = asyncio.get_event_loop().time()
                for key, value in secrets.items():
                    # Log masked secret for debugging
                    if value:
                        masked_secret = f"{value[0]}****" if len(value) < 6 else f"{value[:4]}****"
                        logger.info(f"Loaded secret '{key}': {masked_secret}")
                    else:
                         logger.info(f"Loaded secret '{key}': (empty value)")

                    self._secrets_cache[key] = {
                        "value": value,
                        "expires": now + self._cache_ttl
                    }
                
                logger.debug(f"Retrieved {len(secrets)} secrets from Vault")
                return secrets
            
            logger.warning("No secrets found in Vault")
            return {}
            
        except Exception as e:
            logger.error(f"Error retrieving secrets from Vault: {str(e)}")
            return {}
            
    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()