import os
import time
import logging
from app.services.cache import CacheService
from app.utils.encryption import EncryptionService

from typing import List, Dict, Any, Optional
# Import method implementations
from app.services.directus.auth_methods import (
    get_auth_lock, clear_tokens, validate_token, login_admin, ensure_auth_token
)
from app.services.directus.api_methods import _make_api_request, create_item # Import create_item
from app.services.directus.invite_methods import get_invite_code, get_all_invite_codes, consume_invite_code
from app.services.directus.chat_methods import get_chat_metadata, get_user_chats_metadata, update_chat_metadata # Import chat methods
from app.services.directus.user.user_creation import create_user
from app.services.directus.user.user_authentication import login_user, logout_user, logout_all_sessions, refresh_token
from app.services.directus.user.user_lookup import get_user_by_email, get_total_users_count, get_active_users_since, get_user_fields_direct
from app.services.directus.user.user_profile import get_user_profile
from app.services.directus.user.delete_user import delete_user
from app.services.directus.user.update_user import update_user
# Import device management methods
from app.services.directus.user.device_management import update_user_device_record, get_stored_device_data

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
        
        if self.token:
            masked_token = self.token[:4] + "..." + self.token[-4:] if len(self.token) > 8 else "****"
            logger.info(f"DirectusService initialized with URL: {self.base_url}, Token: {masked_token}")
        else:
            logger.warning("DirectusService initialized WITHOUT a token! Will try to authenticate with admin credentials.")

    async def get_items(self, collection, params=None, no_cache=False):
        """
        Fetch items from a Directus collection with optional query params.
        Returns the list of items directly.
        """
        url = f"{self.base_url}/items/{collection}"
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        # Optionally bypass Directus cache using no-store
        if no_cache:
            headers["Cache-Control"] = "no-store" # Use no-store as per docs for CACHE_SKIP_ALLOWED
            params = dict(params or {})
            params["_ts"] = str(time.time_ns())
        
        # _make_api_request returns an httpx.Response object.
        response_obj = await self._make_api_request("GET", url, headers=headers, params=params or {})

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
        await self.ensure_auth_token() # Ensure we have a valid token
        if not self.auth_token:
            logger.error(f"Cannot update item in {collection}: Authentication failed.")
            return None

        url = f"{self.base_url}/items/{collection}/{item_id}"
        headers = {"Authorization": f"Bearer {self.auth_token}"}

        # Use the internal _make_api_request method with PATCH verb
        response_data = await self._make_api_request("PATCH", url, headers=headers, json_data=data, params=params)

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
