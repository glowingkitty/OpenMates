"""
Shared dependencies for authentication routes.
This file contains functions that provide services to all auth-related endpoints,
including retrieving the currently authenticated user.
"""
from fastapi import Request, HTTPException, Depends, Cookie
from typing import Optional

# Import services and models needed by get_current_user
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.models.user import User

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
    refresh_token: Optional[str] = Cookie(None, alias="auth_refresh_token")
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
        # Ensure all fields expected by the User model are present, providing defaults if necessary
        return User(
            id=cached_data.get("user_id"),
            username=cached_data.get("username"),
            is_admin=cached_data.get("is_admin", False),
            credits=cached_data.get("credits", 0),
            profile_image_url=cached_data.get("profile_image_url"),
            tfa_app_name=cached_data.get("tfa_app_name"),
            last_opened=cached_data.get("last_opened"),
            vault_key_id=cached_data.get("vault_key_id"),
            consent_privacy_and_apps_default_settings=cached_data.get("consent_privacy_and_apps_default_settings"),
            consent_mates_default_settings=cached_data.get("consent_mates_default_settings"),
            language=cached_data.get("language", 'en'), 
            darkmode=cached_data.get("darkmode", False),
            gifted_credits_for_signup=cached_data.get("gifted_credits_for_signup"),
            encrypted_email_address=cached_data.get("encrypted_email_address")
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
    success, user_data, _ = await directus_service.get_user_profile(user_id)
    if not success or not user_data:
        raise HTTPException(status_code=401, detail="Could not fetch user data")

    # Create User object from profile data
    # The get_user_profile function now returns decrypted fields directly
    user = User(
        id=user_id,
        username=user_data.get("username"),
        is_admin=user_data.get("is_admin", False),
        credits=user_data.get("credits", 0),
        profile_image_url=user_data.get("profile_image_url"),
        last_opened=user_data.get("last_opened"),
        vault_key_id=user_data.get("vault_key_id"),
        tfa_app_name=user_data.get("tfa_app_name"),
        consent_privacy_and_apps_default_settings=user_data.get("consent_privacy_and_apps_default_settings"),
        consent_mates_default_settings=user_data.get("consent_mates_default_settings"),
        language=user_data.get("language", 'en'),
        darkmode=user_data.get("darkmode", False),
        gifted_credits_for_signup=user_data.get("gifted_credits_for_signup"), # Include new field
        encrypted_email_address=user_data.get("encrypted_email_address"),
        invoice_counter=user_data.get("invoice_counter", 0)
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
        "invoice_counter": user.invoice_counter
    }
    # Remove gifted_credits_for_signup if it's None before caching
    if not user_data_for_cache.get("gifted_credits_for_signup"):
        user_data_for_cache.pop("gifted_credits_for_signup", None)

    await cache_service.set_user(user_data_for_cache, refresh_token=refresh_token)
    
    return user
