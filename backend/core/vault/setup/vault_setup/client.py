"""
Vault API client that handles connections and requests to the Vault server.
"""

import os
import httpx
import logging
import asyncio
from typing import Dict, Any, Optional, Union, Tuple

logger = logging.getLogger("vault-setup.client")

class VaultClient:
    """Client for interacting with the HashiCorp Vault HTTP API."""
    
    def __init__(self):
        """Initialize the Vault client with connection details."""
        self.vault_addr = os.environ.get("VAULT_ADDR", "http://vault:8200")
        self.vault_token = os.environ.get("VAULT_TOKEN", "root")
        self._client = None
        
    async def init_client(self):
        """Initialize the HTTP client."""
        self._client = httpx.AsyncClient(timeout=30.0)
    
    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            
    async def wait_for_vault(self, max_retries=120, retry_delay=5) -> Tuple[int, Dict[str, Any]]:
        """Wait for Vault to become available with verbose logging.
        
        Args:
            max_retries: Number of times to retry connecting to Vault.
            retry_delay: Number of seconds to wait between retries.
            
        Returns:
            Tuple of (status_code, response_json)
            
        Raises:
            Exception: If Vault doesn't become available within the timeout period.
        """
        logger.info("Waiting for Vault to become available...")
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    logger.info(f"Attempt {attempt+1}: Making request to Vault health endpoint")
                    response = await client.get(f"{self.vault_addr}/v1/sys/health", timeout=10.0)
                    
                    logger.info(f"Health check response: Status={response.status_code}, Text={response.text[:100]}")
                    
                    # Return status code to handle different Vault states
                    return response.status_code, response.json()
                    
            except Exception as e:
                logger.error(f"Vault not available (attempt {attempt+1}/{max_retries}): {str(e)}")
                
            if attempt < max_retries - 1:
                logger.info(f"Waiting {retry_delay} seconds before next attempt...")
                await asyncio.sleep(retry_delay)
        
        raise Exception("Vault did not become available within the timeout period")
    
    async def vault_request(self, method: str, path: str, data: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """Make a request to the Vault API.
        
        Args:
            method: HTTP method (get, post, etc.)
            path: API path relative to /v1/
            data: JSON data for POST/PUT requests
            
        Returns:
            Response JSON or None for 404 responses
            
        Raises:
            Exception: For request errors
        """
        url = f"{self.vault_addr}/v1/{path}"
        headers = {"X-Vault-Token": self.vault_token}
        
        try:
            if not self._client:
                await self.init_client()
                
            if method.lower() == "get":
                response = await self._client.get(url, headers=headers)
            elif method.lower() == "post":
                response = await self._client.post(url, headers=headers, json=data)
            else:
                response = await getattr(self._client, method.lower())(url, headers=headers, json=data)
            
            # Handle sealed state as a special case
            if response.status_code == 503 and "Vault is sealed" in response.text:
                logger.warning(f"Vault is sealed. Path: {path}")
                return {"sealed": True}

            response.raise_for_status()
            return response.json() if response.text else {}
        except httpx.HTTPStatusError as e:
            # Check if it's a 404 - sometimes expected when checking if something exists
            if e.response.status_code == 404:
                logger.debug(f"Resource not found: {path}")
                return None
            logger.error(f"HTTP error: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error in Vault request to {path}: {str(e)}")
            raise
    
    async def check_vault_status(self) -> Optional[Dict[str, Any]]:
        """Check Vault status and return status info.
        
        Returns:
            Status dictionary or None if there's an error
        """
        try:
            if not self._client:
                await self.init_client()
                
            response = await self._client.get(f"{self.vault_addr}/v1/sys/seal-status")
            response.raise_for_status()
            status = response.json()
            return status
        except Exception as e:
            logger.error(f"Error checking Vault status: {str(e)}")
            return None
    
    def update_token(self, token: str):
        """Update the token used for requests.
        
        Args:
            token: The new token to use
        """
        self.vault_token = token