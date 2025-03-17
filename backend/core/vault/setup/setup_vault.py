#!/usr/bin/env python3
import os
import httpx
import asyncio
import logging
import json
import sys
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger("vault-setup")

class VaultSetup:
    def __init__(self):
        self.vault_addr = os.environ.get("VAULT_ADDR", "http://vault:8200")
        self.vault_token = os.environ.get("VAULT_TOKEN", "root")
        # Remove the dev mode flag since we always use production mode
        self.client = None
        
    async def init_client(self):
        self.client = httpx.AsyncClient()
    
    async def close(self):
        if self.client:
            await self.client.aclose()
            
    async def wait_for_vault(self, max_retries=120, retry_delay=5):
        """Wait for Vault to become available with verbose logging"""
        logger.info("Waiting for Vault to become available...")
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    # Just try a basic health check first
                    logger.info(f"Attempt {attempt+1}: Making request to Vault health endpoint")
                    response = await client.get(f"{self.vault_addr}/v1/sys/health", timeout=10.0)
                    
                    logger.info(f"Health check response: Status={response.status_code}, Text={response.text[:100]}")
                    
                    # Accept any response as valid for debugging purposes
                    return response.status_code
                    
            except Exception as e:
                logger.error(f"Vault not available (attempt {attempt+1}/{max_retries}): {str(e)}")
                
            if attempt < max_retries - 1:
                logger.info(f"Waiting {retry_delay} seconds before next attempt...")
                await asyncio.sleep(retry_delay)
        
        raise Exception("Vault did not become available within the timeout period")
    
    async def vault_request(self, method, path, data=None):
        url = f"{self.vault_addr}/v1/{path}"
        headers = {"X-Vault-Token": self.vault_token}
        
        try:
            if method.lower() == "get":
                response = await self.client.get(url, headers=headers)
            elif method.lower() == "post":
                response = await self.client.post(url, headers=headers, json=data)
            else:
                response = await getattr(self.client, method.lower())(url, headers=headers, json=data)
            
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
    
    async def check_transit_engine(self):
        """Check if transit engine is enabled"""
        try:
            result = await self.vault_request("get", "sys/mounts")
            return "transit/" in result["data"]
        except Exception:
            return False
    
    async def enable_transit_engine(self):
        """Enable the transit secrets engine"""
        logger.info("Enabling transit secrets engine")
        await self.vault_request("post", "sys/mounts/transit", {
            "type": "transit",
            "description": "Encryption as a service for OpenMates"
        })
        logger.info("Transit secrets engine enabled")
    
    async def initialize_vault(self):
        """Initialize Vault if not already initialized"""
        try:
            # Check if Vault is already initialized
            response = await self.client.get(f"{self.vault_addr}/v1/sys/init")
            response.raise_for_status()
            
            init_status = response.json()
            if init_status.get("initialized", False):
                logger.info("Vault is already initialized")
                return
                
            # Initialize Vault
            logger.info("Initializing Vault...")
            init_response = await self.client.post(
                f"{self.vault_addr}/v1/sys/init",
                json={
                    "secret_shares": 1,     # For production, use multiple shares (e.g. 5)
                    "secret_threshold": 1   # For production, use a threshold (e.g. 3)
                }
            )
            init_response.raise_for_status()
            
            credentials = init_response.json()
            
            # IMPORTANT: In a real production environment, these credentials should be
            # securely stored and distributed to trusted administrators
            logger.info("Vault initialized successfully!")
            logger.warning("SAVE THESE KEYS - they will not be shown again!")
            logger.warning(f"Unseal Key: {credentials['keys'][0]}")
            logger.warning(f"Root Token: {credentials['root_token']}")
            
            # Update the root token
            self.vault_token = credentials['root_token']
            
            # Unseal Vault
            await self.unseal_vault(credentials['keys'][0])
            
        except Exception as e:
            logger.error(f"Failed to initialize Vault: {str(e)}")
            raise
    
    async def unseal_vault(self, unseal_key):
        """Unseal Vault if it's sealed"""
        try:
            # Check seal status
            response = await self.client.get(f"{self.vault_addr}/v1/sys/seal-status")
            response.raise_for_status()
            
            seal_status = response.json()
            if not seal_status.get("sealed", True):
                logger.info("Vault is already unsealed")
                return
                
            # Unseal vault
            logger.info("Unsealing Vault...")
            unseal_response = await self.client.post(
                f"{self.vault_addr}/v1/sys/unseal",
                json={"key": unseal_key}
            )
            unseal_response.raise_for_status()
            
            logger.info("Vault unsealed successfully")
            
        except Exception as e:
            logger.error(f"Failed to unseal Vault: {str(e)}")
            raise
    
    async def setup(self):
        """Main setup routine"""
        try:
            await self.init_client()
            
            # Wait for Vault to become available
            status_code = await self.wait_for_vault()
            
            # If Vault is not initialized, initialize it
            if status_code == 501:
                await self.initialize_vault()
                
            # Check and enable transit engine if needed
            if not await self.check_transit_engine():
                await self.enable_transit_engine()
            else:
                logger.info("Transit secrets engine is already enabled")
            
            logger.info("Vault setup completed successfully")
            
        except Exception as e:
            logger.error(f"Vault setup failed: {str(e)}")
            sys.exit(1)
        finally:
            await self.close()

async def main():
    setup = VaultSetup()
    await setup.setup()

if __name__ == "__main__":
    asyncio.run(main())
