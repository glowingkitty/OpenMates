import os
import time
import logging
import json
import httpx # Import httpx
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService

from typing import List, Dict, Any, Optional
# Import method implementations
from backend.core.api.app.services.directus.auth_methods import (
    get_auth_lock, clear_tokens, validate_token, login_admin, ensure_auth_token
)
from backend.core.api.app.services.directus.api_methods import _make_api_request, create_item # Import create_item
from backend.core.api.app.services.directus.invite_methods import get_invite_code, get_all_invite_codes, consume_invite_code
from backend.core.api.app.services.directus.chat_methods import ChatMethods # Import ChatMethods class
# from backend.core.api.app.services.directus.app_memory_methods import AppMemoryMethods # Old import, replaced
from backend.core.api.app.services.directus.app_settings_and_memories_methods import AppSettingsAndMemoriesMethods # New import
from backend.core.api.app.services.directus.usage import UsageMethods # Corrected import
from backend.core.api.app.services.directus.user.user_creation import create_user
from backend.core.api.app.services.directus.user.user_authentication import login_user, login_user_with_lookup_hash, logout_user, logout_all_sessions, refresh_token
from backend.core.api.app.services.directus.user.user_lookup import get_user_by_hashed_email, get_total_users_count, get_active_users_since, get_user_fields_direct, authenticate_user_by_lookup_hash, add_user_lookup_hash
from backend.core.api.app.services.directus.user.user_profile import get_user_profile, get_tfa_backup_code_hashes
from backend.core.api.app.services.directus.user.delete_user import delete_user
from backend.core.api.app.services.directus.user.update_user import update_user
# Import device management methods
from backend.core.api.app.services.directus.user.device_management import add_user_device_hash, get_user_device_hashes # Updated imports

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
        self.chat = ChatMethods(self) # Initialize ChatMethods

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
        sensitive_collections = ['directus_users', 'directus_roles', 'directus_permissions']
        
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

    async def create_encryption_key(self, hashed_user_id: str, login_method: str, encrypted_key: str, salt: str) -> bool:
        """
        Creates a new record in the encryption_keys collection.
        """
        payload = {
            "hashed_user_id": hashed_user_id,
            "login_method": login_method,
            "encrypted_key": encrypted_key,
            "salt": salt,
        }
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
        Retrieves the encrypted key and salt for a user and login method.
        """
        params = {
            "filter[hashed_user_id][_eq]": hashed_user_id,
            "filter[login_method][_eq]": login_method,
            "fields": "encrypted_key,salt",
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

    # Device management methods
    add_user_device_hash = add_user_device_hash # Updated
    get_user_device_hashes = get_user_device_hashes # Updated

    # Chat methods are accessed via self.chat.method_name
    # e.g., await self.chat.get_chat_metadata(chat_id)

    # App Settings and Memories methods are accessed via self.app_settings_and_memories.method_name
    # Example: await self.app_settings_and_memories.get_user_app_item_raw(user_id_hash, app_id, item_key)
