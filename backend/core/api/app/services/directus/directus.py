import os
import time
import logging
import json
import httpx # Import httpx
from datetime import datetime, timezone
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService

from typing import List, Dict, Any, Optional
# Import method implementations
from backend.core.api.app.services.directus.auth_methods import (
    get_auth_lock, clear_tokens, validate_token, login_admin, ensure_auth_token
)
from backend.core.api.app.services.directus.api_methods import _make_api_request, create_item # Import create_item
from backend.core.api.app.services.directus.invite_methods import get_invite_code, get_all_invite_codes, consume_invite_code
from backend.core.api.app.services.directus.gift_card_methods import get_gift_card_by_code, get_all_gift_cards, redeem_gift_card
from backend.core.api.app.services.directus.chat_methods import ChatMethods # Import ChatMethods class
# from backend.core.api.app.services.directus.app_memory_methods import AppMemoryMethods # Old import, replaced
from backend.core.api.app.services.directus.app_settings_and_memories_methods import AppSettingsAndMemoriesMethods # New import
from backend.core.api.app.services.directus.usage import UsageMethods # Corrected import
from backend.core.api.app.services.directus.analytics_methods import AnalyticsMethods
from backend.core.api.app.services.directus.embed_methods import EmbedMethods # Import EmbedMethods class
from backend.core.api.app.services.directus.user.user_creation import create_user
from backend.core.api.app.services.directus.user.user_authentication import login_user, login_user_with_lookup_hash, logout_user, logout_all_sessions, refresh_token
from backend.core.api.app.services.directus.user.user_lookup import get_user_by_hashed_email, get_total_users_count, get_active_users_since, get_user_fields_direct, authenticate_user_by_lookup_hash, add_user_lookup_hash, get_user_by_subscription_id
from backend.core.api.app.services.directus.user.user_profile import get_user_profile, get_tfa_backup_code_hashes
from backend.core.api.app.services.directus.user.delete_user import delete_user
from backend.core.api.app.services.directus.user.update_user import update_user
# Import device management methods
from backend.core.api.app.services.directus.user.device_management import add_user_device_hash, get_user_device_hashes # Updated imports
# Import API key device management methods
from backend.core.api.app.services.directus.api_key_device_methods import (
    get_api_key_device_by_hash,
    create_api_key_device,
    update_api_key_device_last_access,
    get_api_key_devices,
    approve_api_key_device,
    revoke_api_key_device,
    get_pending_api_key_devices,
    update_api_key_device_name
)

logger = logging.getLogger(__name__)

