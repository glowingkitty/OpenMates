"""
Shared dependencies for authentication routes.
This file contains functions that provide services to all auth-related endpoints,
including retrieving the currently authenticated user.
"""
import logging
from fastapi import Request, HTTPException, Depends, Cookie
from typing import Optional

# Import services and models needed by get_current_user
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.models.user import User

logger = logging.getLogger(__name__)

# All functions now accept Request and fetch services from backend.core.api.app.state
# (Keep existing service getters)

def get_directus_service(request: Request):
    """Get the Directus service instance from app state."""
    return request.app.state.directus_service

def get_cache_service(request: Request):
    """Get the Cache service instance from app state."""
    return request.app.state.cache_service

def get_metrics_service(request: Request):
    """Get the Metrics service instance from app state."""
    return request.app.state.metrics_service
    
def get_encryption_service(request: Request):
    """Get the Encryption service instance from app state."""
    return request.app.state.encryption_service

def get_compliance_service(request: Request):
    """Get the Compliance service instance from app state."""
    return request.app.state.compliance_service

def get_email_template_service(request: Request):
    """Get the Email Template service instance from app state."""
    return request.app.state.email_template_service

def get_secrets_manager(request: Request):
    """Get the Secrets Manager instance from app state."""
    return request.app.state.secrets_manager


