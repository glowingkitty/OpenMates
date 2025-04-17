import os
import time
import logging
from app.services.cache import CacheService
from app.utils.encryption import EncryptionService

# Import method implementations
from app.services.directus.auth_methods import (
    get_auth_lock, clear_tokens, validate_token, login_admin, ensure_auth_token
)
from app.services.directus.api_methods import _make_api_request, create_item # Import create_item
from app.services.directus.invite_methods import get_invite_code, get_all_invite_codes, consume_invite_code
from app.services.directus.user.user_creation import create_user
from app.services.directus.user.device_management import update_user_device, check_user_device
from app.services.directus.user.user_authentication import login_user, logout_user, logout_all_sessions, refresh_token
from app.services.directus.user.user_lookup import get_user_by_email, get_total_users_count, get_active_users_since, get_user_fields_direct
from app.services.directus.user.user_profile import get_user_profile
from app.services.directus.user.delete_user import delete_user
from app.services.directus.user.update_user import update_user

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
        Supports filters and meta (e.g., total_count).
        """
        url = f"{self.base_url}/items/{collection}"
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        # Optionally bypass Directus cache
        if no_cache:
            headers["Cache-Control"] = "no-cache"
            headers["Pragma"] = "no-cache"
            params = dict(params or {})
            params["_ts"] = str(time.time_ns())
        # Use the internal _make_api_request method
        response = await self._make_api_request("GET", url, headers=headers, params=params or {})
        return response

    # Item creation method
    create_item = create_item # Assign the imported method

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
    update_user_device = update_user_device
    login_user = login_user
    logout_user = logout_user
    logout_all_sessions = logout_all_sessions
    get_user_by_email = get_user_by_email
    refresh_token = refresh_token
    get_total_users_count = get_total_users_count
    get_active_users_since = get_active_users_since
    check_user_device = check_user_device
    delete_user = delete_user
    update_user = update_user
    
    # User profile methods - get_user_profile is the main one now
    get_user_profile = get_user_profile
    
    # User lookup methods
    get_user_fields_direct = get_user_fields_direct
