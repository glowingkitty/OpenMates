import hashlib
import logging
import httpx
import ipaddress # Added import
from typing import Dict, Any, Optional
from fastapi import Request
from functools import lru_cache

logger = logging.getLogger(__name__)

# IP-API configuration (free tier: up to 45 requests/minute)
IP_API_URL = "http://ip-api.com/json/"  # Using non-SSL endpoint for free tier

def get_device_fingerprint(request: Request) -> str:
    """
    Create a unique device fingerprint based on client IP and user agent
    Returns a SHA-256 hash of the combined string
    """
    # Get client IP - use X-Forwarded-For if behind proxy, otherwise use client host
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"
    
    # Get user agent string
    user_agent = request.headers.get("User-Agent", "unknown")
    
    # Combine data and hash
    fingerprint_data = f"{client_ip}:{user_agent}"
    hashed = hashlib.sha256(fingerprint_data.encode()).hexdigest()
    
    return hashed

def get_client_ip(request: Request) -> str:
    """Extract client IP address from request"""
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.client.host if request.client else "unknown"
    return client_ip

def is_private_ip(ip_address_str: str) -> bool:
    """Checks if an IP address string belongs to a private or loopback range."""
    if not ip_address_str or ip_address_str.lower() == "unknown":
        return False # Treat unknown as not private for safety
    try:
        ip = ipaddress.ip_address(ip_address_str)
        # is_private covers RFC1918. is_loopback covers 127.0.0.0/8 and ::1.
        return ip.is_private or ip.is_loopback
    except ValueError:
        logger.warning(f"Invalid IP address format for check: {ip_address_str}")
        return False # Treat invalid format as not private

@lru_cache(maxsize=1024)
def get_location_from_ip(ip_address: str) -> Dict[str, Any]:
    """
    Get location details (string, lat, lon) from IP address using ip-api.com.
    Returns a dictionary with 'location_string', 'latitude', 'longitude'.
    Uses caching to avoid unnecessary API calls.
    """
    default_result = {"location_string": "unknown", "latitude": None, "longitude": None}

    # --- Handle Special Cases ---
    # Handle unknown first
    if ip_address == "unknown":
         logger.debug("Unknown IP address provided, returning default unknown location.")
         return default_result

    # Check if the IP is private or loopback before external lookup
    if is_private_ip(ip_address):
        logger.debug(f"Private/Loopback IP detected: {ip_address}. Returning 'Local Network'.")
        return {"location_string": "Local Network", "latitude": 52.5200, "longitude": 13.4050} # Berlin coords as placeholder

    # --- Proceed with API Lookup for public IPs ---
    try:
        # Use synchronous request
        response = httpx.get(
            f"{IP_API_URL}/{ip_address}",
            params={"fields": "status,message,city,countryCode,lat,lon"}, # Added lat, lon
            timeout=5.0
        )

        if response.status_code == 200:
            data = response.json()

            # Check if the request was successful
            if data.get("status") == "success":
                city = data.get("city")
                country_code = data.get("countryCode")
                latitude = data.get("lat")
                longitude = data.get("lon")

                location_string = "unknown"
                if city:
                    location_string = f"{city}, {country_code}" if country_code else city
                elif country_code:
                    location_string = country_code # Fallback to country code if no city

                return {
                    "location_string": location_string,
                    "latitude": latitude,
                    "longitude": longitude
                }
            else:
                logger.warning(f"IP location lookup failed for {ip_address}: {data.get('message', 'Unknown error')}")

        else:
            logger.warning(f"Failed to get location for IP {ip_address}: Status {response.status_code}")

    except Exception as e:
        logger.error(f"Error looking up location for IP {ip_address}: {str(e)}")

    return default_result

def update_device_record(
    existing_devices: Optional[Dict[str, Any]], 
    fingerprint: str, 
    location: str
) -> Dict[str, Any]:
    """
    Update the devices dictionary with new device information
    Create the dictionary if it doesn't exist
    """
    import time
    current_time = int(time.time())
    
    # Initialize empty dict if None
    devices = existing_devices or {}
    
    if fingerprint in devices:
        # Update existing device record
        devices[fingerprint]["recent"] = current_time
    else:
        # Create new device record
        devices[fingerprint] = {
            "loc": location,
            "first": current_time,
            "recent": current_time
        }
    
    return devices
