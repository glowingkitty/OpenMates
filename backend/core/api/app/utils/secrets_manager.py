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
import time

logger = logging.getLogger(__name__)

class SecretsManager:
    """
    A utility for retrieving secrets from HashiCorp Vault.
    
    This class provides methods to access secrets that were previously stored
    in environment variables but now are securely stored in Vault.
    
    Uses singleton pattern per process to avoid redundant initialization
    and reduce memory usage across multiple tasks in the same worker process.
    
    IMPORTANT: When used in Celery tasks with asyncio.run(), call aclose() 
    before the async function returns to prevent "Event loop is closed" errors
    during httpx client cleanup.
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
        
        # Token validation cache settings (similar to EncryptionService)
        self._token_valid_until = 0  # Token validation expiry timestamp
        self._token_validation_ttl = 300  # Cache token validation for 5 minutes
        
        # Shared httpx client for Vault requests - prevents "Event loop is closed" errors
        # by keeping a single client that can be explicitly closed with aclose()
        self._http_client: Optional[httpx.AsyncClient] = None
        
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
        
        # Try to validate connection to Vault using the shared httpx client
        try:
            client = await self._get_http_client()
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
    
    async def _validate_token(self) -> bool:
        """
        Validate if the current token is valid and has the necessary permissions.
        Attempts to refresh token from file if validation fails.
        
        Returns:
            True if token is valid, False otherwise
        """
        # Check if we have a cached validation result
        current_time = time.time()
        if self._token_valid_until > current_time:
            logger.debug("Using cached token validation result")
            return True
        
        try:
            # Always try to get the token from file first in case it was just created/updated
            file_token = self._get_token_from_file()
            if file_token and file_token != self.vault_token:
                logger.debug("Found newer token in file, updating")
                self.vault_token = file_token
            
            if not self.vault_token:
                logger.warning("No Vault token available for validation")
                return False
            
            url = f"{self.vault_url}/v1/auth/token/lookup-self"
            headers = {"X-Vault-Token": self.vault_token}
            
            # Use the shared httpx client to prevent "Event loop is closed" errors
            client = await self._get_http_client()
            response = await client.get(url, headers=headers)
            
            if response.status_code == 200:
                token_info = response.json().get("data", {})
                current_token_display = f"{self.vault_token[:4]}...{self.vault_token[-4:]}" if self.vault_token and len(self.vault_token) >= 8 else "****"
                logger.debug(f"_validate_token: Current token {current_token_display} is valid. Policies: {token_info.get('policies', [])}")
                # Cache the validation result
                self._token_valid_until = current_time + self._token_validation_ttl
                return True
            
            current_token_display = f"{self.vault_token[:4]}...{self.vault_token[-4:]}" if self.vault_token and len(self.vault_token) >= 8 else "****"
            logger.warning(f"_validate_token: Current token {current_token_display} validation failed: {response.status_code} - {response.text}")
            
            # If the current token failed, try to get a fresh one from the file
            logger.debug("_validate_token: Attempting to refresh token from file.")
            file_token = self._get_token_from_file()
            if file_token and file_token != self.vault_token:
                logger.debug("_validate_token: Found different token in file. Updating and retrying validation.")
                self.vault_token = file_token
                
                # Try again with the new token using the shared client
                new_token_display = f"{self.vault_token[:4]}...{self.vault_token[-4:]}" if self.vault_token and len(self.vault_token) >= 8 else "****"
                headers = {"X-Vault-Token": self.vault_token}
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    token_info = response.json().get("data", {})
                    logger.debug(f"_validate_token: Token from file {new_token_display} is now valid. Policies: {token_info.get('policies', [])}")
                    # Cache the validation result
                    self._token_valid_until = current_time + self._token_validation_ttl
                    return True
                
                logger.warning(f"_validate_token: Token from file {new_token_display} also failed validation: {response.status_code} - {response.text}")
            elif file_token and file_token == self.vault_token:
                logger.debug("_validate_token: Token from file is the same as current token, which failed validation.")
            elif not file_token:
                logger.warning("_validate_token: Could not retrieve any token from file to retry.")
            
            # Reset the validation timestamp
            self._token_valid_until = 0
            return False
        except Exception as e:
            logger.error(f"Error validating Vault token: {str(e)}")
            # Reset the validation timestamp
            self._token_valid_until = 0
            return False
    
    async def _refresh_token_on_error(self) -> bool:
        """
        Attempt to refresh the token from file when an authentication error occurs.
        
        Returns:
            True if token was refreshed, False otherwise
        """
        logger.debug("Attempting to refresh token from file due to authentication error")
        file_token = self._get_token_from_file()
        if file_token and file_token != self.vault_token:
            logger.info("Found updated token in file, refreshing")
            self.vault_token = file_token
            # Reset validation cache to force re-validation
            self._token_valid_until = 0
            return True
        return False
    
    async def _vault_request(self, method: str, path: str, data: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Make a request to the Vault API with automatic token refresh on 403 errors.
        
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
        
        # Validate token before making request (uses cached result if available)
        current_time = time.time()
        if self._token_valid_until <= current_time:
            if not await self._validate_token():
                raise ValueError("Vault token is invalid. Cannot make Vault requests.")
        
        url = f"{self.vault_url}/v1/{path}"
        headers = {"X-Vault-Token": self.vault_token}
        
        try:
            # Use the shared httpx client to prevent "Event loop is closed" errors
            # when using asyncio.run() in Celery tasks
            client = await self._get_http_client()
            if method.lower() == "get":
                response = await client.get(url, headers=headers)
            elif method.lower() == "post":
                response = await client.post(url, headers=headers, json=data)
            else:
                response = await getattr(client, method.lower())(url, headers=headers, json=data)
                
            response.raise_for_status()
            return response.json() if response.text else {}
        except httpx.HTTPStatusError as e:
            # Handle 403 (Forbidden) - token might be expired or invalid
            if e.response.status_code == 403:
                logger.warning(f"Vault returned 403 Forbidden for {path}. Attempting to refresh token...")
                # Reset validation cache
                self._token_valid_until = 0
                # Try to refresh token from file
                if await self._refresh_token_on_error():
                    # Retry the request once with the new token using the shared client
                    logger.debug(f"Retrying Vault request to {path} with refreshed token")
                    headers = {"X-Vault-Token": self.vault_token}
                    client = await self._get_http_client()
                    if method.lower() == "get":
                        response = await client.get(url, headers=headers)
                    elif method.lower() == "post":
                        response = await client.post(url, headers=headers, json=data)
                    else:
                        response = await getattr(client, method.lower())(url, headers=headers, json=data)
                    response.raise_for_status()
                    return response.json() if response.text else {}
                else:
                    logger.error(f"HTTP error 403 in Vault request to {path}: {e.response.text}")
            # 404 is expected when a secret path hasn't been created yet (e.g., env secrets not imported into Vault).
            # Keep logs quiet for 404 to avoid noisy stack traces in normal setup flows.
            elif e.response.status_code == 404:
                logger.debug(f"Vault path not found (404): {path}")
            else:
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

        except httpx.HTTPStatusError as e:
            # Common setup case: the provider path doesn't exist yet.
            if e.response.status_code == 404:
                provider_id = None
                if secret_path.startswith("kv/data/providers/"):
                    provider_id = secret_path.split("kv/data/providers/", 1)[1].strip("/") or None

                suggested_env = None
                if provider_id:
                    suggested_env = f"SECRET__{provider_id.upper()}__{secret_key.upper()}"

                if suggested_env:
                    logger.warning(
                        f"Vault secret not found at '{secret_path}' (key '{secret_key}'). "
                        f"Add `{suggested_env}` to your environment (see `.env.example`) so it can be imported into Vault."
                    )
                else:
                    logger.warning(
                        f"Vault secret not found at '{secret_path}' (key '{secret_key}'). "
                        f"Add an appropriate `SECRET__...` env var (see `.env.example`) so it can be imported into Vault."
                    )
                return None

            logger.error(
                f"HTTP error {e.response.status_code} retrieving secret key '{secret_key}' from path '{secret_path}' in Vault: {e}",
                exc_info=True,
            )
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
            
    async def _get_http_client(self) -> httpx.AsyncClient:
        """
        Get or create the shared httpx client for Vault requests.
        
        Using a shared client instead of creating new ones for each request
        prevents "Event loop is closed" errors when using asyncio.run() in
        Celery tasks. The client is kept alive for the duration of the async
        context and should be explicitly closed with aclose() before returning.
        
        Returns:
            httpx.AsyncClient: The shared HTTP client instance
        """
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=30.0)
            logger.debug("Created new shared httpx client for Vault requests")
        return self._http_client
    
    async def aclose(self):
        """
        Explicitly close the httpx client to prevent "Event loop is closed" errors.
        
        IMPORTANT: Call this method before returning from async functions that are
        executed with asyncio.run() (e.g., in Celery tasks). This ensures the httpx
        client's cleanup tasks complete while the event loop is still running.
        
        The method includes a small sleep after closing to allow httpx's internal
        connection pool cleanup tasks to complete before asyncio.run() closes the
        event loop. Without this, background cleanup tasks can fail with
        "Event loop is closed" errors.
        
        Example usage in a Celery task:
            async def _async_task():
                secrets_manager = SecretsManager()
                await secrets_manager.initialize()
                try:
                    # ... do work ...
                finally:
                    await secrets_manager.aclose()
        """
        if self._http_client is not None and not self._http_client.is_closed:
            try:
                await self._http_client.aclose()
                logger.debug("Closed shared httpx client for Vault requests")
                # CRITICAL: Allow pending httpx cleanup tasks to complete
                # httpx.AsyncClient.aclose() schedules background tasks for connection
                # pool cleanup. If we return immediately, asyncio.run() closes the event
                # loop before these tasks finish, causing "Event loop is closed" errors.
                # A small sleep ensures these background tasks have time to complete.
                await asyncio.sleep(0.1)
            except Exception as e:
                # Log but don't raise - cleanup errors shouldn't break the task
                logger.warning(f"Error closing httpx client: {e}")
            finally:
                self._http_client = None
    
    async def close(self):
        """
        Close the HTTP client. Alias for aclose() for backwards compatibility.
        
        Deprecated: Use aclose() instead for explicit async cleanup.
        """
        await self.aclose()
