import base64
import os
import httpx
import logging
import uuid
import time
import hmac
from typing import Tuple, Optional, Dict, Any, Union

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidTag

logger = logging.getLogger(__name__)

# Vault transit key name for email HMAC
EMAIL_HMAC_KEY_NAME = "email-hmac-key"
# Vault transit key name for creator income encryption
# This is a system-level key used to encrypt creator income credit amounts
CREATOR_INCOME_ENCRYPTION_KEY = "creator_income"
# Vault transit key name for newsletter email encryption
# This is a system-level key used to encrypt newsletter subscriber email addresses
NEWSLETTER_ENCRYPTION_KEY = "newsletter_emails"
# Vault transit key name for support payment receipt encryption
# This is a system-level key used to wrap support receipt AES keys for archival in S3.
SUPPORT_PAYMENTS_ENCRYPTION_KEY = "support_payments"
# Note: All chat and draft encryption now happens client-side
# Server-side encryption methods removed for zero-knowledge architecture

class EncryptionService:
    """
    Service for encrypting/decrypting sensitive user data using HashiCorp Vault
    """
    
    def __init__(self, cache_service=None):
        self.vault_url = os.environ.get("VAULT_URL")
        self.transit_mount = "transit"  # The Vault transit engine mount path
        self.cache = cache_service

        # Add caching properties
        self._token_valid_until = 0  # Token validation expiry timestamp
        self._token_validation_ttl = 300  # Cache token validation for 5 minutes
        
        # Path where vault-setup saves the root token - try multiple possible locations
        self.token_path = "/vault-data/api.token"
        
        # Multiple possible token file paths for testing compatibility
        self.token_file_paths = [
            "/vault-data/api.token",
            "/tmp/vault-token",
            os.path.expanduser("~/.vault-token"),
            "./vault-token"
        ]
        
        logger.debug("EncryptionService initialized")
        logger.debug(f"Vault URL: {self.vault_url}")
            
        # Try to get token from file immediately on initialization
        file_token = self._get_token_from_file()
        if file_token:
            self.vault_token = file_token
            masked_token = f"{self.vault_token[:4]}...{self.vault_token[-4:]}" if len(self.vault_token) >= 8 else "****"
            logger.debug(f"EncryptionService.__init__: Loaded token from file: {masked_token}")
        else:
            logger.warning("EncryptionService.__init__: No token loaded from file on initialization.")
            self.vault_token = os.environ.get("VAULT_TOKEN") # Fallback to env var if file load fails
            if self.vault_token:
                logger.debug(f"EncryptionService.__init__: Loaded token from VAULT_TOKEN env var: {self.vault_token[:4]}...{self.vault_token[-4:] if len(self.vault_token) >=8 else '****'}")
            else:
                logger.error("EncryptionService.__init__: CRITICAL - NO VAULT TOKEN LOADED from file or VAULT_TOKEN env var.")
    
    def _get_token_from_file(self):
        """Try to read the token from the file created by vault-setup"""
        # Check if we have a cached token
        if hasattr(self, '_cached_file_token') and self._cached_file_token:
            return self._cached_file_token
            
        try:
            logger.debug(f"Looking for token file at {self.token_path}")
            if os.path.exists(self.token_path):
                logger.debug(f"Token file found at {self.token_path}")
                
                with open(self.token_path, 'r') as f:
                    token = f.read().strip()
                    
                if token:
                    masked_token = f"{token[:4]}...{token[-4:]}" if len(token) >= 8 else "****"
                    logger.debug(f"_get_token_from_file: Retrieved token from {self.token_path}: {masked_token}")
                    # Cache the token in memory
                    self._cached_file_token = token
                    return token
                else:
                    logger.warning(f"Token file at {self.token_path} is empty")
                    
        except Exception as e:
            logger.error(f"Failed to read token from {self.token_path}: {str(e)}")
        
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
            
            url = f"{self.vault_url}/v1/auth/token/lookup-self"
            headers = {"X-Vault-Token": self.vault_token}
            
            async with httpx.AsyncClient(timeout=30.0) as client:
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
            file_token = self._get_token_from_file() # This will log if it finds a token
            if file_token and file_token != self.vault_token:
                logger.debug(f"_validate_token: Found different token in file. Old: {current_token_display}, New from file: {file_token[:4]}...{file_token[-4:] if len(file_token) >= 8 else '****'}. Updating and retrying validation.")
                self.vault_token = file_token
                
                # Try again with the new token
                new_token_display = f"{self.vault_token[:4]}...{self.vault_token[-4:]}" if self.vault_token and len(self.vault_token) >= 8 else "****"
                headers = {"X-Vault-Token": self.vault_token}
                async with httpx.AsyncClient(timeout=30.0) as client:
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
        url = f"{self.vault_url}/v1/{path}"
        
        # Only do full validation if we don't have a cached result
        current_time = time.time()
        if self._token_valid_until <= current_time:
            # This will use the cached result if available
            if not await self._validate_token():
                logger.error("Cannot proceed with Vault request - invalid token")
                raise Exception("Invalid Vault token")
        
        active_token_display = f"{self.vault_token[:4]}...{self.vault_token[-4:]}" if self.vault_token and len(self.vault_token) >= 8 else "****"
        logger.debug(f"_vault_request: Making {method.upper()} request to {path} using token {active_token_display}")
        headers = {"X-Vault-Token": self.vault_token}
        
        try:
            # Make the request using a context manager
            async with httpx.AsyncClient(timeout=30.0) as client:
                if method.lower() == "get":
                    response = await client.get(url, headers=headers)
                else:  # POST
                    response = await client.post(url, headers=headers, json=data)
            
            # Check for common error statuses
            if response.status_code == 403:
                logger.error(f"Vault permission denied for {method.upper()} on {path}. Response: {response.text}")
                # Reset token validation cache on permission error
                self._token_valid_until = 0
                raise Exception(f"Permission denied in Vault for {method.upper()} on {path}")
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
                logger.error(
                    f"Vault request failed: {response.status_code} for {method.upper()} {path}. Response: {response.text}"
                )
                raise Exception(f"Vault request failed with status {response.status_code}")
            
            return response.json()
        except Exception as e:
            logger.error(f"Error in Vault request: {str(e)}")
            raise
    
    # Initialize token specifically at startup
    async def initialize(self):
        """Initialize the encryption service at startup"""
        logger.debug("Initializing encryption service")
        # Get and validate token
        file_token = self._get_token_from_file()
        if file_token:
            self.vault_token = file_token
        
        # Validate the token and cache the result
        valid = await self._validate_token()
        if valid:
            logger.debug("Encryption service successfully initialized with valid token")
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
                logger.debug(f"Transit engine at '{self.transit_mount}' is enabled")
            except Exception as e:
                # If the error is not just 404, re-raise
                if "404" not in str(e) and "not found" not in str(e).lower():
                    logger.error(f"Error checking transit engine: {str(e)}")
                    raise
                
                # Enable the transit engine
                logger.debug(f"Enabling transit engine at '{self.transit_mount}'")
                try:
                    await self._vault_request("post", "sys/mounts/transit", {
                        "type": "transit",
                        "description": "Encryption as a service for OpenMates"
                    })
                    logger.debug(f"Successfully enabled transit engine")
                except Exception as mount_error:
                    # Check if it's already mounted (race condition)
                    if "already in use" in str(mount_error).lower():
                        logger.debug(f"Transit engine was already mounted by another process")
                    else:
                        raise
        except Exception as e:
            logger.error(f"Failed to ensure transit engine is enabled: {str(e)}")
            raise Exception(f"Failed to initialize encryption service: {str(e)}")

        # --- Ensure EMAIL_HMAC_KEY exists in transit engine ---
        try:
            logger.debug(f"Checking for email HMAC key '{EMAIL_HMAC_KEY_NAME}' in transit engine...")
            key_exists = False
            try:
                # Check if key exists by attempting to read its configuration
                response = await self._vault_request("get", f"{self.transit_mount}/keys/{EMAIL_HMAC_KEY_NAME}")
                # If the response has data (not just the default {"data": {}} from 404 handling), the key exists.
                # Check specifically for a field that indicates existence, like 'type' or 'name'.
                if response and response.get("data") and response["data"].get("name") == EMAIL_HMAC_KEY_NAME:
                    key_exists = True
                    logger.debug(f"Email HMAC key '{EMAIL_HMAC_KEY_NAME}' already exists.")
                else:
                    # This case handles 404 or unexpected empty data
                    logger.debug(f"Email HMAC key '{EMAIL_HMAC_KEY_NAME}' not found.")
            except Exception as e:
                 # Log error during check, but proceed assuming key might not exist
                 logger.warning(f"Error checking for email HMAC key '{EMAIL_HMAC_KEY_NAME}': {str(e)}. Assuming it might not exist.")
                 key_exists = False # Ensure we try to create if check failed

            # If key does not exist, create it
            if not key_exists:
                 logger.debug(f"Attempting to create email HMAC key '{EMAIL_HMAC_KEY_NAME}'...")
                 try:
                     # Create the key
                     await self._vault_request("post", f"{self.transit_mount}/keys/{EMAIL_HMAC_KEY_NAME}", {
                         "type": "aes256-gcm96", # Can use standard encryption key type for HMAC
                         "allow_plaintext_backup": False # Good practice
                     })
                     logger.debug(f"Successfully created email HMAC key '{EMAIL_HMAC_KEY_NAME}'.")
                 except Exception as create_error:
                     # Handle potential race condition if another instance created it
                     if "already exists" in str(create_error).lower():
                         logger.debug(f"Email HMAC key '{EMAIL_HMAC_KEY_NAME}' was created by another process.")
                     else:
                         logger.error(f"Failed to create email HMAC key '{EMAIL_HMAC_KEY_NAME}': {str(create_error)}")
                         raise Exception(f"Failed to initialize email HMAC key: {str(create_error)}")

        except Exception as e:
            logger.error(f"Failed to ensure email HMAC key exists: {str(e)}")
            raise Exception(f"Failed to initialize email HMAC key: {str(e)}")

        # --- Ensure SHARED_CONTENT_METADATA_KEY exists in transit engine ---
        # This key is used for encrypting shared chat/embed metadata for OG tag generation
        SHARED_CONTENT_METADATA_KEY_NAME = "shared-content-metadata"
        try:
            logger.debug(f"Checking for shared content metadata key '{SHARED_CONTENT_METADATA_KEY_NAME}' in transit engine...")
            key_exists = False
            try:
                # Check if key exists by attempting to read its configuration
                response = await self._vault_request("get", f"{self.transit_mount}/keys/{SHARED_CONTENT_METADATA_KEY_NAME}")
                # If the response has data (not just the default {"data": {}} from 404 handling), the key exists.
                if response and response.get("data") and response["data"].get("name") == SHARED_CONTENT_METADATA_KEY_NAME:
                    key_exists = True
                    logger.debug(f"Shared content metadata key '{SHARED_CONTENT_METADATA_KEY_NAME}' already exists.")
                else:
                    # This case handles 404 or unexpected empty data
                    logger.debug(f"Shared content metadata key '{SHARED_CONTENT_METADATA_KEY_NAME}' not found.")
            except Exception as e:
                 # Log error during check, but proceed assuming key might not exist
                 logger.warning(f"Error checking for shared content metadata key '{SHARED_CONTENT_METADATA_KEY_NAME}': {str(e)}. Assuming it might not exist.")
                 key_exists = False # Ensure we try to create if check failed

            # If key does not exist, create it
            if not key_exists:
                 logger.debug(f"Attempting to create shared content metadata key '{SHARED_CONTENT_METADATA_KEY_NAME}'...")
                 try:
                     # Create the key (non-derived, since it's shared across all users)
                     await self._vault_request("post", f"{self.transit_mount}/keys/{SHARED_CONTENT_METADATA_KEY_NAME}", {
                         "type": "aes256-gcm96", # AES with GCM mode for authenticated encryption
                         "allow_plaintext_backup": False # Good practice
                     })
                     logger.debug(f"Successfully created shared content metadata key '{SHARED_CONTENT_METADATA_KEY_NAME}'.")
                 except Exception as create_error:
                     # Handle potential race condition if another instance created it
                     if "already exists" in str(create_error).lower():
                         logger.debug(f"Shared content metadata key '{SHARED_CONTENT_METADATA_KEY_NAME}' was created by another process.")
                     else:
                         logger.error(f"Failed to create shared content metadata key '{SHARED_CONTENT_METADATA_KEY_NAME}': {str(create_error)}")
                         raise Exception(f"Failed to initialize shared content metadata key: {str(create_error)}")

        except Exception as e:
            logger.error(f"Failed to ensure shared content metadata key exists: {str(e)}")
            raise Exception(f"Failed to initialize shared content metadata key: {str(e)}")

        # --- Ensure CREATOR_INCOME_ENCRYPTION_KEY exists in transit engine ---
        # This key is used for encrypting creator income credit amounts for privacy
        try:
            logger.debug(f"Checking for creator income encryption key '{CREATOR_INCOME_ENCRYPTION_KEY}' in transit engine...")
            key_exists = False
            try:
                # Check if key exists by attempting to read its configuration
                response = await self._vault_request("get", f"{self.transit_mount}/keys/{CREATOR_INCOME_ENCRYPTION_KEY}")
                # If the response has data (not just the default {"data": {}} from 404 handling), the key exists.
                if response and response.get("data") and response["data"].get("name") == CREATOR_INCOME_ENCRYPTION_KEY:
                    key_exists = True
                    logger.debug(f"Creator income encryption key '{CREATOR_INCOME_ENCRYPTION_KEY}' already exists.")
                else:
                    # This case handles 404 or unexpected empty data
                    logger.debug(f"Creator income encryption key '{CREATOR_INCOME_ENCRYPTION_KEY}' not found.")
            except Exception as e:
                 # Log error during check, but proceed assuming key might not exist
                 logger.warning(f"Error checking for creator income encryption key '{CREATOR_INCOME_ENCRYPTION_KEY}': {str(e)}. Assuming it might not exist.")
                 key_exists = False # Ensure we try to create if check failed

            # If key does not exist, create it
            if not key_exists:
                 logger.debug(f"Attempting to create creator income encryption key '{CREATOR_INCOME_ENCRYPTION_KEY}'...")
                 try:
                     # Create the key (non-derived, since it's a system-level key for all creator income)
                     await self._vault_request("post", f"{self.transit_mount}/keys/{CREATOR_INCOME_ENCRYPTION_KEY}", {
                         "type": "aes256-gcm96", # AES with GCM mode for authenticated encryption
                         "allow_plaintext_backup": False # Good practice
                     })
                     logger.debug(f"Successfully created creator income encryption key '{CREATOR_INCOME_ENCRYPTION_KEY}'.")
                 except Exception as create_error:
                     # Handle potential race condition if another instance created it
                     if "already exists" in str(create_error).lower():
                         logger.debug(f"Creator income encryption key '{CREATOR_INCOME_ENCRYPTION_KEY}' was created by another process.")
                     else:
                         logger.error(f"Failed to create creator income encryption key '{CREATOR_INCOME_ENCRYPTION_KEY}': {str(create_error)}")
                         raise Exception(f"Failed to initialize creator income encryption key: {str(create_error)}")

        except Exception as e:
            logger.error(f"Failed to ensure creator income encryption key exists: {str(e)}")
            raise Exception(f"Failed to initialize creator income encryption key: {str(e)}")

        # --- Ensure NEWSLETTER_ENCRYPTION_KEY exists in transit engine ---
        # This key is used for encrypting newsletter subscriber email addresses for privacy
        try:
            logger.debug(f"Checking for newsletter encryption key '{NEWSLETTER_ENCRYPTION_KEY}' in transit engine...")
            key_exists = False
            try:
                # Check if key exists by attempting to read its configuration
                response = await self._vault_request("get", f"{self.transit_mount}/keys/{NEWSLETTER_ENCRYPTION_KEY}")
                # If the response has data (not just the default {"data": {}} from 404 handling), the key exists.
                if response and response.get("data") and response["data"].get("name") == NEWSLETTER_ENCRYPTION_KEY:
                    key_exists = True
                    logger.debug(f"Newsletter encryption key '{NEWSLETTER_ENCRYPTION_KEY}' already exists.")
                else:
                    # This case handles 404 or unexpected empty data
                    logger.debug(f"Newsletter encryption key '{NEWSLETTER_ENCRYPTION_KEY}' not found.")
            except Exception as e:
                 # Log error during check, but proceed assuming key might not exist
                 logger.warning(f"Error checking for newsletter encryption key '{NEWSLETTER_ENCRYPTION_KEY}': {str(e)}. Assuming it might not exist.")
                 key_exists = False # Ensure we try to create if check failed

            # If key does not exist, create it
            if not key_exists:
                 logger.debug(f"Attempting to create newsletter encryption key '{NEWSLETTER_ENCRYPTION_KEY}'...")
                 try:
                     # Create the key (non-derived, since it's a system-level key for all newsletter emails)
                     await self._vault_request("post", f"{self.transit_mount}/keys/{NEWSLETTER_ENCRYPTION_KEY}", {
                         "type": "aes256-gcm96", # AES with GCM mode for authenticated encryption
                         "allow_plaintext_backup": False # Good practice
                     })
                     logger.debug(f"Successfully created newsletter encryption key '{NEWSLETTER_ENCRYPTION_KEY}'.")
                 except Exception as create_error:
                     # Handle potential race condition if another instance created it
                     if "already exists" in str(create_error).lower():
                         logger.debug(f"Newsletter encryption key '{NEWSLETTER_ENCRYPTION_KEY}' was created by another process.")
                     else:
                         logger.error(f"Failed to create newsletter encryption key '{NEWSLETTER_ENCRYPTION_KEY}': {str(create_error)}")
                         raise Exception(f"Failed to initialize newsletter encryption key: {str(create_error)}")

        except Exception as e:
            logger.error(f"Failed to ensure newsletter encryption key exists: {str(e)}")
            raise Exception(f"Failed to initialize newsletter encryption key: {str(e)}")

        # --- Ensure SUPPORT_PAYMENTS_ENCRYPTION_KEY exists in transit engine ---
        # This key is used for encrypting support payment receipt archive keys (system-level, not user-specific).
        try:
            logger.debug(f"Checking for support payments encryption key '{SUPPORT_PAYMENTS_ENCRYPTION_KEY}' in transit engine...")
            key_exists = False
            try:
                response = await self._vault_request("get", f"{self.transit_mount}/keys/{SUPPORT_PAYMENTS_ENCRYPTION_KEY}")
                if response and response.get("data") and response["data"].get("name") == SUPPORT_PAYMENTS_ENCRYPTION_KEY:
                    key_exists = True
                    logger.debug(f"Support payments encryption key '{SUPPORT_PAYMENTS_ENCRYPTION_KEY}' already exists.")
                else:
                    logger.debug(f"Support payments encryption key '{SUPPORT_PAYMENTS_ENCRYPTION_KEY}' not found.")
            except Exception as e:
                logger.warning(
                    f"Error checking for support payments encryption key '{SUPPORT_PAYMENTS_ENCRYPTION_KEY}': {str(e)}. "
                    f"Assuming it might not exist."
                )
                key_exists = False

            if not key_exists:
                logger.debug(f"Attempting to create support payments encryption key '{SUPPORT_PAYMENTS_ENCRYPTION_KEY}'...")
                try:
                    await self._vault_request(
                        "post",
                        f"{self.transit_mount}/keys/{SUPPORT_PAYMENTS_ENCRYPTION_KEY}",
                        {
                            "type": "aes256-gcm96",
                            "allow_plaintext_backup": False,
                        },
                    )
                    logger.debug(f"Successfully created support payments encryption key '{SUPPORT_PAYMENTS_ENCRYPTION_KEY}'.")
                except Exception as create_error:
                    if "already exists" in str(create_error).lower():
                        logger.debug(
                            f"Support payments encryption key '{SUPPORT_PAYMENTS_ENCRYPTION_KEY}' was created by another process."
                        )
                    else:
                        logger.error(
                            f"Failed to create support payments encryption key '{SUPPORT_PAYMENTS_ENCRYPTION_KEY}': {str(create_error)}"
                        )
                        raise Exception(f"Failed to initialize support payments encryption key: {str(create_error)}")
        except Exception as e:
            logger.error(f"Failed to ensure support payments encryption key exists: {str(e)}")
            raise Exception(f"Failed to initialize support payments encryption key: {str(e)}")

    # Removed get_email_hash_key method

    async def create_user_key(self) -> str:
        """
        Create a user-specific encryption key in Vault
        Returns the key ID used in Vault
        """
        # Generate a unique key ID for this user
        key_id = f"user_{uuid.uuid4().hex}"
        
        try:
            logger.debug(f"Attempting to create user-specific encryption key in Vault with key_id: {key_id}")
            # Create a dedicated encryption key for this user in Vault
            await self._vault_request("post", f"{self.transit_mount}/keys/{key_id}", {
                "type": "aes256-gcm96",  # AES with GCM mode for authenticated encryption
                "derived": True  # Derive encryption key from a combination of the key and context
            })
            logger.debug(f"Successfully created user-specific encryption key: {key_id}")
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
    
    async def encrypt_newsletter_email(self, email: str) -> str:
        """
        Encrypt newsletter subscriber email using the system-level newsletter encryption key.
        
        Args:
            email: Plaintext email address
            
        Returns:
            Encrypted email address (ciphertext)
        """
        if not email:
            return ""
        
        ciphertext, _ = await self.encrypt(email, key_name=NEWSLETTER_ENCRYPTION_KEY)
        return ciphertext
    
    async def decrypt_newsletter_email(self, encrypted_email: str) -> Optional[str]:
        """
        Decrypt newsletter subscriber email using the system-level newsletter encryption key.
        
        Args:
            encrypted_email: Encrypted email address (ciphertext)
            
        Returns:
            Decrypted email address or None if decryption fails
        """
        if not encrypted_email:
            return None
        
        return await self.decrypt(encrypted_email, key_name=NEWSLETTER_ENCRYPTION_KEY)
    
    async def encrypt_newsletter_token(self, token: str) -> str:
        """
        Encrypt a newsletter unsubscribe token using server-side encryption.
        
        This uses the same encryption key as newsletter emails (NEWSLETTER_ENCRYPTION_KEY)
        to ensure consistent security for all newsletter-related data.
        
        Args:
            token: Plaintext unsubscribe token
            
        Returns:
            Encrypted token (base64-encoded ciphertext with vault:v1: prefix)
        """
        if not token:
            return ""
        
        ciphertext, _ = await self.encrypt(token, key_name=NEWSLETTER_ENCRYPTION_KEY)
        return ciphertext
    
    async def decrypt_newsletter_token(self, encrypted_token: str) -> Optional[str]:
        """
        Decrypt a newsletter unsubscribe token.
        
        Args:
            encrypted_token: Encrypted unsubscribe token (base64-encoded ciphertext)
            
        Returns:
            Decrypted token (plaintext) or None if decryption fails
        """
        if not encrypted_token:
            return None
        
        return await self.decrypt(encrypted_token, key_name=NEWSLETTER_ENCRYPTION_KEY)
    
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

        # Vault transit ciphertexts always have the `vault:` prefix (e.g. `vault:v1:...`).
        # If we don't see it, this is likely client-side encrypted data; avoid sending it to Vault
        # (which would return 400) and let callers fall back to the appropriate decryptor.
        if not isinstance(ciphertext, str) or not ciphertext.startswith("vault:"):
            logger.warning("decrypt: Ciphertext is not a Vault transit value (missing `vault:` prefix).")
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

    # Note: Server-side chat encryption methods removed - chat encryption now happens client-side
    # The following methods are deprecated and should not be used:
    # - create_chat_key()
    # - encrypt_with_chat_key() 
    # - decrypt_with_chat_key()
    # - get_chat_aes_key()
    # - _ensure_chat_aes_key()

    # --- Updated Hashing Methods ---

    async def hash_email(self, email: str) -> str:
        """
        Creates a consistent HMAC-SHA256 hash of an email address using Vault's transit engine.
        """
        if not email:
            return ""

        # Normalize email to lowercase and encode for Vault
        normalized_email = email.strip().lower()
        encoded_input = base64.b64encode(normalized_email.encode('utf-8')).decode('utf-8')

        # Call Vault's HMAC endpoint
        path = f"{self.transit_mount}/hmac/{EMAIL_HMAC_KEY_NAME}"
        # Simplify payload: Remove algorithm and context, let Vault use defaults/key type
        payload = {
            "input": encoded_input
        }

        try:
            result = await self._vault_request("post", path, payload)
            hmac_digest = result.get("data", {}).get("hmac")
            if not hmac_digest:
                 logger.error(f"Vault HMAC response missing 'hmac' field for email: {email[:5]}...")
                 raise ValueError("Invalid response from Vault HMAC endpoint")
            # Vault returns the HMAC digest directly (e.g., "hmac:v1:...")
            # We only need the actual digest part after the last colon
            digest = hmac_digest.split(':')[-1]
            logger.debug(f"Vault HMAC generated digest starting with: {digest[:8]}...") # Log confirmation
            return digest
        except Exception as e:
            logger.error(f"Vault HMAC generation failed for email {email[:5]}...: {str(e)}")
            raise # Re-raise the exception to signal failure

    async def verify_email_hash(self, email: str, stored_hash: str) -> bool:
        """
        Verifies if a plaintext email matches a stored hash using Vault's transit engine.
        """
        if not email or not stored_hash:
            return False
        try:
            # Generate the expected hash using the new async method
            expected_hash = await self.hash_email(email)
            # Use hmac.compare_digest for secure comparison
            return hmac.compare_digest(expected_hash, stored_hash)
        except Exception as e:
            # Log error during verification but return False
            logger.error(f"Error during email hash verification for {email[:5]}...: {str(e)}")
            return False

    async def close(self):
        """
        Placeholder close method to be called during application shutdown.
        Currently, httpx.AsyncClient is created per request, so no specific
        client instance needs to be closed here.
        """
        logger.debug("EncryptionService close called.")
        # If in the future, a persistent AsyncClient is added to this service,
        # it should be closed here. e.g., if hasattr(self, 'client') and self.client: await self.client.aclose()
        pass

    # Note: All chat and draft encryption methods removed - encryption now happens client-side
    # The following methods are deprecated and should not be used:
    # - _ensure_user_draft_aes_key()
    # - get_user_draft_aes_key()
    # - encrypt_locally_with_aes()
    # - decrypt_locally_with_aes()
    # - _ensure_chat_aes_key()
    # - get_chat_aes_key()
            
    async def decrypt_with_email_key(self, encrypted_email: str, email_encryption_key_b64: str) -> Optional[str]:
        """
        Decrypt an encrypted email using the email encryption key provided by the client.
        
        The email is encrypted using TweetNaCl's secretbox (XSalsa20-Poly1305) on the client side.
        The format is base64(nonce + ciphertext), where nonce is 24 bytes.
        
        Args:
            encrypted_email: The encrypted email address (base64 encoded)
            email_encryption_key_b64: Base64-encoded email encryption key derived from SHA256(email + user_email_salt)
                                      This key is already derived on the client side, so we use it directly.
            
        Returns:
            The decrypted email address or None if decryption fails
        """
        if not encrypted_email or not email_encryption_key_b64:
            logger.warning("decrypt_with_email_key: Missing encrypted_email or email_encryption_key_b64")
            return None
            
        try:
            # Import nacl library for XSalsa20-Poly1305 decryption (compatible with TweetNaCl)
            try:
                import nacl.secret
                import nacl.utils
            except ImportError:
                logger.error("decrypt_with_email_key: PyNaCl library not installed. Cannot decrypt email.")
                return None
                
            # Decode the base64 email encryption key
            email_encryption_key = base64.b64decode(email_encryption_key_b64)
            
            # Check if the key has the correct length (32 bytes for XSalsa20)
            if len(email_encryption_key) != 32:
                logger.error(f"decrypt_with_email_key: Invalid key length: {len(email_encryption_key)} bytes. Expected 32 bytes.")
                return None
                
            # Decode the base64 encrypted email (contains nonce + ciphertext)
            try:
                combined = base64.b64decode(encrypted_email)
            except base64.binascii.Error as b64_error:
                logger.error(f"decrypt_with_email_key: Base64 decoding error: {b64_error}")
                return None
                
            # Extract nonce (24 bytes) and ciphertext
            NACL_NONCE_SIZE = 24
            if len(combined) <= NACL_NONCE_SIZE:
                logger.error(f"decrypt_with_email_key: Invalid encrypted email format. Too short: {len(combined)} bytes")
                return None
                
            nonce = combined[:NACL_NONCE_SIZE]
            ciphertext = combined[NACL_NONCE_SIZE:]
            
            # Create the SecretBox with the key
            box = nacl.secret.SecretBox(email_encryption_key)
            
            try:
                # Decrypt the email
                decrypted_bytes = box.decrypt(ciphertext, nonce)
                return decrypted_bytes.decode('utf-8')
            except nacl.exceptions.CryptoError as e:
                logger.error(f"decrypt_with_email_key: Decryption failed: {str(e)}")
                return None
                
        except Exception as e:
            logger.error(f"decrypt_with_email_key: Decryption error: {str(e)}", exc_info=True)
            return None