# --- Moved from settings.py ---
async def get_current_user(
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token", include_in_schema=False)  # Hidden from API docs - internal use only
) -> User:
    """
    Retrieves the current authenticated user based on the refresh token cookie.
    Checks cache first, then validates token and fetches profile if needed.
    Caches the user data on successful retrieval.
    Raises HTTPException(401) if not authenticated or token is invalid.
    """
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Not authenticated: Missing token")
    
    # Check cache first using the enhanced cache service method
    cached_data = await cache_service.get_user_by_token(refresh_token)

    if cached_data:
        # CRITICAL: Validate required fields before creating User object - fail fast if missing
        # These fields are required by the User model and must not be None
        cached_user_id = cached_data.get("user_id")
        cached_username = cached_data.get("username")
        cached_vault_key_id = cached_data.get("vault_key_id")
        
        if not cached_user_id:
            logger.error(f"CRITICAL: user_id is missing from cached data for token")
            raise HTTPException(status_code=500, detail="User data incomplete: missing user ID")
        
        if not cached_username:
            logger.error(f"CRITICAL: username is missing from cached data for user {cached_user_id}")
            raise HTTPException(status_code=500, detail="User data incomplete: missing username")
        
        if not cached_vault_key_id:
            logger.error(f"CRITICAL: vault_key_id is missing from cached data for user {cached_user_id}")
            raise HTTPException(status_code=500, detail="User data incomplete: missing encryption key")
        
        # Ensure all fields expected by the User model are present, providing defaults if necessary
        return User(
            id=cached_user_id,
            username=cached_username,
            # Handle None values for boolean fields - default to False if None
            is_admin=cached_data.get("is_admin") or False,
            credits=cached_data.get("credits", 0),
            profile_image_url=cached_data.get("profile_image_url"),
            tfa_app_name=cached_data.get("tfa_app_name"),
            last_opened=cached_data.get("last_opened"),
            vault_key_id=cached_vault_key_id,
            consent_privacy_and_apps_default_settings=cached_data.get("consent_privacy_and_apps_default_settings"),
            consent_mates_default_settings=cached_data.get("consent_mates_default_settings"),
            language=cached_data.get("language", 'en'),
            darkmode=cached_data.get("darkmode") or False,
            gifted_credits_for_signup=cached_data.get("gifted_credits_for_signup"),
            encrypted_email_address=cached_data.get("encrypted_email_address"),
            encrypted_key=cached_data.get("encrypted_key"),
            salt=cached_data.get("salt"),
            user_email_salt=cached_data.get("user_email_salt"),
            lookup_hashes=cached_data.get("lookup_hashes"),
            account_id=cached_data.get("account_id"),
            invoice_counter=cached_data.get("invoice_counter"),
            # Monthly subscription fields
            encrypted_payment_method_id=cached_data.get("encrypted_payment_method_id"),
            stripe_customer_id=cached_data.get("stripe_customer_id"),
            stripe_subscription_id=cached_data.get("stripe_subscription_id"),
            subscription_status=cached_data.get("subscription_status"),
            subscription_credits=cached_data.get("subscription_credits"),
            subscription_currency=cached_data.get("subscription_currency"),
            next_billing_date=cached_data.get("next_billing_date"),
            subscription_billing_day_preference=cached_data.get("subscription_billing_day_preference"),
            # Low balance auto top-up fields
            # Handle None values explicitly - if field is None in DB, default to False
            auto_topup_low_balance_enabled=cached_data.get("auto_topup_low_balance_enabled") or False,
            auto_topup_low_balance_threshold=cached_data.get("auto_topup_low_balance_threshold"),
            auto_topup_low_balance_amount=cached_data.get("auto_topup_low_balance_amount"),
            auto_topup_low_balance_currency=cached_data.get("auto_topup_low_balance_currency"),
            encrypted_auto_topup_last_triggered=cached_data.get("encrypted_auto_topup_last_triggered")
        )
    
    # If no cache hit, validate token and get user data
    # Note: validate_token might need adjustment if it wasn't moved/updated
    success, token_data = await directus_service.validate_token(refresh_token)
    if not success or not token_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    # Get user ID from token data
    user_id = token_data.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token data: Missing user ID")

    # Fetch complete user profile (which now includes decrypted gifted_credits_for_signup)
    success, user_data, profile_message = await directus_service.get_user_profile(user_id)
    if not success or not user_data:
        logger.error(f"Failed to fetch user profile for user {user_id}: {profile_message}")
        raise HTTPException(status_code=500, detail=f"Could not fetch user data: {profile_message}")

    # CRITICAL: Validate required fields before creating User object - fail fast if missing
    # These fields are required by the User model and must not be None
    profile_username = user_data.get("username")
    profile_vault_key_id = user_data.get("vault_key_id")
    
    if not profile_username:
        logger.error(f"CRITICAL: username is missing from user profile for user {user_id}")
        logger.error(f"Profile data keys: {list(user_data.keys())}")
        raise HTTPException(status_code=500, detail="User data incomplete: missing username. This indicates a data integrity issue.")
    
    if not profile_vault_key_id:
        logger.error(f"CRITICAL: vault_key_id is missing from user profile for user {user_id}")
        logger.error(f"Profile data keys: {list(user_data.keys())}")
        raise HTTPException(status_code=500, detail="User data incomplete: missing encryption key. This indicates a data integrity issue.")

    # Create User object from profile data
    # The get_user_profile function now returns decrypted fields directly
    user = User(
        id=user_id,
        username=profile_username,
        # Handle None values for boolean fields - default to False if None
        is_admin=user_data.get("is_admin") or False,
        credits=user_data.get("credits", 0),
        profile_image_url=user_data.get("profile_image_url"),
        last_opened=user_data.get("last_opened"),
        vault_key_id=profile_vault_key_id,
        tfa_app_name=user_data.get("tfa_app_name"),
        consent_privacy_and_apps_default_settings=user_data.get("consent_privacy_and_apps_default_settings"),
        consent_mates_default_settings=user_data.get("consent_mates_default_settings"),
        language=user_data.get("language", 'en'),
        darkmode=user_data.get("darkmode") or False,
        gifted_credits_for_signup=user_data.get("gifted_credits_for_signup"), # Include new field
        encrypted_email_address=user_data.get("encrypted_email_address"),
        invoice_counter=user_data.get("invoice_counter", 0),
        encrypted_key=user_data.get("encrypted_key"),
        salt=user_data.get("salt"),
        user_email_salt=user_data.get("user_email_salt"),
        lookup_hashes=user_data.get("lookup_hashes"),
        account_id=user_data.get("account_id"),
        # Monthly subscription fields
        encrypted_payment_method_id=user_data.get("encrypted_payment_method_id"),
        stripe_customer_id=user_data.get("stripe_customer_id"),
        stripe_subscription_id=user_data.get("stripe_subscription_id"),
        subscription_status=user_data.get("subscription_status"),
        subscription_credits=user_data.get("subscription_credits"),
        subscription_currency=user_data.get("subscription_currency"),
        next_billing_date=user_data.get("next_billing_date"),
        subscription_billing_day_preference=user_data.get("subscription_billing_day_preference"),
        # Low balance auto top-up fields
        # Handle None values explicitly - if field is None in DB, default to False
        auto_topup_low_balance_enabled=user_data.get("auto_topup_low_balance_enabled") or False,
        auto_topup_low_balance_threshold=user_data.get("auto_topup_low_balance_threshold"),
        auto_topup_low_balance_amount=user_data.get("auto_topup_low_balance_amount"),
        auto_topup_low_balance_currency=user_data.get("auto_topup_low_balance_currency"),
        encrypted_auto_topup_last_triggered=user_data.get("encrypted_auto_topup_last_triggered")
    )
    
    # Cache the user data for future requests using the enhanced cache service method
    # Prepare standardized user data for cache (match structure used elsewhere)
    user_data_for_cache = {
        "user_id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "credits": user.credits,
        "profile_image_url": user.profile_image_url,
        "tfa_app_name": user.tfa_app_name,
        "last_opened": user.last_opened,
        "vault_key_id": user.vault_key_id,
        "consent_privacy_and_apps_default_settings": user.consent_privacy_and_apps_default_settings,
        "consent_mates_default_settings": user.consent_mates_default_settings,
        # Determine tfa_enabled based on whether encrypted_tfa_secret exists in the raw user_data fetched by get_user_profile
        # This requires get_user_profile to potentially return the raw data or tfa_enabled status
        # Assuming get_user_profile adds 'tfa_enabled' based on its logic:
        "tfa_enabled": user_data.get("tfa_enabled", False),
        "language": user.language,
        "darkmode": user.darkmode,
        "gifted_credits_for_signup": user.gifted_credits_for_signup, # Include new field
        "encrypted_email_address": user.encrypted_email_address,
        "invoice_counter": user.invoice_counter,
        "encrypted_key": user_data.get("encrypted_key"),
        "salt": user_data.get("salt"),
        "user_email_salt": user_data.get("user_email_salt"),
        "lookup_hashes": user_data.get("lookup_hashes"),
        "account_id": user_data.get("account_id"),
        # Monthly subscription fields
        "encrypted_payment_method_id": user.encrypted_payment_method_id,
        "stripe_customer_id": user.stripe_customer_id,
        "stripe_subscription_id": user.stripe_subscription_id,
        "subscription_status": user.subscription_status,
        "subscription_credits": user.subscription_credits,
        "subscription_currency": user.subscription_currency,
        "next_billing_date": user.next_billing_date,
        "subscription_billing_day_preference": user.subscription_billing_day_preference,
        # Low balance auto top-up fields
        "auto_topup_low_balance_enabled": user.auto_topup_low_balance_enabled,
        "auto_topup_low_balance_threshold": user.auto_topup_low_balance_threshold,
        "auto_topup_low_balance_amount": user.auto_topup_low_balance_amount,
        "auto_topup_low_balance_currency": user.auto_topup_low_balance_currency,
        "encrypted_auto_topup_last_triggered": user.encrypted_auto_topup_last_triggered
    }
    # Remove gifted_credits_for_signup if it's None before caching
    if not user_data_for_cache.get("gifted_credits_for_signup"):
        user_data_for_cache.pop("gifted_credits_for_signup", None)

    await cache_service.set_user(user_data_for_cache, refresh_token=refresh_token)
    
    return user


