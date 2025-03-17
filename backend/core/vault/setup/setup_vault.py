#!/usr/bin/env python3
import os
import httpx
import asyncio
import logging
import sys
import time
import pathlib
import stat

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
        self.client = None
        self.unseal_key_file = "/app/data/unseal.key"
        self.token_file = "/app/data/root.token"  # Add file for token storage
        self.auto_unseal = os.environ.get("VAULT_AUTO_UNSEAL", "true").lower() == "true"
        
    async def init_client(self):
        self.client = httpx.AsyncClient(timeout=30.0)
    
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
                    
                    # Return status code to handle different Vault states
                    return response.status_code, response.json()
                    
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
    
    async def check_transit_engine(self):
        """Check if transit engine is enabled"""
        try:
            result = await self.vault_request("get", "sys/mounts")
            # If we got a sealed response, return False to trigger enabling later
            if result and result.get("sealed"):
                return False
            return "transit/" in result.get("data", {})
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
    
    async def check_vault_status(self):
        """Check Vault status and return status info"""
        try:
            response = await self.client.get(f"{self.vault_addr}/v1/sys/seal-status")
            response.raise_for_status()
            status = response.json()
            return status
        except Exception as e:
            logger.error(f"Error checking Vault status: {str(e)}")
            return None

    async def create_api_policy(self):
        """Create a policy specifically for the API service"""
        logger.info("Creating API service policy")
        
        # Define policy with appropriate permissions
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
        """
        
        try:
            await self.vault_request("post", "sys/policies/acl/api-service", {
                "policy": policy_hcl
            })
            logger.info("API service policy created successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to create API service policy: {str(e)}")
            return False
    
    async def create_api_token(self):
        """Create a token for the API service with appropriate policies"""
        logger.info("Creating API service token")
        
        try:
            # Create a token with the api-service policy
            result = await self.vault_request("post", "auth/token/create", {
                "policies": ["api-service", "root"],  # Include root for development simplicity
                "display_name": "api-service-token",
                "ttl": "768h",  # 32 days
                "renewable": True
            })
            
            token = result["auth"]["client_token"]
            # Mask token for logging - only show beginning and end
            masked_token = f"{token[:4]}...{token[-4:]}" if len(token) >= 8 else "****"
            logger.info(f"API service token created successfully: {masked_token}")
            
            # Output ONLY the API token clearly - this is the ONLY token needed
            print("\n" + "="*80)
            print("VAULT TOKEN - ADD THIS TO YOUR .ENV FILE")
            print("="*80)
            print(f"VAULT_ROOT_TOKEN={token}")
            print("="*80)
            
            return token
        except Exception as e:
            logger.error(f"Failed to create API service token: {str(e)}")
            return None
    
    def save_unseal_key(self, unseal_key):
        """Save unseal key to a restricted access file"""
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(self.unseal_key_file), exist_ok=True)
            
            # Write key to file
            with open(self.unseal_key_file, 'w') as f:
                f.write(unseal_key)
            
            # Set restrictive permissions (600 - owner read/write only)
            os.chmod(self.unseal_key_file, stat.S_IRUSR | stat.S_IWUSR)
            
            logger.info("Saved unseal key for auto-unsealing")
            return True
        except Exception as e:
            logger.error(f"Failed to save unseal key: {str(e)}")
            return False
    
    def save_root_token(self, root_token):
        """Save root token to a restricted access file"""
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(self.token_file), exist_ok=True)
            
            # Write token to file
            with open(self.token_file, 'w') as f:
                f.write(root_token)
            
            # Set restrictive permissions (600 - owner read/write only)
            os.chmod(self.token_file, stat.S_IRUSR | stat.S_IWUSR)
            
            logger.info("Saved root token")
            return True
        except Exception as e:
            logger.error(f"Failed to save root token: {str(e)}")
            return False
    
    def get_saved_unseal_key(self):
        """Get saved unseal key if available"""
        try:
            if os.path.exists(self.unseal_key_file):
                with open(self.unseal_key_file, 'r') as f:
                    unseal_key = f.read().strip()
                logger.info("Retrieved saved unseal key")
                return unseal_key
            return None
        except Exception as e:
            logger.error(f"Failed to read unseal key: {str(e)}")
            return None
    
    def get_saved_root_token(self):
        """Get saved root token if available"""
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, 'r') as f:
                    token = f.read().strip()
                masked_token = f"{token[:4]}...{token[-4:]}" if len(token) >= 8 else "****"
                logger.info(f"Retrieved saved root token: {masked_token}")
                return token
            return None
        except Exception as e:
            logger.error(f"Failed to read root token: {str(e)}")
            return None
    
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
                    "secret_shares": 1,     # For development, just a single share
                    "secret_threshold": 1   
                }
            )
            init_response.raise_for_status()
            
            credentials = init_response.json()
            
            # Store the keys for future use
            root_token = credentials['root_token']
            unseal_key = credentials['keys'][0]
            
            # Save both the unseal key and root token
            self.save_unseal_key(unseal_key)
            self.save_root_token(root_token)
            
            # Display the keys clearly for manual backup
            print("\n" + "="*80)
            print("VAULT INITIALIZED")
            print("="*80)
            print("ROOT TOKEN: " + root_token)
            print("UNSEAL KEY: " + unseal_key)
            print("\nIMPORTANT: Save these values securely! You will need them if auto-unsealing fails.")
            print("The unseal key has been saved for auto-unsealing.")
            print("="*80 + "\n")
            
            # Update the root token in the current session
            self.vault_token = root_token
            
            # Unseal Vault
            await self.unseal_vault(unseal_key)
            
        except Exception as e:
            logger.error(f"Failed to initialize Vault: {str(e)}")
            raise
    
    async def unseal_vault(self, unseal_key=None):
        """Unseal Vault if it's sealed."""
        try:
            # Check seal status
            response = await self.client.get(f"{self.vault_addr}/v1/sys/seal-status")
            response.raise_for_status()
            
            seal_status = response.json()
            if not seal_status.get("sealed", True):
                logger.info("Vault is already unsealed")
                return True
            
            if not unseal_key:
                # Try to get from saved file first
                unseal_key = self.get_saved_unseal_key()
                
            if not unseal_key:
                # If still no key, report the error
                logger.error("No unseal key provided or found - cannot unseal Vault")
                print("\n" + "="*80)
                print("VAULT IS SEALED - MANUAL UNSEALING REQUIRED")
                print("="*80)
                print("No unseal key found. You need to manually unseal Vault:")
                print("1. Get your unseal key")
                print("2. Run: docker exec -it vault vault operator unseal <key>")
                print("3. Or set VAULT_AUTO_UNSEAL=false if you prefer manual unsealing")
                print("="*80 + "\n")
                return False
                
            # Unseal vault
            logger.info("Unsealing Vault...")
            unseal_response = await self.client.post(
                f"{self.vault_addr}/v1/sys/unseal",
                json={"key": unseal_key}
            )
            unseal_response.raise_for_status()
            
            # Verify it's unsealed
            result = unseal_response.json()
            if not result.get("sealed", True):
                logger.info("Vault unsealed successfully")
                
                # Try to load the saved root token
                saved_token = self.get_saved_root_token()
                if saved_token:
                    logger.info("Updating token after unsealing")
                    self.vault_token = saved_token
                
                return True
            else:
                logger.warning("Vault is still sealed after unseal attempt")
                return False
            
        except Exception as e:
            logger.error(f"Failed to unseal Vault: {str(e)}")
            return False
    
    async def setup(self):
        """Main setup routine"""
        try:
            await self.init_client()
            
            # Wait for Vault to become available
            status_code, health_data = await self.wait_for_vault()
            
            # If Vault is not initialized, initialize it
            if not health_data.get("initialized", False):
                logger.info("Vault needs to be initialized")
                await self.initialize_vault()
            elif health_data.get("sealed", True):
                # Vault is initialized but sealed - try auto unsealing
                logger.info("Vault is sealed, attempting auto-unseal")
                if not self.auto_unseal:
                    logger.info("Auto-unsealing disabled, skipping")
                elif not await self.unseal_vault():
                    # Only exit if auto-unsealing is enabled but failed
                    logger.error("Auto-unsealing failed")
                    sys.exit(1)
            
            # Check and enable transit engine if needed
            if not await self.check_transit_engine():
                await self.enable_transit_engine()
            else:
                logger.info("Transit secrets engine is already enabled")
            
            # Create API service policy
            await self.create_api_policy()
            
            # Create token for API service
            api_token = await self.create_api_token()
            if not api_token:
                logger.error("Failed to create API token")
                sys.exit(1)
            
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
