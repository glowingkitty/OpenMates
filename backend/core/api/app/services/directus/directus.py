import os
import logging
from app.services.cache import CacheService
from app.utils.encryption import EncryptionService

# Import method implementations
from app.services.directus.auth_methods import (
    get_auth_lock, clear_tokens, validate_token, login_admin, ensure_auth_token
)
from app.services.directus.api_methods import _make_api_request
from app.services.directus.invite_methods import get_invite_code, get_all_invite_codes
from app.services.directus.user import (
    create_user, update_user_device, update_user_devices, login_user, logout_user,
    logout_all_sessions, get_user_by_email, refresh_token, get_total_users_count,
    get_active_users_since, check_user_device, get_user_credits, get_user_username,
    get_user_profile_image, invalidate_user_profile_cache, get_user_profile, delete_user, update_user
)

logger = logging.getLogger(__name__)

class DirectusService:
    """
    Service for interacting with Directus CMS API
    """
    
    def __init__(self, cache_service: CacheService = None, encryption_service: EncryptionService = None): # Added encryption_service parameter
        self.base_url = os.getenv("CMS_URL", "http://cms:8055")
        self.token = os.getenv("CMS_TOKEN")
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
    
    # User management methods
    create_user = create_user
    update_user_device = update_user_device
    update_user_devices = update_user_devices
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
    
    # User profile methods
    get_user_profile = get_user_profile
    get_user_credits = get_user_credits
    get_user_username = get_user_username
    get_user_profile_image = get_user_profile_image
    invalidate_user_profile_cache = invalidate_user_profile_cache
