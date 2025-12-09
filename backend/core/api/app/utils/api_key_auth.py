# backend/core/api/app/utils/api_key_auth.py
#
# This module provides API key authentication for external API access

import hashlib
import logging
from datetime import datetime, timezone
from fastapi import Request, HTTPException, status, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, Dict, Any
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.device_fingerprint import _extract_client_ip

logger = logging.getLogger(__name__)

class ApiKeyNotFoundError(Exception):
    """Raised when API key is not found or invalid"""
    pass

class DeviceNotApprovedError(Exception):
    """Raised when device is not approved for API key access"""
    pass

class ApiKeyAuthService:
    """Service for API key authentication"""

    def __init__(self, directus_service: DirectusService, cache_service: CacheService):
        self.directus_service = directus_service
        self.cache_service = cache_service

    async def hash_api_key(self, api_key: str) -> str:
        """Hash an API key using SHA-256"""
        return hashlib.sha256(api_key.encode()).hexdigest()

    async def authenticate_api_key(
        self,
        api_key: str,
        request: Optional[Request] = None
    ) -> Dict[str, Any]:
        """
        Authenticate an API key and return user information.
        Uses the new api_keys collection for efficient lookups.
        Also checks device approval if request is provided.

        Args:
            api_key: The API key to authenticate
            request: Optional FastAPI request object for device tracking

        Returns:
            Dict containing user information and API key metadata

        Raises:
            ApiKeyNotFoundError: If the API key is invalid, not found, or expired
            DeviceNotApprovedError: If the device is not approved for this API key
        """
        if not api_key or not api_key.startswith('sk-api-'):
            raise ApiKeyNotFoundError("Invalid API key format")

        try:
            # Hash the provided API key
            api_key_hash = await self.hash_api_key(api_key)

            # Try cache first for API key record (not user_info, as device approval must be checked each time)
            cache_key = f"api_key_record:{api_key_hash}"
            cached_api_key_record = await self.cache_service.get(cache_key)
            
            api_key_record = None
            if cached_api_key_record:
                api_key_record = cached_api_key_record
            else:
                # Query api_keys collection directly (much more efficient than querying all users)
                api_key_record = await self.directus_service.get_api_key_by_hash(api_key_hash)
                
                if api_key_record:
                    # Cache API key record for 5 minutes (device approval is checked separately)
                    await self.cache_service.set(cache_key, api_key_record, ttl=300)
                
            if not api_key_record:
                raise ApiKeyNotFoundError("API key not found")

            # Check if API key is expired
            expires_at = api_key_record.get('expires_at')
            if expires_at:
                try:
                    # Parse ISO format timestamp
                    if isinstance(expires_at, str):
                        expires_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                    else:
                        expires_dt = expires_at
                    
                    if expires_dt.tzinfo is None:
                        expires_dt = expires_dt.replace(tzinfo=timezone.utc)
                    
                    now = datetime.now(timezone.utc)
                    if expires_dt < now:
                        raise ApiKeyNotFoundError("API key has expired")
                except Exception as e:
                    logger.warning(f"Error checking API key expiration: {e}")
                    # Don't fail if we can't parse expiration, but log it

            # Get user_id from the API key record
            user_id = api_key_record.get('user_id')
            if not user_id:
                raise ApiKeyNotFoundError("API key record missing user_id")

            # Check device approval - BLOCKS if device is new or not approved
            # First request from new device is blocked until user approves in web UI
            device_hash = None
            if request:
                device_hash = await self._check_and_register_device(
                    api_key_id=api_key_record.get('id'),
                    user_id=user_id,
                    request=request
                )

            # Build user info response
            # API key authentication only needs user_id - no email required
            user_info = {
                'user_id': user_id,
                'api_key_id': api_key_record.get('id'),
                'api_key_hash': api_key_hash,  # SHA-256 hash of the API key for usage tracking
                'device_hash': device_hash,  # SHA-256 hash of the device (IP:user_id) for usage tracking
                'api_key_encrypted_name': api_key_record.get('encrypted_name'),  # Encrypted name (client decrypts)
                # Note: encrypted_name is not decrypted here (client decrypts it)
            }

            # Update last_used timestamp (async, don't wait)
            # This is fire-and-forget to avoid blocking the response
            try:
                last_used_at = datetime.now(timezone.utc).isoformat()
                updated = await self.directus_service.update_api_key_last_used(
                    api_key_hash, last_used_at=last_used_at
                )
                if updated:
                    # Refresh cached record so subsequent requests reflect the latest usage
                    api_key_record["last_used_at"] = last_used_at
                    await self.cache_service.set(cache_key, api_key_record, ttl=300)
                else:
                    logger.warning("API key last_used_at update returned False")
            except Exception as e:
                logger.warning(f"Failed to update API key last_used timestamp: {e}")

            return user_info

        except ApiKeyNotFoundError:
            raise
        except DeviceNotApprovedError:
            raise
        except Exception as e:
            logger.error(f"Error authenticating API key: {e}", exc_info=True)
            raise ApiKeyNotFoundError("Authentication failed")

    async def _check_and_register_device(
        self,
        api_key_id: str,
        user_id: str,
        request: Request
    ) -> str:
        """
        Check if the device is approved for this API key, and register it if it's new.
        BLOCKS API access if device is new or not approved.
        First request from new device is blocked until user approves in web UI.
        
        Args:
            api_key_id: The ID of the API key
            user_id: The user ID
            request: FastAPI request object for extracting IP address
            
        Returns:
            device_hash: SHA-256 hash of the device (IP:user_id) for usage tracking
            
        Raises:
            DeviceNotApprovedError: If the device is not approved (blocks API access)
        """
        try:
            # Extract client IP address
            client_ip = _extract_client_ip(
                request.headers,
                request.client.host if request.client else None
            )
            
            # Generate device hash: SHA256(IP_address:user_id)
            # This is the same format as documented in developer_settings.md
            device_hash_string = f"{client_ip}:{user_id}"
            device_hash = hashlib.sha256(device_hash_string.encode()).hexdigest()
            
            # Check cache first for device approval status
            device_approval_cache_key = f"api_key_device_approval:{api_key_id}:{device_hash}"
            cached_approval = await self.cache_service.get(device_approval_cache_key)
            
            if cached_approval is not None:
                # Found in cache - check approval status
                approved_at = cached_approval.get('approved_at')
                device_id = cached_approval.get('device_id')
                
                # approved_at is NULL/None means device is not approved
                if not approved_at:
                    logger.warning(f"API key access denied (cached): Device {device_hash[:8]}... not approved for API key {api_key_id}")
                    raise DeviceNotApprovedError(
                        f"Device not approved. Please confirm this device in Settings > Developers > Devices before using the API key."
                    )
                
                # Device is approved - update last access timestamp (async, don't wait)
                try:
                    await self.directus_service.update_api_key_device_last_access(
                        api_key_id=api_key_id,
                        device_hash=device_hash
                    )
                except Exception as e:
                    logger.warning(f"Failed to update device last_access timestamp: {e}")
                
                logger.debug(f"Device {device_hash[:8]}... approved (from cache) and access granted for API key {api_key_id}")
                return device_hash
            
            # Not in cache - check database
            device_record = await self.directus_service.get_api_key_device_by_hash(
                api_key_id=api_key_id,
                device_hash=device_hash
            )
            
            if device_record:
                # Device exists - cache the result and update last access
                device_id = device_record.get('id')
                approved_at = device_record.get('approved_at')
                
                # Cache device record for 5 minutes (for future lookups)
                await self.cache_service.set(
                    device_approval_cache_key,
                    {
                        'approved_at': approved_at,
                        'device_id': device_id
                    },
                    ttl=300
                )
                
                # Check if device is approved - BLOCK if not approved (approved_at is NULL/None)
                if not approved_at:
                    logger.warning(f"API key access denied: Device {device_hash[:8]}... not approved for API key {api_key_id}")
                    raise DeviceNotApprovedError(
                        f"Device not approved. Please confirm this device in Settings > Developers > Devices before using the API key."
                    )
                
                # Device is approved - update last access timestamp (async, don't wait)
                try:
                    await self.directus_service.update_api_key_device_last_access(
                        api_key_id=api_key_id,
                        device_hash=device_hash
                    )
                except Exception as e:
                    logger.warning(f"Failed to update device last_access timestamp: {e}")
                
                logger.debug(f"Device {device_hash[:8]}... approved and access granted for API key {api_key_id}")
                return device_hash
            else:
                # New device - create record (unapproved by default)
                logger.info(f"New device detected for API key {api_key_id}: {device_hash[:8]}...")
                success, device_record, message = await self.directus_service.create_api_key_device(
                    api_key_id=api_key_id,
                    user_id=user_id,
                    device_hash=device_hash,
                    client_ip=client_ip,
                    access_type="rest_api"
                )
                
                if success and device_record:
                    # Cache the new device record (unapproved by default - approved_at is NULL)
                    device_id = device_record.get('id')
                    await self.cache_service.set(
                        device_approval_cache_key,
                        {
                            'approved_at': None,  # NULL means not approved
                            'device_id': device_id
                        },
                        ttl=300
                    )
                    
                    logger.info(f"New device registered for API key {api_key_id}: {device_hash[:8]}... (blocked until approved)")
                    # TODO: Send notification to user about new device (via WebSocket or email)
                    # BLOCK API access until device is approved in web UI
                    raise DeviceNotApprovedError(
                        f"New device detected. Please confirm this device in Settings > Developers > Devices before using the API key."
                    )
                else:
                    logger.error(f"Failed to create device record: {message}")
                    # If device record creation fails, we still block access for security
                    raise DeviceNotApprovedError(
                        f"Device registration failed. Please try again or contact support."
                    )
        except DeviceNotApprovedError:
            # Re-raise device approval errors
            raise
        except Exception as e:
            # Log unexpected errors but still block access for security
            logger.error(f"Error checking/registering device: {e}", exc_info=True)
            raise DeviceNotApprovedError(
                f"Device verification failed. Please try again or contact support."
            )
                    
    # Note: _update_api_key_last_used is no longer needed here
    # The update is now handled by directus_service.update_api_key_last_used(key_hash)
    # which directly updates the api_keys collection


