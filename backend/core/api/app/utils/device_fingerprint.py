import hashlib
import logging
import httpx
import ipaddress
from typing import Dict, Any, Optional, Mapping # Added Mapping
from fastapi import Request # Keep for original functions
from functools import lru_cache

logger = logging.getLogger(__name__)

# IP-API configuration
IP_API_URL = "http://ip-api.com/json/"

# --- Internal Helper Functions ---

def _extract_client_ip(headers: Mapping[str, str], client_host: Optional[str]) -> str:
    """Internal helper to extract client IP from headers and host."""
    # Headers accessed via Mapping should be lower-case
    logger.debug(f"_extract_client_ip: Headers: {headers}")
    logger.debug(f"_extract_client_ip: Client host: {client_host}")

    # Try X-Real-IP first
    client_ip = headers.get("x-real-ip", "")
    if client_ip and _is_valid_ip_format(client_ip):
        logger.debug(f"_extract_client_ip: Using X-Real-IP: {client_ip}")
        return client_ip

    # Try X-Forwarded-For next
    x_forwarded_for = headers.get("x-forwarded-for", "")
    client_ip = x_forwarded_for.split(",")[0].strip()

    if client_ip and _is_valid_ip_format(client_ip):
        logger.debug(f"_extract_client_ip: Using X-Forwarded-For: {client_ip}")
        return client_ip

    # Fall back to client.host as last resort
    client_ip = client_host if client_host else "unknown"
    logger.debug(f"_extract_client_ip: Using client.host fallback: {client_ip}")
    return client_ip

def _calculate_fingerprint(client_ip: str, user_agent: str) -> str:
    """Internal helper to calculate the SHA-256 fingerprint."""
    fingerprint_data = f"{client_ip}:{user_agent}"
    hashed = hashlib.sha256(fingerprint_data.encode()).hexdigest()
    return hashed

# --- Original Functions (using helpers) ---

def get_device_fingerprint(request: Request) -> str:
    """
    Create a unique device fingerprint based on client IP and user agent (using Request object).
    Returns a SHA-256 hash of the combined string.
    """
    client_ip = get_client_ip(request)
    # Request.headers allows original case access
    user_agent = request.headers.get("User-Agent", "unknown")
    return _calculate_fingerprint(client_ip, user_agent)

def get_client_ip(request: Request) -> str:
    """Extract client IP address from Request object using the internal helper."""
    # FastAPI Request headers are case-insensitive Mapping
    # Pass None for client_host if request.client is None
    return _extract_client_ip(request.headers, request.client.host if request.client else None)

# --- WebSocket Specific Functions (using helpers) ---

def get_websocket_client_ip(websocket) -> str: # Use 'Any' or specific WebSocket type if available
    """Extract client IP address from WebSocket scope using the internal helper."""
    # WebSocket headers might be case-sensitive depending on the library, convert to lower for safety
    # websocket.headers is likely a Headers object, similar to Request
    headers_lower = {k.lower(): v for k, v in websocket.headers.items()}
    return _extract_client_ip(headers_lower, websocket.client.host if websocket.client else None)

def get_websocket_device_fingerprint(websocket) -> str:
    """Create a device fingerprint for a WebSocket connection."""
    client_ip = get_websocket_client_ip(websocket)
    # Get User-Agent, prefer original case if possible from websocket.headers
    user_agent = websocket.headers.get("User-Agent", "unknown")
    return _calculate_fingerprint(client_ip, user_agent)


# --- Utility Functions ---

def _is_valid_ip_format(ip: str) -> bool:
    """Check if the IP string is a valid format and not a template placeholder"""
    # Check for template placeholders like {http.request.remote.ip}
    if '{' in ip or '}' in ip:
        logger.debug(f"Rejected template placeholder in IP: {ip}")
        return False

    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        # Log as warning, not error, as it might be expected sometimes
        logger.warning(f"Invalid IP format encountered: {ip}")
        return False

