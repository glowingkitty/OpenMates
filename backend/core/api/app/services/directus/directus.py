import os
import time
import logging
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
from backend.core.api.app.services.directus.chat_methods import get_chat_metadata, get_user_chats_metadata, update_chat_metadata # Import chat methods
# from backend.core.api.app.services.directus.app_memory_methods import AppMemoryMethods # Old import, replaced
from backend.core.api.app.services.directus.app_settings_and_memories_methods import AppSettingsAndMemoriesMethods # New import
from backend.core.api.app.services.directus.usage_methods import UsageMethods # Import UsageMethods
from backend.core.api.app.services.directus.user.user_creation import create_user
from backend.core.api.app.services.directus.user.user_authentication import login_user, logout_user, logout_all_sessions, refresh_token
from backend.core.api.app.services.directus.user.user_lookup import get_user_by_email, get_total_users_count, get_active_users_since, get_user_fields_direct
from backend.core.api.app.services.directus.user.user_profile import get_user_profile
from backend.core.api.app.services.directus.user.delete_user import delete_user
from backend.core.api.app.services.directus.user.update_user import update_user
# Import device management methods
from backend.core.api.app.services.directus.user.device_management import update_user_device_record, get_stored_device_data

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
        self.usage = UsageMethods(self._client, self.base_url, self.token) # Pass the client instance

    async def close(self):
        """Close the httpx client."""
        await self._client.aclose()
        logger.info("DirectusService httpx client closed.")

    async def get_items(self, collection, params=None, no_cache=True):
        """
        Fetch items from a Directus collection with optional query params.
        Returns the list of items directly.
        """
        url = f"{self.base_url}/items/{collection}"
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        # Optionally bypass Directus cache using no-store
        if no_cache:
            headers["Cache-Control"] = "no-store" # Use no-store as per docs for CACHE_SKIP_ALLOWED
            # Ensure params is a dictionary to add our cache-busting timestamp
            current_params = dict(params or {})
            current_params["_ts"] = str(time.time_ns()) # Timestamp for cache busting
            # The "cache!=clear" parameter is not standard; Cache-Control header is preferred.
        else:
            current_params = params # Use original params if no_cache is False
        
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
    async def _update_item(self, collection: str, item_id: str, data: Dict[str, Any], params: Optional[Dict] = None) -> Optional[Dict]:
        """
        Internal helper to update an item in a Directus collection by its ID.
        Handles authentication and retries.
        """
        url = f"{self.base_url}/items/{collection}/{item_id}"
        
        response_data = await self._make_api_request(
            "PATCH", url, json=data, params=params
        )

        # _make_api_request returns the parsed JSON response or None on error
        if response_data and isinstance(response_data, dict) and 'data' in response_data:
             logger.info(f"Successfully updated item {item_id} in collection {collection}")
             return response_data.get('data') # Return the updated item data
        elif response_data:
             logger.warning(f"Update item response for {collection}/{item_id} has unexpected format: {response_data}")
             return response_data # Return raw response if format is unexpected but not None
        else:
             logger.error(f"Failed to update item {item_id} in collection {collection}")
             return None

    # Assign the internal helper to the class
    update_item = _update_item

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
    logout_user = logout_user
    logout_all_sessions = logout_all_sessions
    get_user_by_email = get_user_by_email
    refresh_token = refresh_token
    get_total_users_count = get_total_users_count
    get_active_users_since = get_active_users_since
    delete_user = delete_user
    update_user = update_user
    
    # User profile methods - get_user_profile is the main one now
    get_user_profile = get_user_profile
    
    # User lookup methods
    get_user_fields_direct = get_user_fields_direct

    # Device management methods
    update_user_device_record = update_user_device_record
    get_stored_device_data = get_stored_device_data

    # Chat methods
    get_chat_metadata = get_chat_metadata
    get_user_chats_metadata = get_user_chats_metadata
    update_chat_metadata = update_chat_metadata

    # App Settings and Memories methods are accessed via self.app_settings_and_memories.method_name
    # Example: await self.app_settings_and_memories.get_user_app_item_raw(user_id_hash, app_id, item_key)