# Dependency functions
def get_api_key_auth_service(request: Request) -> ApiKeyAuthService:
    """Get API key authentication service from app state"""
    directus_service = request.app.state.directus_service
    cache_service = request.app.state.cache_service
    return ApiKeyAuthService(directus_service, cache_service)


async def verify_api_key(
    request: Request,
    api_key_auth_service: ApiKeyAuthService = Depends(get_api_key_auth_service)
) -> Dict[str, Any]:
    """
    FastAPI dependency to verify API key authentication.

    Returns user information if API key is valid.
    Raises HTTPException if API key is invalid or missing.
    """
    # Check Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header"
        )

    # Extract API key from Bearer token
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format. Use: Bearer <api_key>"
        )

    api_key = auth_header[7:]  # Remove "Bearer " prefix

    try:
        user_info = await api_key_auth_service.authenticate_api_key(api_key, request=request)
        return user_info
    except ApiKeyNotFoundError as e:
        logger.warning(f"API key authentication failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    except DeviceNotApprovedError as e:
        logger.warning(f"API key device not approved: {e}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )

# Security scheme for OpenAPI documentation
# This creates the security scheme that will appear in Swagger UI
# The scheme_name must match what we use in the OpenAPI schema
api_key_scheme = HTTPBearer(
    scheme_name="API Key",
    description="Enter your API key. API keys start with 'sk-api-'. Use format: Bearer sk-api-..."
)

async def get_api_key_from_security(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(api_key_scheme)
) -> Dict[str, Any]:
    """
    Get and verify API key from Security() credentials.
    This function uses Security() to enable Swagger UI authentication,
    while still using our custom verification logic.
    
    Args:
        request: FastAPI request object (injected automatically)
        credentials: HTTPBearer credentials from Security() (injected automatically)
        
    Returns:
        Dict containing user information if API key is valid
        
    Raises:
        HTTPException: If API key is invalid or missing
    """
    # Get the auth service from app state
    api_key_auth_service = get_api_key_auth_service(request)
    
    # Extract API key from Bearer token
    api_key = credentials.credentials
    
    try:
        user_info = await api_key_auth_service.authenticate_api_key(api_key, request=request)
        return user_info
    except ApiKeyNotFoundError as e:
        logger.warning(f"API key authentication failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    except DeviceNotApprovedError as e:
        logger.warning(f"API key device not approved: {e}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )

# Convenience dependency for use in routes
# Using Depends() with a function that has Security() as a parameter
# This ensures FastAPI adds the security requirement to the OpenAPI schema
ApiKeyAuth = Depends(get_api_key_from_security)