async def get_current_user_optional(
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token", include_in_schema=False)
) -> Optional[User]:
    """
    Optional variant of get_current_user.
    Returns None when no valid session is present instead of raising 401.
    """
    try:
        return await get_current_user(directus_service, cache_service, refresh_token)
    except HTTPException as e:
        if e.status_code == 401:
            return None
        raise


async def get_current_user_or_api_key(
    request: Request,
    directus_service: DirectusService = Depends(get_directus_service),
    cache_service: CacheService = Depends(get_cache_service),
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token", include_in_schema=False)  # Hidden from API docs - internal use only
) -> User:
    """
    Unified authentication dependency that supports both session and API key authentication.
    
    Tries session authentication first (via cookie), then falls back to API key authentication
    (via Authorization header) if session auth fails or is not available.
    
    Returns:
        User object if authenticated via either method
        
    Raises:
        HTTPException(401): If neither authentication method succeeds
    """
    # Try session authentication first
    if refresh_token:
        try:
            return await get_current_user(
                directus_service=directus_service,
                cache_service=cache_service,
                refresh_token=refresh_token
            )
        except HTTPException:
            # Session auth failed, try API key auth
            pass
    
    # Try API key authentication
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        try:
            from backend.core.api.app.utils.api_key_auth import get_api_key_auth_service
            api_key_auth_service = get_api_key_auth_service(request)
            api_key = auth_header[7:]  # Remove "Bearer " prefix
            
            user_info = await api_key_auth_service.authenticate_api_key(api_key, request=request)
            user_id = user_info.get("user_id")
            
            if user_id:
                # Fetch user profile to create User object
                success, user_data, profile_message = await directus_service.get_user_profile(user_id)
                if success and user_data:
                    # Create User object from profile data (same as get_current_user)
                    profile_username = user_data.get("username")
                    profile_vault_key_id = user_data.get("vault_key_id")
                    
                    if not profile_username or not profile_vault_key_id:
                        raise HTTPException(status_code=500, detail="User data incomplete")
                    
                    return User(
                        id=user_id,
                        username=profile_username,
                        is_admin=user_data.get("is_admin") or False,
                        credits=user_data.get("credits", 0),
                        profile_image_url=user_data.get("profile_image_url"),
                        last_opened=user_data.get("last_opened"),
                        vault_key_id=profile_vault_key_id,
                        tfa_app_name=user_data.get("tfa_app_name"),
                        consent_privacy_and_apps_default_settings=user_data.get("consent_privacy_and_apps_default_settings"),
                        consent_mates_default_settings=user_data.get("consent_mates_default_settings"),
                        language=user_data.get("language", 'en'),
                        darkmode=user_data.get("darkmode") or False,
                        gifted_credits_for_signup=user_data.get("gifted_credits_for_signup"),
                        encrypted_email_address=user_data.get("encrypted_email_address"),
                        invoice_counter=user_data.get("invoice_counter", 0),
                        encrypted_key=user_data.get("encrypted_key"),
                        salt=user_data.get("salt"),
                        user_email_salt=user_data.get("user_email_salt"),
                        lookup_hashes=user_data.get("lookup_hashes"),
                        account_id=user_data.get("account_id"),
                        encrypted_payment_method_id=user_data.get("encrypted_payment_method_id"),
                        stripe_customer_id=user_data.get("stripe_customer_id"),
                        stripe_subscription_id=user_data.get("stripe_subscription_id"),
                        subscription_status=user_data.get("subscription_status"),
                        subscription_credits=user_data.get("subscription_credits"),
                        subscription_currency=user_data.get("subscription_currency"),
                        next_billing_date=user_data.get("next_billing_date"),
                        auto_topup_low_balance_enabled=user_data.get("auto_topup_low_balance_enabled") or False,
                        auto_topup_low_balance_threshold=user_data.get("auto_topup_low_balance_threshold"),
                        auto_topup_low_balance_amount=user_data.get("auto_topup_low_balance_amount"),
                        auto_topup_low_balance_currency=user_data.get("auto_topup_low_balance_currency"),
                        encrypted_auto_topup_last_triggered=user_data.get("encrypted_auto_topup_last_triggered")
                    )
        except HTTPException:
            # API key auth failed, will raise below
            pass
        except Exception as e:
            logger.debug(f"API key authentication error: {e}")
            # Continue to raise 401 below
    
    # Neither authentication method succeeded
    raise HTTPException(status_code=401, detail="Not authenticated: Missing or invalid token/API key")
