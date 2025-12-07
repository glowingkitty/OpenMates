# backend/core/api/app/services/directus/api_key_device_methods.py
#
# Device management methods for API key access
# Handles device tracking and approval for API key authentication
#
# Note: These methods are bound to DirectusService and can access self.cache
# for cache invalidation when devices are approved/revoked

import logging
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger(__name__)


async def get_api_key_device_by_hash(
    self,
    api_key_id: str,
    device_hash: str
) -> Optional[Dict[str, Any]]:
    """
    Get an API key device record by API key ID and device hash.
    
    Args:
        self: The DirectusService instance
        api_key_id: The ID of the API key
        device_hash: The device hash to look up
        
    Returns:
        Device record if found, None otherwise
    """
    try:
        url = f"{self.base_url}/items/api_key_devices"
        params = {
            "filter[api_key_id][_eq]": api_key_id,
            "filter[device_hash][_eq]": device_hash,
            "limit": 1
        }
        
        response = await self._make_api_request("GET", url, params=params)
        
        if response.status_code == 200:
            data = response.json().get("data", [])
            if data and len(data) > 0:
                return data[0]
        return None
        
    except Exception as e:
        logger.error(f"Error getting API key device by hash: {e}", exc_info=True)
        return None


async def create_api_key_device(
    self,
    api_key_id: str,
    user_id: str,
    device_hash: str,
    client_ip: str,
    access_type: str = "rest_api",
    machine_identifier: Optional[str] = None
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Create a new API key device record.
    New devices start with approved_at=NULL and require user approval.
    
    Args:
        self: The DirectusService instance
        api_key_id: The ID of the API key
        user_id: The user ID
        device_hash: The device hash (SHA256 of IP:user_id or machine_id:user_id)
        client_ip: The client IP address (for anonymization and geo lookup)
        access_type: Type of access ('rest_api', 'cli', 'pip', 'npm')
        machine_identifier: Optional machine identifier for CLI/pip/npm access
        
    Returns:
        Tuple of (success, device_record, message)
    """
    try:
        from backend.core.api.app.utils.device_fingerprint import get_geo_data_from_ip, _extract_client_ip
        
        # Get user's vault_key_id for encryption
        user_data = await self.get_user_fields_direct(user_id, ['vault_key_id'])
        if not user_data or not user_data.get('vault_key_id'):
            error_msg = "User vault_key_id not found - cannot encrypt device data"
            logger.error(error_msg)
            return False, None, error_msg
        
        vault_key_id = user_data.get('vault_key_id')
        
        # Get geo data from IP
        geo_data = get_geo_data_from_ip(client_ip)
        country_code = geo_data.get("country_code", "Unknown")
        region = geo_data.get("region")
        city = geo_data.get("city")
        
        # Anonymize IP address (first two octets only)
        # Example: 184.149.123.45 -> 184.149.xxx
        ip_parts = client_ip.split(".")
        if len(ip_parts) >= 2:
            anonymized_ip = f"{ip_parts[0]}.{ip_parts[1]}.xxx"
        else:
            anonymized_ip = "unknown.xxx"
        
        # Encrypt sensitive fields with user's vault key
        encrypted_anonymized_ip, _ = await self.encryption_service.encrypt_with_user_key(anonymized_ip, vault_key_id)
        encrypted_country_code, _ = await self.encryption_service.encrypt_with_user_key(country_code, vault_key_id)
        encrypted_region, _ = await self.encryption_service.encrypt_with_user_key(region or "", vault_key_id) if region else (None, None)
        encrypted_city, _ = await self.encryption_service.encrypt_with_user_key(city or "", vault_key_id) if city else (None, None)
        encrypted_access_type, _ = await self.encryption_service.encrypt_with_user_key(access_type, vault_key_id)
        encrypted_machine_identifier, _ = await self.encryption_service.encrypt_with_user_key(machine_identifier or "", vault_key_id) if machine_identifier else (None, None)
        
        # Create user_id hash for privacy
        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
        
        # Create device record with encrypted fields and timestamps
        now = datetime.now(timezone.utc).isoformat()
        device_data = {
            "api_key_id": api_key_id,
            "hashed_user_id": user_id_hash,
            "device_hash": device_hash,
            "encrypted_anonymized_ip": encrypted_anonymized_ip,
            "encrypted_country_code": encrypted_country_code,
            "encrypted_region": encrypted_region,
            "encrypted_city": encrypted_city,
            "encrypted_access_type": encrypted_access_type,
            "encrypted_machine_identifier": encrypted_machine_identifier,
            "approved_at": None,  # NULL means device is pending approval
            "first_access_at": now,
            "last_access_at": now,
            "created_at": now,
            "updated_at": now
        }
        
        url = f"{self.base_url}/items/api_key_devices"
        response = await self._make_api_request("POST", url, json=device_data)
        
        if response.status_code == 200:
            device_record = response.json().get("data")
            logger.info(f"Created new API key device record for api_key_id={api_key_id}, device_hash={device_hash[:8]}...")
            return True, device_record, "Device record created"
        else:
            error_msg = f"Failed to create API key device record: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return False, None, error_msg
            
    except Exception as e:
        error_msg = f"Error creating API key device record: {e}"
        logger.error(error_msg, exc_info=True)
        return False, None, error_msg


async def update_api_key_device_last_access(
    self,
    api_key_id: str,
    device_hash: str
) -> bool:
    """
    Update the last_access_at timestamp for an API key device.
    
    Args:
        self: The DirectusService instance
        api_key_id: The ID of the API key
        device_hash: The device hash
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # First, get the device record to get its ID
        device_record = await get_api_key_device_by_hash(self, api_key_id, device_hash)
        if not device_record:
            logger.warning(f"Device record not found for api_key_id={api_key_id}, device_hash={device_hash[:8]}...")
            return False
        
        device_id = device_record.get("id")
        now = datetime.now(timezone.utc).isoformat()
        
        url = f"{self.base_url}/items/api_key_devices/{device_id}"
        update_data = {"last_access_at": now}
        
        response = await self._make_api_request("PATCH", url, json=update_data)
        
        if response.status_code == 200:
            logger.debug(f"Updated last_access_at for API key device {device_id}")
            return True
        else:
            logger.error(f"Failed to update API key device last_access_at: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error updating API key device last_access_at: {e}", exc_info=True)
        return False


async def get_api_key_devices(
    self,
    api_key_id: str,
    user_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get all device records for an API key.
    Decrypts encrypted fields if user_id is provided.
    
    Args:
        self: The DirectusService instance
        api_key_id: The ID of the API key
        user_id: Optional user ID for decryption (if None, returns encrypted fields)
        
    Returns:
        List of device records with decrypted fields if user_id provided
    """
    try:
        url = f"{self.base_url}/items/api_key_devices"
        params = {
            "filter[api_key_id][_eq]": api_key_id,
            "sort": "-last_access_at"  # Most recent first
        }
        
        response = await self._make_api_request("GET", url, params=params)
        
        if response.status_code == 200:
            data = response.json().get("data", [])
            
            # Decrypt fields if user_id is provided
            if user_id and data:
                # Get user's vault_key_id for decryption
                user_data = await self.get_user_fields_direct(user_id, ['vault_key_id'])
                vault_key_id = user_data.get('vault_key_id') if user_data else None
                
                if vault_key_id:
                    decrypted_devices = []
                    for device in data:
                        decrypted_device = device.copy()
                        
                        # Decrypt encrypted fields
                        try:
                            if device.get('encrypted_anonymized_ip'):
                                decrypted_device['anonymized_ip'] = await self.encryption_service.decrypt_with_user_key(
                                    device['encrypted_anonymized_ip'], vault_key_id
                                )
                            if device.get('encrypted_country_code'):
                                decrypted_device['country_code'] = await self.encryption_service.decrypt_with_user_key(
                                    device['encrypted_country_code'], vault_key_id
                                )
                            if device.get('encrypted_region'):
                                decrypted_device['region'] = await self.encryption_service.decrypt_with_user_key(
                                    device['encrypted_region'], vault_key_id
                                )
                            if device.get('encrypted_city'):
                                decrypted_device['city'] = await self.encryption_service.decrypt_with_user_key(
                                    device['encrypted_city'], vault_key_id
                                )
                            if device.get('encrypted_access_type'):
                                decrypted_device['access_type'] = await self.encryption_service.decrypt_with_user_key(
                                    device['encrypted_access_type'], vault_key_id
                                )
                            if device.get('encrypted_machine_identifier'):
                                decrypted_device['machine_identifier'] = await self.encryption_service.decrypt_with_user_key(
                                    device['encrypted_machine_identifier'], vault_key_id
                                )
                        except Exception as decrypt_error:
                            logger.warning(f"Error decrypting device fields: {decrypt_error}")
                            # Continue with encrypted fields if decryption fails
                        
                        decrypted_devices.append(decrypted_device)
                    
                    return decrypted_devices
            
            return data
        return []
        
    except Exception as e:
        logger.error(f"Error getting API key devices: {e}", exc_info=True)
        return []


async def approve_api_key_device(
    self,
    device_id: str
) -> Tuple[bool, str]:
    """
    Approve an API key device, allowing it to use the API key.
    Also invalidates the device approval cache to ensure immediate effect.
    
    Args:
        self: The DirectusService instance
        device_id: The ID of the device record to approve
        
    Returns:
        Tuple of (success, message)
    """
    try:
        # First, get the device record to get api_key_id and device_hash for cache invalidation
        url_get = f"{self.base_url}/items/api_key_devices/{device_id}"
        get_response = await self._make_api_request("GET", url_get, params={"fields": "api_key_id,device_hash"})
        
        api_key_id = None
        device_hash = None
        if get_response.status_code == 200:
            device_data = get_response.json().get("data", {})
            api_key_id = device_data.get("api_key_id")
            device_hash = device_data.get("device_hash")
        
        # Update device to approved (set approved_at timestamp)
        url = f"{self.base_url}/items/api_key_devices/{device_id}"
        now = datetime.now(timezone.utc).isoformat()
        update_data = {
            "approved_at": now,
            "updated_at": now
        }
        
        response = await self._make_api_request("PATCH", url, json=update_data)
        
        if response.status_code == 200:
            logger.info(f"Approved API key device {device_id}")
            
            # Invalidate device approval cache if we have the keys
            # Note: DirectusService has self.cache attribute (CacheService instance)
            if api_key_id and device_hash and hasattr(self, 'cache') and self.cache:
                device_approval_cache_key = f"api_key_device_approval:{api_key_id}:{device_hash}"
                try:
                    await self.cache.delete(device_approval_cache_key)
                    logger.debug(f"Invalidated device approval cache for {device_id}")
                except Exception as cache_error:
                    logger.warning(f"Failed to invalidate device approval cache: {cache_error}")
            
            return True, "Device approved successfully"
        else:
            error_msg = f"Failed to approve API key device: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return False, error_msg
            
    except Exception as e:
        error_msg = f"Error approving API key device: {e}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg


async def revoke_api_key_device(
    self,
    device_id: str
) -> Tuple[bool, str]:
    """
    Revoke access for an API key device by deleting the device record.
    Also invalidates the device approval cache to ensure immediate effect.
    
    Args:
        self: The DirectusService instance
        device_id: The ID of the device record to revoke
        
    Returns:
        Tuple of (success, message)
    """
    try:
        # First, get the device record to get api_key_id and device_hash for cache invalidation
        url_get = f"{self.base_url}/items/api_key_devices/{device_id}"
        get_response = await self._make_api_request("GET", url_get, params={"fields": "api_key_id,device_hash"})
        
        api_key_id = None
        device_hash = None
        if get_response.status_code == 200:
            device_data = get_response.json().get("data", {})
            api_key_id = device_data.get("api_key_id")
            device_hash = device_data.get("device_hash")
        
        # Delete device record
        url = f"{self.base_url}/items/api_key_devices/{device_id}"
        response = await self._make_api_request("DELETE", url)
        
        if response.status_code == 200 or response.status_code == 204:
            logger.info(f"Revoked API key device {device_id}")
            
            # Invalidate device approval cache if we have the keys
            # Note: DirectusService has self.cache attribute (CacheService instance)
            if api_key_id and device_hash and hasattr(self, 'cache') and self.cache:
                device_approval_cache_key = f"api_key_device_approval:{api_key_id}:{device_hash}"
                try:
                    await self.cache.delete(device_approval_cache_key)
                    logger.debug(f"Invalidated device approval cache for {device_id}")
                except Exception as cache_error:
                    logger.warning(f"Failed to invalidate device approval cache: {cache_error}")
            
            return True, "Device revoked successfully"
        else:
            error_msg = f"Failed to revoke API key device: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return False, error_msg
            
    except Exception as e:
        error_msg = f"Error revoking API key device: {e}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg


async def get_pending_api_key_devices(
    self,
    user_id: str
) -> List[Dict[str, Any]]:
    """
    Get all pending (unapproved) device records for a user's API keys.
    
    Args:
        self: The DirectusService instance
        user_id: The user ID
        
    Returns:
        List of pending device records
    """
    try:
        # Create user_id hash for privacy-preserving lookup
        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
        
        url = f"{self.base_url}/items/api_key_devices"
        params = {
            "filter[hashed_user_id][_eq]": user_id_hash,
            "filter[approved_at][_null]": True,  # NULL means pending approval
            "sort": "-first_access_at"  # Most recent first
        }
        
        response = await self._make_api_request("GET", url, params=params)
        
        if response.status_code == 200:
            data = response.json().get("data", [])
            return data
        return []
        
    except Exception as e:
        logger.error(f"Error getting pending API key devices: {e}", exc_info=True)
        return []
