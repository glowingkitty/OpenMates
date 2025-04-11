"""
Functions for managing Vault secret engines.
"""

import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger("vault-setup.engines")

class SecretEngines:
    """Manages Vault secret engines (transit, KV, etc.)."""
    
    def __init__(self, vault_client):
        """Initialize with a vault client instance.
        
        Args:
            vault_client: The VaultClient instance
        """
        self.client = vault_client
        
    async def check_transit_engine(self) -> bool:
        """Check if transit engine is enabled.
        
        Returns:
            True if enabled, False otherwise
        """
        try:
            result = await self.client.vault_request("get", "sys/mounts")
            # If we got a sealed response, return False to trigger enabling later
            if result and result.get("sealed"):
                return False
            return "transit/" in result.get("data", {})
        except Exception as e:
            logger.error(f"Error checking transit engine: {str(e)}")
            return False
    
    async def enable_transit_engine(self) -> bool:
        """Enable the transit secrets engine.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info("Enabling transit secrets engine")
            await self.client.vault_request("post", "sys/mounts/transit", {
                "type": "transit",
                "description": "Encryption as a service for OpenMates"
            })
            logger.info("Transit secrets engine enabled")
            return True
        except Exception as e:
            logger.error(f"Failed to enable transit engine: {str(e)}")
            return False
    
    async def enable_kv_engine(self) -> bool:
        """Enable the KV secrets engine for storing API keys and other secrets.
        
        Returns:
            True if successful or already enabled, False otherwise
        """
        logger.info("Checking KV v2 secrets engine")
        try:
            # Check if already enabled
            mounts = await self.client.vault_request("get", "sys/mounts")
            if mounts and "kv/" in mounts.get("data", {}):
                logger.info("KV secrets engine is already enabled")
                return True
                
            # Enable KV v2 engine
            logger.info("Enabling KV v2 secrets engine")
            await self.client.vault_request("post", "sys/mounts/kv", {
                "type": "kv",
                "options": {"version": "2"},
                "description": "KV store for OpenMates API keys and secrets"
            })
            logger.info("KV v2 secrets engine enabled")
            return True
        except Exception as e:
            logger.error(f"Failed to enable KV secrets engine: {str(e)}")
            return False