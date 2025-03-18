import base64
import os
import httpx
import json
import logging
import uuid
import time
import glob
from typing import Tuple, Optional, Dict, Any

logger = logging.getLogger(__name__)

class EncryptionService:
    """
    Service for encrypting/decrypting sensitive user data using HashiCorp Vault
    """
    
    def __init__(self):
        self.vault_url = os.environ.get("VAULT_URL", "http://vault:8200")
        self.vault_token = os.environ.get("VAULT_TOKEN", "root") 
        self.transit_mount = "transit"  # The Vault transit engine mount path
        self._client = None
        
        # Path where vault-setup saves the root token - try multiple possible locations
        self.token_file_paths = [
            "/vault-data/root.token",       # Current mount point
            "/vault-data/api.token",        # Alternative file name
            "/app/data/root.token",         # Original path
        ]
        
        logger.info("EncryptionService initialized")
        logger.info(f"Vault URL: {self.vault_url}")
        
        # Log a masked version of the token for debugging
        if self.vault_token:
            masked_token = f"{self.vault_token[:4]}...{self.vault_token[-4:]}" if len(self.vault_token) >= 8 else "****"
            logger.info(f"Using Vault token from environment: {masked_token}")
        else:
            logger.warning("No Vault token provided in environment")
            
        # Try to get token from file immediately on initialization
        file_token = self._get_token_from_file()
        if file_token:
            self.vault_token = file_token
            masked_token = f"{self.vault_token[:4]}...{self.vault_token[-4:]}" if len(self.vault_token) >= 8 else "****"
            logger.info(f"Updated token from file on init: {masked_token}")
    
    async def _get_client(self):
        """Get or create httpx client"""
        if not self._client:
            self._client = httpx.AsyncClient(timeout=30.0)  # Increase timeout for reliability
        return self._client
    
    def _get_token_from_file(self):
        """Try to read the token from the file created by vault-setup"""
        for token_path in self.token_file_paths:
            try:
                logger.debug(f"Looking for token file at {token_path}")
                if os.path.exists(token_path):
                    logger.info(f"Token file found at {token_path}")
                    
                    with open(token_path, 'r') as f:
                        token = f.read().strip()
                        
                    if token:
                        masked_token = f"{token[:4]}...{token[-4:]}" if len(token) >= 8 else "****"
                        logger.info(f"Retrieved token from file: {masked_token}")
                        return token
                    else:
                        logger.warning(f"Token file at {token_path} is empty")
                        
            except Exception as e:
                logger.error(f"Failed to read token from {token_path}: {str(e)}")
        
        # If we get here, check if the directory exists and list contents for debugging
        for directory in set(os.path.dirname(p) for p in self.token_file_paths):
            if os.path.exists(directory):
                logger.info(f"Directory {directory} exists. Contents: {os.listdir(directory)}")
            else:
                logger.warning(f"Directory {directory} does not exist")
                
        logger.error("Could not find a valid token file in any of the expected locations")
        return None
    
    async def _validate_token(self):
        """Validate if the current token is valid and has the necessary permissions"""
        try:
            # Always try to get the token from file first in case it was just created
            file_token = self._get_token_from_file()
            if file_token and file_token != self.vault_token:
                logger.info("Found newer token in file, updating")
                self.vault_token = file_token
            
            client = await self._get_client()
            url = f"{self.vault_url}/v1/auth/token/lookup-self"
            headers = {"X-Vault-Token": self.vault_token}
            
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                token_info = response.json().get("data", {})
                logger.info(f"Vault token is valid. Policies: {token_info.get('policies', [])}")
                return True
            
            logger.warning(f"Vault token validation failed: {response.status_code} - {response.text}")
            
            # If the current token failed, try to get a fresh one from the file
            file_token = self._get_token_from_file()
            if file_token and file_token != self.vault_token:
                logger.info("Trying token from file instead")
                self.vault_token = file_token
                
                # Try again with the new token
                headers = {"X-Vault-Token": self.vault_token}
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    token_info = response.json().get("data", {})
                    logger.info(f"Token from file is valid. Policies: {token_info.get('policies', [])}")
                    return True
                
                logger.warning(f"Token from file also failed: {response.status_code} - {response.text}")
            
            return False
        except Exception as e:
            logger.error(f"Error validating Vault token: {str(e)}")
            return False
    
    async def wait_for_valid_token(self, max_attempts=30, delay=2):
        """Wait for a valid token to become available"""
        logger.info(f"Waiting for valid Vault token (max {max_attempts} attempts, {delay}s delay)")
        
        for attempt in range(max_attempts):
            # Try to get token from file
            file_token = self._get_token_from_file()
            if file_token:
                self.vault_token = file_token
                
                if await self._validate_token():
                    logger.info(f"Found valid token after {attempt+1} attempts")
                    return True
            
            logger.info(f"No valid token found (attempt {attempt+1}/{max_attempts}), waiting {delay}s...")
            time.sleep(delay)
        
        logger.error(f"Failed to find valid token after {max_attempts} attempts")
        return False
    
    async def _vault_request(self, method: str, path: str, data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make a request to the Vault API with enhanced error handling and retry logic"""
        client = await self._get_client()
        url = f"{self.vault_url}/v1/{path}"
        
        # Wait for a valid token if this is our first request
        if not hasattr(self, '_token_validated') or not self._token_validated:
            await self.wait_for_valid_token()
            self._token_validated = True
        
        headers = {"X-Vault-Token": self.vault_token}
        
        # Validate token before making the actual request
        if not await self._validate_token():
            logger.error("Cannot proceed with Vault request - invalid token")
            raise Exception("Invalid Vault token")
        
        try:
            # Make the request
            if method.lower() == "get":
                response = await client.get(url, headers=headers)
            else:  # POST
                response = await client.post(url, headers=headers, json=data)
            
            # Check for common error statuses
            if response.status_code == 403:
                logger.error(f"Vault permission denied: {response.text}")
                raise Exception(f"Permission denied in Vault: {path}")
            elif response.status_code == 404:
                # Not necessarily an error if checking if something exists
                logger.warning(f"Vault resource not found: {path}")
                return {"data": {}}
            elif response.status_code != 200:
                logger.error(f"Vault request failed: {response.status_code} - {response.text}")
                raise Exception(f"Vault request failed with status {response.status_code}")
            
            return response.json()
        except Exception as e:
            logger.error(f"Error in Vault request: {str(e)}")
            raise
    
    async def ensure_keys_exist(self):
        """Ensure encryption engine is enabled in Vault with improved error handling"""
        # Check if the transit engine is enabled
        try:
            # Try to read the transit mount info - will fail if not enabled
            try:
                await self._vault_request("get", f"sys/mounts/{self.transit_mount}")
                logger.info(f"Transit engine at '{self.transit_mount}' is enabled")
            except Exception as e:
                # If the error is not just 404, re-raise
                if "404" not in str(e) and "not found" not in str(e).lower():
                    logger.error(f"Error checking transit engine: {str(e)}")
                    raise
                
                # Enable the transit engine
                logger.info(f"Enabling transit engine at '{self.transit_mount}'")
                try:
                    await self._vault_request("post", "sys/mounts/transit", {
                        "type": "transit",
                        "description": "Encryption as a service for OpenMates"
                    })
                    logger.info(f"Successfully enabled transit engine")
                except Exception as mount_error:
                    # Check if it's already mounted (race condition)
                    if "already in use" in str(mount_error).lower():
                        logger.info(f"Transit engine was already mounted by another process")
                    else:
                        raise
        except Exception as e:
            logger.error(f"Failed to ensure transit engine is enabled: {str(e)}")
            raise Exception(f"Failed to initialize encryption service: {str(e)}")
    
    async def create_user_key(self, user_id: str) -> str:
        """
        Create a user-specific encryption key in Vault
        Returns the key ID used in Vault
        """
        # Generate a unique key ID for this user
        key_id = f"user_{uuid.uuid4().hex}"
        
        try:
            # Create a dedicated encryption key for this user in Vault
            await self._vault_request("post", f"{self.transit_mount}/keys/{key_id}", {
                "type": "aes256-gcm96",  # AES with GCM mode for authenticated encryption
                "derived": True  # Derive encryption key from a combination of the key and context
            })
            logger.info(f"Created user-specific encryption key: {key_id}")
            return key_id
        except Exception as e:
            logger.error(f"Error creating user key: {str(e)}")
            raise
    
    async def encrypt_with_user_key(self, plaintext: str, key_id: str) -> Tuple[str, str]:
        """
        Encrypt plaintext using user's specific Vault key
        Returns (ciphertext, key_version)
        
        The key_version is now used as a single version field for all encrypted data
        """
        if not plaintext or not key_id:
            return "", ""
            
        # Use a consistent context for this key - the key_id itself works well
        context = base64.b64encode(key_id.encode()).decode("utf-8")
        
        # Use the user's specific key for encryption with context
        ciphertext, key_version = await self.encrypt(plaintext, key_name=key_id, context=context)
        
        return ciphertext, key_version
    
    async def decrypt_with_user_key(self, ciphertext: str, key_id: str) -> Optional[str]:
        """
        Decrypt ciphertext using user's specific Vault key
        """
        if not ciphertext or not key_id:
            return None
            
        # Use the same context as encryption - must be consistent!
        context = base64.b64encode(key_id.encode()).decode("utf-8")
        
        # Use the user's specific key for decryption with context
        return await self.decrypt(ciphertext, key_name=key_id, context=context)
    
    async def encrypt(self, plaintext: str, key_name: str = "user_data", context: str = None) -> Tuple[str, str]:
        """
        Encrypt plaintext using Vault's transit engine
        Returns (ciphertext, key_version)
        
        If the key is a derived key, context must be provided
        """
        if not plaintext:
            return "", ""
            
        # Base64 encode the plaintext
        encoded = base64.b64encode(plaintext.encode()).decode("utf-8")
        
        # Send to Vault for encryption
        path = f"{self.transit_mount}/encrypt/{key_name}"
        payload = {"plaintext": encoded}
        
        # Add context for derived keys
        if context:
            payload["context"] = context
        
        try:
            result = await self._vault_request("post", path, payload)
            ciphertext = result["data"]["ciphertext"]
            # Extract key version from ciphertext (format is vault:v1:...)
            key_version = ciphertext.split(":")[1] if ":" in ciphertext else "v1"
            
            return ciphertext, key_version
        except Exception as e:
            logger.error(f"Encryption error: {str(e)}")
            raise
    
    async def decrypt(self, ciphertext: str, key_name: str = "user_data", context: str = None) -> Optional[str]:
        """
        Decrypt ciphertext using Vault's transit engine
        
        If the key is a derived key, context must be provided
        """
        if not ciphertext:
            return None
            
        # Send to Vault for decryption
        path = f"{self.transit_mount}/decrypt/{key_name}"
        payload = {"ciphertext": ciphertext}
        
        # Add context for derived keys
        if context:
            payload["context"] = context
        
        try:
            result = await self._vault_request("post", path, payload)
            decoded = base64.b64decode(result["data"]["plaintext"]).decode("utf-8")
            return decoded
        except Exception as e:
            logger.error(f"Decryption error: {str(e)}")
            return None
    
    async def close(self):
        """Close the HTTP client"""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def create_chat_key(self, key_id: str) -> bool:
        """
        Create a chat-specific encryption key in Vault
        """
        try:
            # Create the key in Vault's transit engine
            await self._vault_request("post", f"{self.transit_mount}/keys/{key_id}", {
                "type": "aes256-gcm96",
                "derived": True
            })
            logger.info(f"Created chat-specific encryption key: {key_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to create chat key {key_id}: {str(e)}")
            return False

    async def encrypt_with_chat_key(self, plaintext: str, key_id: str) -> Tuple[str, str]:
        """
        Encrypt plaintext using chat's specific Vault key
        Returns (ciphertext, key_version)
        """
        if not plaintext or not key_id:
            return "", ""
            
        # Use consistent context for chat keys too
        context = base64.b64encode(key_id.encode()).decode("utf-8")
        
        # Use the chat's specific key for encryption
        return await self.encrypt(plaintext, key_name=key_id, context=context)

    async def decrypt_with_chat_key(self, ciphertext: str, key_id: str) -> Optional[str]:
        """
        Decrypt ciphertext using chat's specific Vault key
        """
        if not ciphertext or not key_id:
            return None
            
        # Use consistent context for chat keys
        context = base64.b64encode(key_id.encode()).decode("utf-8")
        
        # Use the chat's specific key for decryption
        return await self.decrypt(ciphertext, key_name=key_id, context=context)
