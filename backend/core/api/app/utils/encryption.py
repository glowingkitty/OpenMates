import base64
import os
import httpx
import json
import logging
import uuid
import time
import glob
import secrets  # Added
import hmac     # Added
import hashlib  # Added
from typing import Tuple, Optional, Dict, Any

logger = logging.getLogger(__name__)

# Vault path and key name for the email hashing key
EMAIL_HASH_KEY_PATH = "secret/data/keys/email_hash"
EMAIL_HASH_KEY_NAME = "EMAIL_HASH_KEY"

class EncryptionService:
    """
    Service for encrypting/decrypting sensitive user data using HashiCorp Vault
    """
    
    def __init__(self, cache_service=None):
        self.vault_url = os.environ.get("VAULT_URL", "http://vault:8200")
        self.vault_token = os.environ.get("VAULT_TOKEN", "root") 
        self.transit_mount = "transit"  # The Vault transit engine mount path
        self._client = None
        self.cache = cache_service  # Store the cache service
        self.email_hash_key: Optional[str] = None # Added: Store the loaded email hash key

        # Add caching properties
        self._token_valid_until = 0  # Token validation expiry timestamp
        self._token_validation_ttl = 300  # Cache token validation for 5 minutes
        
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
            logger.debug(f"Updated token from file on init: {masked_token}")
    
    async def _get_client(self):
        """Get or create httpx client"""
        if not self._client:
            self._client = httpx.AsyncClient(timeout=30.0)  # Increase timeout for reliability
        return self._client
    
    def _get_token_from_file(self):
        """Try to read the token from the file created by vault-setup"""
        # Check if we have a cached token
        if hasattr(self, '_cached_file_token') and self._cached_file_token:
            return self._cached_file_token
            
        for token_path in self.token_file_paths:
            try:
                logger.debug(f"Looking for token file at {token_path}")
                if os.path.exists(token_path):
                    logger.debug(f"Token file found at {token_path}")
                    
                    with open(token_path, 'r') as f:
                        token = f.read().strip()
                        
                    if token:
                        masked_token = f"{token[:4]}...{token[-4:]}" if len(token) >= 8 else "****"
                        logger.debug(f"Retrieved token from file: {masked_token}")
                        # Cache the token in memory
                        self._cached_file_token = token
                        return token
                    else:
                        logger.warning(f"Token file at {token_path} is empty")
                        
            except Exception as e:
                logger.error(f"Failed to read token from {token_path}: {str(e)}")
        
        # If we get here, check if the directory exists and list contents for debugging
        for directory in set(os.path.dirname(p) for p in self.token_file_paths):
            if os.path.exists(directory):
                logger.debug(f"Directory {directory} exists. Contents: {os.listdir(directory)}")
            else:
                logger.warning(f"Directory {directory} does not exist")
                
        logger.error("Could not find a valid token file in any of the expected locations")
        return None
    
    async def _validate_token(self):
        """Validate if the current token is valid and has the necessary permissions"""
        # Check if we have a cached validation result
        current_time = time.time()
        if self._token_valid_until > current_time:
            logger.debug("Using cached token validation result")
            return True
            
        try:
            # Always try to get the token from file first in case it was just created
            file_token = self._get_token_from_file()
            if file_token and file_token != self.vault_token:
                logger.debug("Found newer token in file, updating")
                self.vault_token = file_token
            
            client = await self._get_client()
            url = f"{self.vault_url}/v1/auth/token/lookup-self"
            headers = {"X-Vault-Token": self.vault_token}
            
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                token_info = response.json().get("data", {})
                logger.debug(f"Vault token is valid. Policies: {token_info.get('policies', [])}")
                # Cache the validation result
                self._token_valid_until = current_time + self._token_validation_ttl
                return True
            
            logger.warning(f"Vault token validation failed: {response.status_code}")
            
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
                    logger.debug(f"Token from file is valid. Policies: {token_info.get('policies', [])}")
                    # Cache the validation result
                    self._token_valid_until = current_time + self._token_validation_ttl
                    return True
                
                logger.warning(f"Token from file also failed: {response.status_code}")
            
            # Reset the validation timestamp
            self._token_valid_until = 0
            return False
        except Exception as e:
            logger.error(f"Error validating Vault token: {str(e)}")
            # Reset the validation timestamp
            self._token_valid_until = 0
            return False
    
    async def wait_for_valid_token(self, max_attempts=30, delay=2):
        """Wait for a valid token to become available"""
        logger.debug(f"Waiting for valid Vault token (max {max_attempts} attempts, {delay}s delay)")
        
        # Check if we already have a valid token (based on cached result)
        current_time = time.time()
        if self._token_valid_until > current_time:
            logger.debug("Using cached valid token")
            return True
            
        for attempt in range(max_attempts):
            # Try to get token from file
            file_token = self._get_token_from_file()
            if file_token:
                self.vault_token = file_token
                
                if await self._validate_token():
                    logger.debug(f"Found valid token after {attempt+1} attempts")
                    return True
            
            logger.debug(f"No valid token found (attempt {attempt+1}/{max_attempts}), waiting {delay}s...")
            time.sleep(delay)
        
        logger.error(f"Failed to find valid token after {max_attempts} attempts")
        return False
    
    async def _vault_request(self, method: str, path: str, data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make a request to the Vault API with enhanced error handling and retry logic"""
        client = await self._get_client()
        url = f"{self.vault_url}/v1/{path}"
        
        # Only do full validation if we don't have a cached result
        current_time = time.time()
        if self._token_valid_until <= current_time:
            # This will use the cached result if available
            if not await self._validate_token():
                logger.error("Cannot proceed with Vault request - invalid token")
                raise Exception("Invalid Vault token")
        
        headers = {"X-Vault-Token": self.vault_token}
        
        try:
            # Make the request
            if method.lower() == "get":
                response = await client.get(url, headers=headers)
            else:  # POST
                response = await client.post(url, headers=headers, json=data)
            
            # Check for common error statuses
            if response.status_code == 403:
                logger.error(f"Vault permission denied: {response.text}")
                # Reset token validation cache on permission error
                self._token_valid_until = 0
                raise Exception(f"Permission denied in Vault: {path}")
            elif response.status_code == 404:
                # Not necessarily an error if checking if something exists
                logger.debug(f"Vault resource not found: {path}")
                return {"data": {}}
            elif response.status_code == 401:
                logger.warning(f"Vault token expired or invalid")
                # Reset token validation cache
                self._token_valid_until = 0
                raise Exception(f"Vault token is expired or invalid")
            elif response.status_code != 200:
                logger.error(f"Vault request failed: {response.status_code}")
                raise Exception(f"Vault request failed with status {response.status_code}")
            
            return response.json()
        except Exception as e:
            logger.error(f"Error in Vault request: {str(e)}")
            raise
    
    # Initialize token specifically at startup
    async def initialize(self):
        """Initialize the encryption service at startup"""
        logger.info("Initializing encryption service")
        # Get and validate token
        file_token = self._get_token_from_file()
        if file_token:
            self.vault_token = file_token
        
        # Validate the token and cache the result
        valid = await self._validate_token()
        if valid:
            logger.info("Encryption service successfully initialized with valid token")
            return True
        else:
            logger.warning("Failed to initialize encryption service with valid token")
            return False
    
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

        # --- Add logic for EMAIL_HASH_KEY ---
        try:
            logger.info(f"Checking for email hash key in Vault at {EMAIL_HASH_KEY_PATH}")
            # Try reading the key from Vault KV v2
            response = await self._vault_request("get", EMAIL_HASH_KEY_PATH)
            
            if response and 'data' in response and 'data' in response['data'] and EMAIL_HASH_KEY_NAME in response['data']['data']:
                self.email_hash_key = response['data']['data'][EMAIL_HASH_KEY_NAME]
                logger.info("Successfully loaded email hash key from Vault.")
            else:
                logger.warning(f"Email hash key not found in Vault at {EMAIL_HASH_KEY_PATH}. Generating a new one.")
                # Generate a new secure key
                new_key = secrets.token_hex(32)
                
                # Write the new key to Vault KV v2
                write_payload = {"data": {EMAIL_HASH_KEY_NAME: new_key}}
                await self._vault_request("post", EMAIL_HASH_KEY_PATH, data=write_payload)
                
                self.email_hash_key = new_key
                logger.info(f"Successfully generated and stored new email hash key in Vault.")

        except Exception as e:
            logger.error(f"Failed to ensure email hash key exists in Vault: {str(e)}")
            # Depending on policy, we might want to raise an exception here to prevent startup
            raise Exception(f"Failed to initialize email hash key: {str(e)}")

        if not self.email_hash_key:
             logger.critical("Email hash key could not be loaded or generated. Hashing will fail.")
             raise Exception("Email hash key initialization failed.")
    
    def get_email_hash_key(self) -> str:
        """Returns the loaded email hash key. Raises error if not loaded."""
        if not self.email_hash_key:
            logger.error("Email hash key accessed before it was loaded!")
            raise ValueError("Email hash key has not been loaded from Vault.")
        return self.email_hash_key

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
            logger.info(f"Created user-specific encryption key.")
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
            logger.info(f"Created chat-specific encryption key.")
            return True
        except Exception as e:
            logger.error(f"Failed to create chat key: {str(e)}")
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

    # --- Added Hashing Methods ---

    def hash_email(self, email: str) -> str:
        """
        Creates a consistent HMAC-SHA256 hash of an email address using the key from Vault.
        """
        if not email:
            return ""
            
        # Normalize email to lowercase
        normalized_email = email.strip().lower()
        
        # Get the key (raises error if not loaded)
        key = self.get_email_hash_key() 
        
        # Create the HMAC hash
        hash_obj = hmac.new(
            key=key.encode('utf-8'),
            msg=normalized_email.encode('utf-8'),
            digestmod=hashlib.sha256
        )
        
        # Return hex digest
        return hash_obj.hexdigest()

    def verify_email_hash(self, email: str, stored_hash: str) -> bool:
        """
        Verifies if a plaintext email matches a stored hash using the key from Vault.
        """
        if not email or not stored_hash:
            return False
        return hmac.compare_digest(self.hash_email(email), stored_hash)
