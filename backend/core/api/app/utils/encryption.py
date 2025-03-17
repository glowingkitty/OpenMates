import base64
import os
import httpx
import json
import logging
import uuid
from typing import Tuple, Optional, Dict, Any

logger = logging.getLogger(__name__)

class EncryptionService:
    """
    Service for encrypting/decrypting sensitive user data using HashiCorp Vault
    """
    
    def __init__(self):
        self.vault_url = os.environ.get("VAULT_URL", "http://vault:8200")
        self.vault_token = os.environ.get("VAULT_TOKEN", "root")  # Should be configured securely in production
        self.transit_mount = "transit"  # The Vault transit engine mount path
        self._client = None
        # Remove dev mode check since we always use production mode
        logger.info("Running in PRODUCTION mode - Vault is using persistent storage")
    
    async def _get_client(self):
        """Get or create httpx client"""
        if not self._client:
            self._client = httpx.AsyncClient()
        return self._client
    
    async def _vault_request(self, method: str, path: str, data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make a request to the Vault API"""
        client = await self._get_client()
        url = f"{self.vault_url}/v1/{path}"
        headers = {"X-Vault-Token": self.vault_token}
        
        try:
            if method.lower() == "get":
                response = await client.get(url, headers=headers)
            else:  # POST
                response = await client.post(url, headers=headers, json=data)
            
            if response.status_code != 200:
                logger.error(f"Vault request failed: {response.status_code} - {response.text}")
                raise Exception(f"Vault request failed with status {response.status_code}")
            
            return response.json()
        except Exception as e:
            logger.error(f"Error in Vault request: {str(e)}")
            raise
    
    async def ensure_keys_exist(self):
        """Ensure encryption engine is enabled in Vault"""
        # Check if the transit engine is enabled
        try:
            # Try to read the transit mount info - will fail if not enabled
            await self._vault_request("get", f"sys/mounts/{self.transit_mount}")
            logger.info(f"Transit engine at '{self.transit_mount}' is enabled")
        except Exception:
            # Enable the transit engine
            logger.info(f"Enabling transit engine at '{self.transit_mount}'")
            await self._vault_request("post", "sys/mounts/transit", {
                "type": "transit",
                "description": "Encryption as a service for OpenMates"
            })
        
        # No pre-created keys needed since we create per-user and per-chat keys dynamically
        # Each user and chat will get their own unique encryption key
    
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
            
        # Use the user's specific key for encryption
        ciphertext, key_version = await self.encrypt(plaintext, key_name=key_id)
        
        return ciphertext, key_version
    
    async def decrypt_with_user_key(self, ciphertext: str, key_id: str) -> Optional[str]:
        """
        Decrypt ciphertext using user's specific Vault key
        """
        if not ciphertext or not key_id:
            return None
            
        # Use the user's specific key for decryption
        return await self.decrypt(ciphertext, key_name=key_id)
    
    async def encrypt(self, plaintext: str, key_name: str = "user_data") -> Tuple[str, str]:
        """
        Encrypt plaintext using Vault's transit engine
        Returns (ciphertext, key_version)
        """
        if not plaintext:
            return "", ""
            
        # Base64 encode the plaintext
        encoded = base64.b64encode(plaintext.encode()).decode("utf-8")
        
        # Send to Vault for encryption
        path = f"{self.transit_mount}/encrypt/{key_name}"
        payload = {"plaintext": encoded}
        
        try:
            result = await self._vault_request("post", path, payload)
            ciphertext = result["data"]["ciphertext"]
            # Extract key version from ciphertext (format is vault:v1:...)
            key_version = ciphertext.split(":")[1] if ":" in ciphertext else "v1"
            
            return ciphertext, key_version
        except Exception as e:
            logger.error(f"Encryption error: {str(e)}")
            raise
    
    async def decrypt(self, ciphertext: str, key_name: str = "user_data") -> Optional[str]:
        """
        Decrypt ciphertext using Vault's transit engine
        """
        if not ciphertext:
            return None
            
        # Send to Vault for decryption
        path = f"{self.transit_mount}/decrypt/{key_name}"
        payload = {"ciphertext": ciphertext}
        
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
            
        # Use the chat's specific key for encryption
        return await self.encrypt(plaintext, key_name=key_id)

    async def decrypt_with_chat_key(self, ciphertext: str, key_id: str) -> Optional[str]:
        """
        Decrypt ciphertext using chat's specific Vault key
        """
        if not ciphertext or not key_id:
            return None
            
        # Use the chat's specific key for decryption
        return await self.decrypt(ciphertext, key_name=key_id)