class DirectusService:
    """
    Service for interacting with Directus CMS API
    """
    
    def __init__(self, cache_service: CacheService = None, encryption_service: EncryptionService = None): # Added encryption_service parameter
        self.base_url = os.getenv("CMS_URL", "http://cms:8055")
        self.token = os.getenv("DIRECTUS_TOKEN")
        self.admin_email = os.getenv("ADMIN_EMAIL")
        self.admin_password = os.getenv("ADMIN_PASSWORD")
        self.auth_token = None
        self.admin_token = None
        self._auth_lock = None
        self.max_retries = int(os.getenv("DIRECTUS_MAX_RETRIES", "3"))
        
        self.cache = cache_service or CacheService()
        self.cache_ttl = int(os.getenv("DIRECTUS_CACHE_TTL", "3600"))
        self.token_ttl = int(os.getenv("DIRECTUS_TOKEN_TTL", "43200"))
        # Use injected encryption_service or create one if not provided (though it should be provided from main.py)
        self.encryption_service = encryption_service or EncryptionService()
        self._client = httpx.AsyncClient() # Initialize the client
        
        if self.token:
            masked_token = self.token[:4] + "..." + self.token[-4:] if len(self.token) > 8 else "****"
            logger.info(f"DirectusService initialized with URL: {self.base_url}, Token: {masked_token}")
        else:
            logger.warning("DirectusService initialized WITHOUT a token! Will try to authenticate with admin credentials.")

        # Initialize method groups
        self.app_settings_and_memories = AppSettingsAndMemoriesMethods(self) # New combined methods
        self.usage = UsageMethods(self, self.encryption_service)
        self.analytics = AnalyticsMethods(self) # Anonymous analytics methods
        self.chat = ChatMethods(self) # Initialize ChatMethods
        self.embed = EmbedMethods(self) # Initialize EmbedMethods

    async def close(self):
        """Close the httpx client."""
        await self._client.aclose()
        logger.info("DirectusService httpx client closed.")

    async def get_items(self, collection, params=None, no_cache=True):
        """
        Fetch items from a Directus collection with optional query params.
        Returns the list of items directly.
        
        For sensitive collections like 'directus_users', ensures admin token is used.
        """
        url = f"{self.base_url}/items/{collection}"
        
        # For sensitive collections like directus_users, ensure we use admin token
        # user_passkeys contains user_id which requires admin permissions
        sensitive_collections = ['directus_users', 'directus_roles', 'directus_permissions', 'user_passkeys']
        
        if collection in sensitive_collections:
            # Ensure we have a valid admin token for sensitive collections
            admin_token = await self.ensure_auth_token(admin_required=True)
            if not admin_token:
                logger.error(f"Failed to get admin token for sensitive collection: {collection}")
                return []
            headers = {"Authorization": f"Bearer {admin_token}"}
            logger.info(f"Using admin token for sensitive collection: {collection}")
        else:
            # Use regular token for non-sensitive collections
            headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        
        # Optionally bypass Directus cache using no-store
        if no_cache:
            headers["Cache-Control"] = "no-store" # Use no-store as per docs for CACHE_SKIP_ALLOWED
            # Ensure params is a dictionary to add our cache-busting timestamp
            current_params = dict(params or {})
            current_params["_ts"] = str(time.time_ns()) # Timestamp for cache busting
            # The "cache!=clear" parameter is not standard; Cache-Control header is preferred.
        else:
            current_params = dict(params or {}) # Make a copy to avoid modifying original
        
        # Directus requires complex query parameters (filter, sort, etc.) to be JSON-encoded
        # httpx doesn't automatically JSON-encode nested dicts, so we need to do it manually
        if "filter" in current_params and isinstance(current_params["filter"], dict):
            current_params["filter"] = json.dumps(current_params["filter"])
        
        if "sort" in current_params and isinstance(current_params["sort"], list):
            current_params["sort"] = json.dumps(current_params["sort"])
        
        # _make_api_request returns an httpx.Response object.
        response_obj = await self._make_api_request("GET", url, headers=headers, params=current_params)

        if response_obj is None:
            logger.error(f"Directus get_items for '{collection}': _make_api_request returned None.")
            return []

        try:
            if 200 <= response_obj.status_code < 300:
                response_json = response_obj.json() # Parse JSON from the response object
                if response_json and isinstance(response_json, dict) and "data" in response_json:
                    if isinstance(response_json["data"], list):
                        return response_json["data"]  # Return the list of items
                    else:
                        logger.error(f"Directus get_items for '{collection}': 'data' field is not a list. Response JSON: {response_json}")
                        return []
                elif response_json and isinstance(response_json, list): # If API directly returns a list
                    return response_json
                else:
                    logger.warning(f"Directus get_items for '{collection}': Unexpected JSON structure. Response JSON: {response_json}")
                    return []
            else:
                logger.warning(f"Directus get_items for '{collection}' failed with status {response_obj.status_code}. Response text: {response_obj.text[:200]}")
                return []
        except Exception as e: # Catch JSONDecodeError or other parsing issues
            logger.error(f"Directus get_items for '{collection}': Error parsing JSON response. Status: {response_obj.status_code}, Error: {e}, Response text: {response_obj.text[:200]}", exc_info=True)
            return []

    # Item creation method
    create_item = create_item # Assign the imported method

    async def create_encryption_key(self, hashed_user_id: str, login_method: str, encrypted_key: str, salt: str, key_iv: Optional[str] = None) -> bool:
        """
        Creates a new record in the encryption_keys collection.
        """
        payload = {
            "hashed_user_id": hashed_user_id,
            "login_method": login_method,
            "encrypted_key": encrypted_key,
            "salt": salt,
        }
        if key_iv:
            payload["key_iv"] = key_iv
        try:
            created_item = await self.create_item("encryption_keys", payload)
            if created_item:
                logger.info(f"Successfully created encryption key for hashed_user_id: {hashed_user_id}")
                return True
            else:
                logger.error(f"Failed to create encryption key for hashed_user_id: {hashed_user_id} - no item returned.")
                return False
        except Exception as e:
            logger.error(f"Exception creating encryption key for hashed_user_id: {hashed_user_id}: {e}", exc_info=True)
            return False

    async def get_encryption_key(self, hashed_user_id: str, login_method: str) -> Optional[Dict[str, str]]:
        """
        Retrieves the encrypted key, salt, and IV for a user and login method.
        """
        params = {
            "filter[hashed_user_id][_eq]": hashed_user_id,
            "filter[login_method][_eq]": login_method,
            "fields": "encrypted_key,salt,key_iv",
            "limit": 1
        }
        try:
            items = await self.get_items("encryption_keys", params)
            if items:
                return items[0]
            return None
        except Exception as e:
            logger.error(f"Exception getting encryption key for hashed_user_id: {hashed_user_id}: {e}", exc_info=True)
            return None

    async def delete_encryption_key(self, hashed_user_id: str, login_method: str) -> bool:
        """
        Deletes an encryption key record by hashed_user_id and login_method.
        
        Args:
            hashed_user_id: SHA256 hash of the user's UUID
            login_method: The login method (e.g., 'api_key_{key_hash}', 'passkey_{credential_id_hash}')
            
        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            # First find the encryption key record
            encryption_key = await self.get_encryption_key(hashed_user_id, login_method)
            if not encryption_key:
                logger.warning(f"Encryption key not found for deletion: hashed_user_id={hashed_user_id[:8]}..., login_method={login_method}")
                return False
            
            # Get the record ID (Directus auto-generates IDs, we need to query by fields to get ID)
            params = {
                "filter[hashed_user_id][_eq]": hashed_user_id,
                "filter[login_method][_eq]": login_method,
                "fields": "id",
                "limit": 1
            }
            items = await self.get_items("encryption_keys", params)
            if not items or len(items) == 0:
                logger.warning(f"Encryption key record not found for deletion: hashed_user_id={hashed_user_id[:8]}..., login_method={login_method}")
                return False
            
            encryption_key_id = items[0].get("id")
            if not encryption_key_id:
                logger.error(f"Encryption key record missing ID: hashed_user_id={hashed_user_id[:8]}..., login_method={login_method}")
                return False
            
            # Delete the encryption key record
            success = await self.delete_item("encryption_keys", encryption_key_id)
            if success:
                logger.info(f"Successfully deleted encryption key for hashed_user_id={hashed_user_id[:8]}..., login_method={login_method}")
            return success
        except Exception as e:
            logger.error(f"Exception deleting encryption key for hashed_user_id={hashed_user_id[:8]}..., login_method={login_method}: {e}", exc_info=True)
            return False

    async def get_any_passkey_encryption_key(self, hashed_user_id: str) -> Optional[Dict[str, str]]:
        """
        Retrieves ANY valid passkey encryption key for a user.
        Used when we know the user authenticated via passkey but don't have the specific credential ID hash.
        """
        params = {
            "filter[hashed_user_id][_eq]": hashed_user_id,
            "filter[login_method][_starts_with]": "passkey_",
            "fields": "encrypted_key,salt,key_iv",
            "limit": 1
        }
        try:
            items = await self.get_items("encryption_keys", params)
            if items:
                return items[0]
            return None
        except Exception as e:
            logger.error(f"Exception getting any passkey encryption key for hashed_user_id: {hashed_user_id}: {e}", exc_info=True)
            return None

    async def delete_encryption_key(self, hashed_user_id: str, login_method: str) -> bool:
        """
        Deletes an encryption key record for a user and login method.
        """
        params = {
            "filter[hashed_user_id][_eq]": hashed_user_id,
            "filter[login_method][_eq]": login_method,
            "fields": "id",
            "limit": 1
        }
        try:
            items = await self.get_items("encryption_keys", params)
            if items:
                item_id = items[0].get("id")
                if item_id:
                    return await self.delete_item("encryption_keys", item_id)
            return False
        except Exception as e:
            logger.error(f"Exception deleting encryption key for hashed_user_id: {hashed_user_id}: {e}", exc_info=True)
            return False

    # Passkey management methods
    async def create_passkey(
        self,
        hashed_user_id: str,
        user_id: str,
        credential_id: str,
        public_key_cose_b64: str,
        aaguid: str,
        public_key_jwk: Optional[Dict[str, Any]] = None,
        encrypted_device_name: Optional[str] = None
    ) -> bool:
        """
        Creates a new passkey record in the user_passkeys collection.
        
        Args:
            hashed_user_id: SHA256 hash of the user's UUID (for privacy-preserving lookups)
            user_id: Direct reference to user_id for efficient lookups
            credential_id: Base64-encoded credential ID from WebAuthn
            public_key_cose_b64: Public key in COSE format (base64-encoded CBOR bytes) - REQUIRED for py_webauthn
            aaguid: Authenticator Attestation Globally Unique Identifier
            public_key_jwk: Public key in JWK format (optional, for backward compatibility)
            encrypted_device_name: Optional encrypted user-friendly device name
            
        Returns:
            True if passkey was created successfully, False otherwise
        """
        # Get current Unix timestamp (integer) for all timestamp fields
        # registered_at, created_at, and updated_at will all be the same value
        # since the passkey is being registered/created right now
        current_timestamp = int(time.time())
        
        payload = {
            "hashed_user_id": hashed_user_id,
            "user_id": user_id,
            "credential_id": credential_id,
            "public_key_cose": public_key_cose_b64,
            "aaguid": aaguid,
            "sign_count": 0,
            "registered_at": current_timestamp,
            "created_at": current_timestamp,
            "updated_at": current_timestamp,
        }
        if public_key_jwk:
            payload["public_key_jwk"] = public_key_jwk
        if encrypted_device_name:
            payload["encrypted_device_name"] = encrypted_device_name
        
        try:
            created_item = await self.create_item("user_passkeys", payload)
            if created_item:
                logger.info(f"Successfully created passkey for hashed_user_id: {hashed_user_id[:8]}...")
                return True
            else:
                logger.error(f"Failed to create passkey for hashed_user_id: {hashed_user_id[:8]}... - no item returned.")
                return False
        except Exception as e:
            logger.error(f"Exception creating passkey for hashed_user_id: {hashed_user_id[:8]}...: {e}", exc_info=True)
            return False

    async def get_passkey_by_credential_id(self, credential_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a passkey by its credential ID.
        
        Args:
            credential_id: Base64-encoded credential ID
            
        Returns:
            Passkey record if found, None otherwise (includes hashed_user_id and user_id)
        """
        params = {
            "filter[credential_id][_eq]": credential_id,
            "fields": "id,hashed_user_id,user_id,credential_id,public_key_cose,public_key_jwk,aaguid,sign_count,encrypted_device_name,registered_at,last_used_at",
            "limit": 1
        }
        try:
            items = await self.get_items("user_passkeys", params)
            if items:
                return items[0]
            return None
        except Exception as e:
            logger.error(f"Exception getting passkey by credential_id: {e}", exc_info=True)
            return None

    async def update_passkey_sign_count(
        self,
        passkey_id: str,
        new_sign_count: int
    ) -> bool:
        """
        Updates the sign_count and last_used_at timestamp for a passkey.
        
        Args:
            passkey_id: The passkey record ID
            new_sign_count: The new sign count value
            
        Returns:
            True if update was successful, False otherwise
        """
        # Use Unix timestamp (integer) for consistency with create_passkey
        # Directus will convert this to ISO format when returning via API
        current_timestamp = int(time.time())
        update_data = {
            "sign_count": new_sign_count,
            "last_used_at": current_timestamp
        }
        try:
            updated_item = await self.update_item("user_passkeys", passkey_id, update_data)
            if updated_item:
                logger.info(f"Successfully updated sign_count for passkey {passkey_id[:6]}... to {new_sign_count}")
                return True
            else:
                logger.error(f"Failed to update sign_count for passkey {passkey_id[:6]}...")
                return False
        except Exception as e:
            logger.error(f"Exception updating passkey sign_count: {e}", exc_info=True)
            return False

    async def update_passkey_device_name(
        self,
        passkey_id: str,
        encrypted_device_name: str
    ) -> bool:
        """
        Updates the encrypted device name for a passkey.
        
        Args:
            passkey_id: The passkey record ID
            encrypted_device_name: The new encrypted device name
            
        Returns:
            True if update was successful, False otherwise
        """
        update_data = {
            "encrypted_device_name": encrypted_device_name
        }
        try:
            updated_item = await self.update_item("user_passkeys", passkey_id, update_data)
            if updated_item:
                logger.info(f"Successfully updated device name for passkey {passkey_id[:6]}...")
                return True
            else:
                logger.error(f"Failed to update device name for passkey {passkey_id[:6]}...")
                return False
        except Exception as e:
            logger.error(f"Exception updating passkey device name: {e}", exc_info=True)
            return False

    async def delete_passkey(self, passkey_id: str) -> bool:
        """
        Deletes a passkey record.
        
        Args:
            passkey_id: The passkey record ID
            
        Returns:
            True if deletion was successful, False otherwise
        """
        try:
            success = await self.delete_item("user_passkeys", passkey_id)
            if success:
                logger.info(f"Successfully deleted passkey {passkey_id[:6]}...")
                return True
            else:
                logger.error(f"Failed to delete passkey {passkey_id[:6]}...")
                return False
        except Exception as e:
            logger.error(f"Exception deleting passkey: {e}", exc_info=True)
            return False

    async def get_user_passkeys(self, hashed_user_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves all passkeys for a user by hashed_user_id.
        
        Args:
            hashed_user_id: SHA256 hash of the user's UUID
            
        Returns:
            List of passkey records (includes encrypted_device_name)
        """
        params = {
            "filter[hashed_user_id][_eq]": hashed_user_id,
            "fields": "id,credential_id,encrypted_device_name,registered_at,last_used_at,sign_count",
            "sort": "-last_used_at"  # Most recently used first
        }
        try:
            items = await self.get_items("user_passkeys", params)
            return items if items else []
        except Exception as e:
            logger.error(f"Exception getting user passkeys for hashed_user_id {hashed_user_id[:8]}...: {e}", exc_info=True)
            return []

    async def get_user_passkeys_by_user_id(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves all passkeys for a user by user_id (UUID).
        Queries directly by user_id field for efficient lookups.
        Only returns essential fields needed for the settings UI.
        
        Args:
            user_id: The user's UUID
            
        Returns:
            List of passkey records with only essential fields:
            - id (for rename/delete operations)
            - encrypted_device_name (for display, client decrypts)
            - registered_at (registration timestamp)
            - last_used_at (last usage timestamp)
            - sign_count (usage counter)
        """
        params = {
            "filter[user_id][_eq]": user_id,
            "fields": "id,encrypted_device_name,registered_at,last_used_at,sign_count",
            "sort": "-last_used_at"  # Most recently used first
        }
        try:
            items = await self.get_items("user_passkeys", params)
            return items if items else []
        except Exception as e:
            logger.error(f"Exception getting user passkeys for user_id {user_id[:8]}...: {e}", exc_info=True)
            return []

    async def get_user_id_from_hashed_user_id(self, hashed_user_id: str) -> Optional[str]:
        """
        Gets user_id from hashed_user_id by querying user_passkeys table.
        This is a reverse lookup - finds which user has this hashed_user_id.
        
        This is used for resident credential (passwordless) passkey login where we only have
        the credential_id and need to find the user.
        
        Args:
            hashed_user_id: SHA256 hash of the user's UUID
            
        Returns:
            user_id if found, None otherwise
            
        Note: This implementation queries user_passkeys table by indexed hashed_user_id field,
        which is much more efficient than batch-querying all users.
        """
        logger.debug(f"Attempting to get user_id from hashed_user_id: {hashed_user_id[:8]}...")
        try:
            # Query user_passkeys table with indexed hashed_user_id field (single query!)
            params = {
                "filter[hashed_user_id][_eq]": hashed_user_id,
                "fields": "user_id",  # Get user_id directly
                "limit": 1
            }
            passkeys = await self.get_items("user_passkeys", params=params, no_cache=True)
            
            if passkeys and len(passkeys) > 0:
                user_id = passkeys[0].get("user_id")
                if user_id:
                    logger.debug(f"Found user_id {user_id[:6]}... for hashed_user_id {hashed_user_id[:8]}...")
                    return user_id
                else:
                    logger.warning(f"user_passkeys record found but user_id is missing for hashed_user_id: {hashed_user_id[:8]}...")
                    return None
            else:
                logger.warning(f"No passkey found for hashed_user_id: {hashed_user_id[:8]}...")
                return None
        except Exception as e:
            logger.error(f"Exception getting user_id from hashed_user_id {hashed_user_id[:8]}...: {e}", exc_info=True)
            return None

    async def get_user_api_keys_by_user_id(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves all API keys for a user by user_id (UUID).
        Queries directly by user_id field for efficient lookups.
        
        Args:
            user_id: The user's UUID
            
        Returns:
            List of API key records with fields:
            - id (for delete operations)
            - key_hash (for validation)
            - encrypted_key_prefix (client decrypts for display)
            - encrypted_name (client decrypts for display)
            - expires_at (expiration timestamp)
            - last_used_at (last usage timestamp)
            - created_at (creation timestamp)
        """
        params = {
            "filter[user_id][_eq]": user_id,
            "fields": "id,key_hash,encrypted_key_prefix,encrypted_name,expires_at,last_used_at,created_at",
            "sort": "-created_at"  # Most recently created first
        }
        try:
            items = await self.get_items("api_keys", params)
            return items if items else []
        except Exception as e:
            logger.error(f"Exception getting user API keys for user_id {user_id[:8]}...: {e}", exc_info=True)
            return []

    async def get_api_key_by_hash(self, key_hash: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves an API key by its hash (for authentication).
        
        Args:
            key_hash: SHA-256 hash of the API key
            
        Returns:
            API key record if found, None otherwise
        """
        params = {
            "filter[key_hash][_eq]": key_hash,
            "fields": "id,user_id,hashed_user_id,key_hash,encrypted_name,expires_at,last_used_at",
            "limit": 1
        }
        try:
            items = await self.get_items("api_keys", params)
            if items:
                return items[0]
            return None
        except Exception as e:
            logger.error(f"Exception getting API key by hash: {e}", exc_info=True)
            return None

    async def create_api_key(
        self,
        user_id: str,
        hashed_user_id: str,
        key_hash: str,
        encrypted_key_prefix: str,
        encrypted_name: str,
        expires_at: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Creates a new API key record in the api_keys collection.
        
        Args:
            user_id: The user's UUID
            hashed_user_id: SHA256 hash of user_id
            key_hash: SHA-256 hash of the full API key
            encrypted_key_prefix: Client-side encrypted key prefix
            encrypted_name: Client-side encrypted API key name
            expires_at: Optional expiration timestamp (ISO format)
            
        Returns:
            Created API key record if successful, None otherwise
        """
        # Set created_at and updated_at timestamps (ISO format for Directus timestamp fields)
        from datetime import datetime, timezone
        current_timestamp = datetime.now(timezone.utc).isoformat()
        
        payload = {
            "user_id": user_id,
            "hashed_user_id": hashed_user_id,
            "key_hash": key_hash,
            "encrypted_key_prefix": encrypted_key_prefix,
            "encrypted_name": encrypted_name,
            "created_at": current_timestamp,
            "updated_at": current_timestamp,
        }
        if expires_at:
            payload["expires_at"] = expires_at
        
        try:
            success, created_item = await self.create_item("api_keys", payload)
            if success and created_item:
                logger.info(f"Successfully created API key for user {user_id}")
                return created_item
            else:
                logger.error(f"Failed to create API key for user {user_id} - no item returned.")
                return None
        except Exception as e:
            logger.error(f"Exception creating API key for user {user_id}: {e}", exc_info=True)
            return None

    async def delete_api_key(self, api_key_id: str) -> bool:
        """
        Deletes an API key by its ID.
        
        Args:
            api_key_id: The API key record ID
            
        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            success = await self.delete_item("api_keys", api_key_id)
            if success:
                logger.info(f"Successfully deleted API key {api_key_id}")
            return success
        except Exception as e:
            logger.error(f"Exception deleting API key {api_key_id}: {e}", exc_info=True)
            return False

    async def update_api_key_last_used(self, key_hash: str) -> bool:
        """
        Updates the last_used_at timestamp for an API key.
        
        Args:
            key_hash: SHA-256 hash of the API key
            
        Returns:
            True if updated successfully, False otherwise
        """
        try:
            # First get the API key to find its ID
            api_key = await self.get_api_key_by_hash(key_hash)
            if not api_key:
                logger.warning(f"API key not found for hash update: {key_hash[:16]}...")
                return False
            
            api_key_id = api_key.get("id")
            if not api_key_id:
                logger.error(f"API key record missing ID: {key_hash[:16]}...")
                return False
            
            # Update last_used_at
            update_data = {
                "last_used_at": datetime.now(timezone.utc).isoformat()
            }
            updated = await self._update_item("api_keys", api_key_id, update_data)
            return updated is not None
        except Exception as e:
            logger.error(f"Exception updating API key last_used_at for hash {key_hash[:16]}...: {e}", exc_info=True)
            return False

    async def _update_item(self, collection: str, item_id: str, data: Dict[str, Any], params: Optional[Dict] = None) -> Optional[Dict]:
        """
        Internal helper to update an item in a Directus collection by its ID.
        Handles authentication and retries.
        """
        url = f"{self.base_url}/items/{collection}/{item_id}"
        
        response_obj = await self._make_api_request(
            "PATCH", url, json=data, params=params
        )

        # _make_api_request returns httpx.Response object or None on error
        if response_obj is None:
            logger.error(f"Failed to update item {item_id} in collection {collection} - request returned None")
            return None
            
        try:
            if 200 <= response_obj.status_code < 300:
                # Handle 204 No Content - success with no response body
                if response_obj.status_code == 204:
                    logger.info(f"Successfully updated item {item_id} in collection {collection} (204 No Content)")
                    return {"success": True}  # Return success indicator instead of None
                
                response_json = response_obj.json()
                if response_json and isinstance(response_json, dict) and 'data' in response_json:
                    logger.info(f"Successfully updated item {item_id} in collection {collection}")
                    return response_json.get('data')  # Return the updated item data
                else:
                    logger.warning(f"Update item response for {collection}/{item_id} has unexpected JSON format: {response_json}")
                    return response_json  # Return raw JSON if format is unexpected
            else:
                logger.error(f"Failed to update item {item_id} in collection {collection}. Status: {response_obj.status_code}, Response: {response_obj.text[:200]}")
                return None
        except Exception as e:
            logger.error(f"Error parsing update response for {collection}/{item_id}: {e}. Status: {response_obj.status_code}, Response: {response_obj.text[:200]}", exc_info=True)
            return None

    # Assign the internal helper to the class
    update_item = _update_item

    # Bind create_item from api_methods
    create_item = create_item

    async def _delete_item(self, collection: str, item_id: str, params: Optional[Dict] = None) -> bool:
        """
        Internal helper to delete an item from a Directus collection by its ID.
        Handles authentication and retries.
        Returns True if deletion was successful (204 No Content), False otherwise.
        """
        url = f"{self.base_url}/items/{collection}/{item_id}"
        
        response_obj = await self._make_api_request(
            "DELETE", url, params=params
        )

        if response_obj is not None:
            if response_obj.status_code == 204: # No Content
                logger.info(f"Successfully deleted item {item_id} from collection {collection}")
                return True
            else:
                logger.error(f"Failed to delete item {item_id} from collection {collection}. Status: {response_obj.status_code}, Response: {response_obj.text[:200]}")
                return False
        else:
            # _make_api_request already logs errors if it returns None
            logger.error(f"API request to delete item {item_id} in collection {collection} failed (request layer).")
            return False

    # Assign the internal helper to the class
    delete_item = _delete_item

    async def bulk_delete_items(self, collection: str, item_ids: List[str], params: Optional[Dict] = None) -> bool:
        """
        Bulk delete multiple items from a Directus collection in a single HTTP request.
        This is more efficient than deleting items one by one.
        
        Args:
            collection: The name of the Directus collection
            item_ids: List of item IDs to delete
            params: Optional query parameters
            
        Returns:
            True if all items were successfully deleted, False otherwise
        """
        if not item_ids:
            logger.warning(f"bulk_delete_items called with empty item_ids list for collection {collection}")
            return True  # Nothing to delete is considered success
        
        url = f"{self.base_url}/items/{collection}"
        
        # Get authentication token
        token = await self.ensure_auth_token()
        if not token:
            logger.error("Failed to get authentication token for bulk delete")
            return False
        
        # Prepare headers and body
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        body = json.dumps({"keys": item_ids})
        
        try:
            # Use httpx's generic request() method which supports content for DELETE
            # The convenience method delete() doesn't support json/content parameters
            response_obj = await self._client.request(
                "DELETE",
                url,
                content=body,
                headers=headers,
                params=params,
                timeout=3.0
            )
            
            if response_obj.status_code == 204:  # No Content - success
                logger.info(f"Successfully bulk deleted {len(item_ids)} items from collection {collection}")
                return True
            else:
                logger.error(
                    f"Failed to bulk delete {len(item_ids)} items from collection {collection}. "
                    f"Status: {response_obj.status_code}, Response: {response_obj.text[:200]}"
                )
                return False
                
        except Exception as e:
            logger.error(
                f"Exception during bulk delete of {len(item_ids)} items in collection {collection}: {e}",
                exc_info=True
            )
            return False

    # Authentication methods
    get_auth_lock = get_auth_lock
    clear_tokens = clear_tokens
    validate_token = validate_token
    login_admin = login_admin
    ensure_auth_token = ensure_auth_token
    
    # API request method
    _make_api_request = _make_api_request

    # Invite code methods
    get_invite_code = get_invite_code
    get_all_invite_codes = get_all_invite_codes
    consume_invite_code = consume_invite_code # Assign the imported method
    
    # Gift card methods
    get_gift_card_by_code = get_gift_card_by_code
    get_all_gift_cards = get_all_gift_cards
    redeem_gift_card = redeem_gift_card
    
    # User management methods
    create_user = create_user
    login_user = login_user
    login_user_with_lookup_hash = login_user_with_lookup_hash
    logout_user = logout_user
    logout_all_sessions = logout_all_sessions
    get_user_by_hashed_email = get_user_by_hashed_email
    refresh_token = refresh_token
    get_total_users_count = get_total_users_count
    get_active_users_since = get_active_users_since
    delete_user = delete_user
    update_user = update_user
    
    # User profile methods - get_user_profile is the main one now
    get_user_profile = get_user_profile
    get_tfa_backup_code_hashes = get_tfa_backup_code_hashes
    
    # User lookup methods
    get_user_fields_direct = get_user_fields_direct
    get_encryption_key = get_encryption_key
    authenticate_user_by_lookup_hash = authenticate_user_by_lookup_hash
    add_user_lookup_hash = add_user_lookup_hash
    get_user_by_subscription_id = get_user_by_subscription_id

    # Device management methods
    add_user_device_hash = add_user_device_hash # Updated
    get_user_device_hashes = get_user_device_hashes # Updated
    
    # API key device management methods
    get_api_key_device_by_hash = get_api_key_device_by_hash
    create_api_key_device = create_api_key_device
    update_api_key_device_last_access = update_api_key_device_last_access
    get_api_key_devices = get_api_key_devices
    approve_api_key_device = approve_api_key_device
    revoke_api_key_device = revoke_api_key_device
    get_pending_api_key_devices = get_pending_api_key_devices
    update_api_key_device_name = update_api_key_device_name

    # Chat methods are accessed via self.chat.method_name
    # e.g., await self.chat.get_chat_metadata(chat_id)

    # App Settings and Memories methods are accessed via self.app_settings_and_memories.method_name
    # Example: await self.app_settings_and_memories.get_user_app_item_raw(user_id_hash, app_id, item_key)