def is_private_ip(ip_address_str: str) -> bool:
    """Checks if an IP address string belongs to a private or loopback range."""
    # Log only first few chars as requested
    logger.info(f"Checking if IP is private: {ip_address_str[:3]}...")
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
    logger.info(f"Fetching location for IP: {ip_address[:3]}...") # Log only first 3 chars
    default_result = {"location_string": "unknown", "latitude": None, "longitude": None, "country_code": None}

    # --- Handle Special Cases ---
    # Handle unknown first
    if ip_address == "unknown":
         logger.info("Unknown IP address provided, returning default unknown location.")
         return default_result

    # Check if the IP is private or loopback before external lookup
    if is_private_ip(ip_address):
        logger.info(f"Private/Loopback IP detected: {ip_address[:3]}.... Returning 'Local Network' with Berlin coordinates.")
        # Return Berlin coordinates as requested
        return {"location_string": "Local Network", "latitude": 52.5200, "longitude": 13.4050, "country_code": "DE"} # Added DE country code

    # --- Proceed with API Lookup for public IPs ---
    try:
        # Use synchronous request
        response = httpx.get(
            f"{IP_API_URL}/{ip_address}",
            params={"fields": "status,message,city,countryCode,lat,lon"}, # Added lat, lon
            timeout=5.0
        )
        response.raise_for_status() # Raise exception for bad status codes

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
                "country_code": country_code,
                "location_string": location_string,
                "latitude": latitude,
                "longitude": longitude
            }
        else:
            logger.warning(f"IP location lookup failed for {ip_address}: {data.get('message', 'Unknown error')}")

    except httpx.RequestError as e:
         logger.error(f"HTTP request error looking up location for IP {ip_address}: {e}")
    except Exception as e:
        logger.error(f"Error looking up location for IP {ip_address}: {str(e)}", exc_info=True)

    return default_result

def update_device_record(
    existing_devices: Optional[Dict[str, Any]],
    fingerprint: str,
    location_info: Dict[str, Any] # Expect the dict from get_location_from_ip
) -> Dict[str, Any]:
    """
    Update the devices dictionary with new device information.
    Create the dictionary if it doesn't exist.
    """
    import time
    current_time = int(time.time())

    # Initialize empty dict if None
    devices = existing_devices or {}

    # Extract location string, default to unknown
    location_str = location_info.get("location_string", "unknown")

    if fingerprint in devices:
        # Update existing device record
        devices[fingerprint]["recent"] = current_time
        # Optionally update location if it was previously unknown? Or keep first known?
        # For now, just update 'recent'
    else:
        # Create new device record
        devices[fingerprint] = {
            "loc": location_str,
            "first": current_time,
            "recent": current_time,
            # Store country code and coords if available?
            "country": location_info.get("country_code"),
            "lat": location_info.get("latitude"),
            "lon": location_info.get("longitude")
        }

    return devices

# --- Deprecated / Original IP extraction logic (kept for reference if needed) ---
# def get_client_ip_original(request: Request) -> str:
#     """Extract client IP address from request"""
#     # Log headers for debug but at DEBUG level to avoid cluttering
#     logger.debug(f"get_client_ip: Headers: {dict(request.headers)}")
#     logger.debug(f"get_client_ip: Client host: {request.client.host if request.client else 'No client object'}")
#
#     # Try X-Real-IP first (often more reliable)
#     client_ip = request.headers.get("X-Real-IP", "")
#     if client_ip and _is_valid_ip_format(client_ip):
#         logger.debug(f"get_client_ip: Using X-Real-IP: {client_ip}")
#         return client_ip
#
#     # Try X-Forwarded-For next
#     x_forwarded_for = request.headers.get("X-Forwarded-For", "")
#     client_ip = x_forwarded_for.split(",")[0].strip()
#
#     # Validate the IP format to prevent template placeholders
#     if client_ip and _is_valid_ip_format(client_ip):
#         logger.debug(f"get_client_ip: Using X-Forwarded-For: {client_ip}")
#         return client_ip
#
#     # Fall back to client.host as last resort
#     client_ip = request.client.host if request.client else "unknown"
#     logger.debug(f"get_client_ip: Using client.host fallback: {client_ip}")
#     return client_ip
