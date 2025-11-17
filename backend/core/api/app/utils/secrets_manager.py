"""
Secrets Manager for accessing API keys and other secrets from Vault.

This module provides a utility for retrieving secrets from HashiCorp Vault
instead of environment variables. It should be used for all sensitive data
that was previously stored in .env files.
"""

import os
import logging
import httpx
from typing import Optional, Dict, Any
import asyncio

logger = logging.getLogger(__name__)

class SecretsManager:
    """
    A utility for retrieving secrets from HashiCorp Vault.
    
    This class provides methods to access secrets that were previously stored
    in environment variables but now are securely stored in Vault.
    
    Uses singleton pattern per process to avoid redundant initialization
    and reduce memory usage across multiple tasks in the same worker process.
    """
    _instance = None
    _initialized = False
    
    def __new__(cls, cache_service=None):
        """Singleton pattern: return the same instance for all calls within a process."""
        if cls._instance is None:
            cls._instance = super(SecretsManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, cache_service=None):
        """Initialize the SecretsManager with Vault connection details."""
        # Only initialize once per process (singleton pattern)
        if self._initialized:
            # Update cache_service if provided and different
            if cache_service is not None and self.cache != cache_service:
                self.cache = cache_service
            return
            
        self.vault_url = os.environ.get("VAULT_URL")
        self.cache = cache_service
        self.token_path = "/vault-data/api.token"
        
        # Initialize vault_token to None - will be set during initialize()
        # This prevents AttributeError if methods are called before initialize()
        self.vault_token = None

        # Cache settings
        self._cache_ttl = 300  # 5 minutes
        # Cache structure: { "vault_path/secret_key": {"value": "...", "expires": ...} }
        self._secrets_cache = {}
        self._initialized = True
            
    def _get_token_from_file(self) -> Optional[str]:
        """
        Try to read the token from the file created by vault-setup.
        
        Returns:
            The token string if found, None otherwise
        """
        try:
            if os.path.exists(self.token_path):
                with open(self.token_path, 'r') as f:
                    token = f.read().strip()
                    if token:
                        logger.debug(f"Token loaded from file: {self.token_path}")
                        return token
        except Exception as e:
            logger.error(f"Error reading token from {self.token_path}: {str(e)}")
        
        return None
    
    async def initialize(self):
        """
        Initialize the secrets manager and validate Vault connection.
        
        Attempts to get the Vault token from:
        1. Environment variable VAULT_TOKEN
        2. Token file at /vault-data/api.token
        
        If no token is found, Vault operations will fail gracefully.
        """
        # Try to get token from environment variable first
        env_token = os.environ.get("VAULT_TOKEN")
        if env_token:
            self.vault_token = env_token.strip()
            masked_token = f"{self.vault_token[:4]}...{self.vault_token[-4:]}" if len(self.vault_token) >= 8 else "****"
            logger.info(f"Using Vault token from environment variable: {masked_token}")
        else:
            # Try to get token from file if not provided in env
            file_token = self._get_token_from_file()
            if file_token:
                self.vault_token = file_token
                masked_token = f"{self.vault_token[:4]}...{self.vault_token[-4:]}" if len(self.vault_token) >= 8 else "****"
                logger.info(f"Using token from file for Vault authentication: {masked_token}")
        
        # If no token was found, log warning and skip validation
        if not self.vault_token:
            logger.warning("No Vault token found in environment variable VAULT_TOKEN or token file. Vault operations will fail. This is expected if Vault is not configured.")
            return False
        
        # If vault_url is not set, skip validation
        if not self.vault_url:
            logger.warning("VAULT_URL environment variable not set. Vault operations will fail. This is expected if Vault is not configured.")
            return False
        
        # Try to validate connection to Vault
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.vault_url}/v1/sys/health",
                    headers={"X-Vault-Token": self.vault_token}
                )
            
            if response.status_code == 200:
                logger.info("Successfully connected to Vault and Vault is healthy.")
                # No longer fetching all secrets during initialization
                return True
            else:
                logger.warning(f"Connection to Vault returned status code: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to connect to Vault: {str(e)}", exc_info=True)
            return False
    
    async def _vault_request(self, method: str, path: str, data: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Make a request to the Vault API.
        
        Args:
            method: HTTP method (get, post, etc.)
            path: Vault API path (e.g., "kv/data/providers/brave")
            data: Optional data for POST requests
            
        Returns:
            Response JSON data
            
        Raises:
            ValueError: If vault_token or vault_url is not set
            httpx.HTTPStatusError: If the HTTP request fails
        """
        # Validate that vault_token and vault_url are set
        if not self.vault_token:
            raise ValueError("Vault token not set. Call initialize() first or set VAULT_TOKEN environment variable.")
        if not self.vault_url:
            raise ValueError("VAULT_URL environment variable not set. Cannot make Vault requests.")
        
        url = f"{self.vault_url}/v1/{path}"
        headers = {"X-Vault-Token": self.vault_token}
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
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
    
    async def get_secret(self, secret_path: str, secret_key: str) -> Optional[str]:
        """
        Get a specific secret key from a given path in Vault.

        Args:
            secret_path: The path in Vault where the secret is stored (e.g., "kv/data/providers/google").
                         This path should be the full path for the KV v2 engine,
                         typically starting with "kv/data/".
            secret_key: The key of the secret within that path (e.g., "api_key").

        Returns:
            The secret value or None if not found or on error.
        """
        cache_full_key = f"{secret_path}/{secret_key}"

        # Check cache first
        cached_item = self._secrets_cache.get(cache_full_key)
        if cached_item and cached_item["expires"] > asyncio.get_event_loop().time():
            logger.debug(f"Returning cached secret for {cache_full_key}")
            return cached_item["value"]

        try:
            logger.debug(f"Fetching secret from Vault: path='{secret_path}', key='{secret_key}'")

            response_data = await self._vault_request("get", secret_path)

            if response_data and "data" in response_data and "data" in response_data["data"]:
                secrets_at_path = response_data["data"]["data"]
                if secret_key in secrets_at_path:
                    secret_value = secrets_at_path[secret_key]
                    
                    # Log masked secret for debugging
                    if secret_value and isinstance(secret_value, str):
                        masked_secret = f"{secret_value[:4]}****{secret_value[-4:]}" if len(secret_value) > 8 else "****"
                        logger.info(f"Successfully loaded secret '{secret_key}' from path '{secret_path}': {masked_secret}")
                    elif secret_value is not None: # Handle non-string secrets if any, though typically they are strings
                        logger.info(f"Successfully loaded secret '{secret_key}' from path '{secret_path}' (non-string or empty value)")
                    else:
                        logger.info(f"Successfully loaded secret '{secret_key}' from path '{secret_path}' (empty value)")

                    # Cache the secret
                    self._secrets_cache[cache_full_key] = {
                        "value": secret_value,
                        "expires": asyncio.get_event_loop().time() + self._cache_ttl
                    }
                    return secret_value
                else:
                    logger.warning(f"Secret key '{secret_key}' not found at path '{secret_path}' in Vault.")
            else:
                logger.warning(f"No data found at path '{secret_path}' in Vault, or data format is unexpected. Response: {response_data}")
            
            return None

        except Exception as e:
            logger.error(f"Error retrieving secret key '{secret_key}' from path '{secret_path}' in Vault: {e}", exc_info=True)
            return None

    async def get_secrets_from_path(self, secret_path: str) -> Optional[Dict[str, Any]]:
        """
        Get all secrets (key-value pairs) from a given path in Vault.
        This is useful if a service needs multiple keys from the same Vault path.

        Args:
            secret_path: The path in Vault (e.g., "kv/data/providers/google").

        Returns:
            A dictionary of secrets or None if path not found or on error.
        """
        try:
            logger.debug(f"Fetching all secrets from Vault path: '{secret_path}'")
            response_data = await self._vault_request("get", secret_path)

            if response_data and "data" in response_data and "data" in response_data["data"]:
                secrets = response_data["data"]["data"]
                now = asyncio.get_event_loop().time()
                for key, value in secrets.items():
                    cache_full_key = f"{secret_path}/{key}"
                    self._secrets_cache[cache_full_key] = {
                        "value": value,
                        "expires": now + self._cache_ttl
                    }
                    if value and isinstance(value, str):
                        masked_secret = f"{value[:4]}****{value[-4:]}" if len(value) > 8 else "****"
                        logger.info(f"Loaded and cached secret '{key}' from path '{secret_path}': {masked_secret}")
                    else:
                        logger.info(f"Loaded and cached secret '{key}' from path '{secret_path}' (non-string or empty value)")
                logger.info(f"Successfully loaded {len(secrets)} secrets from path '{secret_path}'.")
                return secrets
            else:
                logger.warning(f"No data found at path '{secret_path}' in Vault, or data format is unexpected. Response: {response_data}")
            
            return None
        except Exception as e:
            logger.error(f"Error retrieving all secrets from path '{secret_path}' in Vault: {e}", exc_info=True)
            return None
            
    async def close(self):
        """Close the HTTP client."""
        pass
