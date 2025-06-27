# backend/core/api/app/utils/device_fingerprint.py
import hashlib
import json
import logging
import httpx
import ipaddress
from typing import Dict, Any, Optional, Mapping, Tuple, List
from fastapi import Request
from functools import lru_cache
import time
import secrets # Not used anymore, but keeping for now if other parts of the codebase use it

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# --- Configuration ---
IP_API_URL = "http://ip-api.com/json/"

# --- Internal Helper Functions ---

def _is_valid_ip_format(ip: str) -> bool:
    """Check if the IP string is a valid format and not a template placeholder"""
    if not ip or '{' in ip or '}' in ip:
        return False
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False

def _extract_client_ip(headers: Mapping[str, str], client_host: Optional[str]) -> str:
    """Internal helper to extract client IP from headers and host."""
    ip_candidates = [
        headers.get("x-real-ip", ""),
        headers.get("x-forwarded-for", "").split(",")[0].strip(),
    ]

    for ip in ip_candidates:
        if ip and _is_valid_ip_format(ip):
            return ip

    if client_host and _is_valid_ip_format(client_host):
        return client_host

    logger.warning(f"Could not determine a valid client IP. Headers: {headers}, Host: {client_host}")
    return "unknown"

def is_private_ip(ip_address_str: str) -> bool:
    """Checks if an IP address string belongs to a private or loopback range."""
    if not ip_address_str or ip_address_str.lower() == "unknown" or not _is_valid_ip_format(ip_address_str):
        return False
    try:
        ip = ipaddress.ip_address(ip_address_str)
        return ip.is_private or ip.is_loopback
    except ValueError:
        return False

@lru_cache(maxsize=1024)
def get_geo_data_from_ip(ip_address: str) -> Dict[str, Any]:
    """
    Get geolocation data from IP address using ip-api.com.
    Uses caching.
    """
    default_result = {"country_code": None, "region": None, "city": None, "latitude": None, "longitude": None}

    if ip_address == "unknown" or is_private_ip(ip_address):
        return {"country_code": "Local", "region": "Local", "city": "Local Network", "latitude": None, "longitude": None}

    try:
        response = httpx.get(
            f"{IP_API_URL}/{ip_address}",
            params={"fields": "status,message,countryCode,regionName,city,lat,lon"},
            timeout=5.0
        )
        response.raise_for_status()
        data = response.json()

        if data.get("status") == "success":
            return {
                "country_code": data.get("countryCode"),
                "region": data.get("regionName"),
                "city": data.get("city"),
                "latitude": data.get("lat"),
                "longitude": data.get("lon")
            }
        else:
            logger.warning(f"IP location lookup failed for {ip_address}: {data.get('message', 'Unknown error')}")

    except httpx.RequestError as e:
         logger.error(f"HTTP request error looking up location for IP {ip_address}: {e}")
    except Exception as e:
        logger.error(f"Error looking up location for IP {ip_address}: {str(e)}", exc_info=True)

    return default_result

def parse_user_agent(user_agent: str) -> Tuple[str, str, str, str, str]:
    """
    Extract browser, version, OS, OS version and device type from User-Agent
    using the 'user-agents' library.
    """
    try:
        from user_agents import parse
        ua = parse(user_agent)

        browser_name = ua.browser.family if ua.browser else "Unknown"
        browser_version = ua.browser.version_string if ua.browser else "Unknown"
        os_name = ua.os.family if ua.os else "Unknown"
        os_version = ua.os.version_string if ua.os else "Unknown"

        if ua.is_mobile:
            device_type = "mobile"
        elif ua.is_tablet:
            device_type = "tablet"
        elif ua.is_pc:
            device_type = "desktop"
        elif ua.is_bot:
            device_type = "bot"
        else:
            device_type = "unknown"

        return browser_name, browser_version, os_name, os_version, device_type

    except ImportError:
        logger.error("The 'user-agents' library is not installed. Please install it: pip install user-agents")
        browser_name, browser_version, os_name, os_version, device_type = "Unknown", "Unknown", "Unknown", "Unknown", "desktop"
        ua_lower = user_agent.lower()
        if "mobile" in ua_lower or "iphone" in ua_lower or "android" in ua_lower: device_type = "mobile"
        elif "tablet" in ua_lower or "ipad" in ua_lower: device_type = "tablet"
        if "firefox" in ua_lower: browser_name = "Firefox"
        elif "chrome" in ua_lower: browser_name = "Chrome"
        elif "safari" in ua_lower: browser_name = "Safari"
        if "windows" in ua_lower: os_name = "Windows"
        elif "mac os" in ua_lower: os_name = "MacOS"
        elif "linux" in ua_lower: os_name = "Linux"
        elif "android" in ua_lower: os_name = "Android"
        elif "iphone" in ua_lower or "ipad" in ua_lower: os_name = "iOS"
        return browser_name, browser_version, os_name, os_version, device_type
    except Exception as e:
        logger.error(f"Error parsing user agent '{user_agent}': {e}", exc_info=True)
        return "Unknown", "Unknown", "Unknown", "Unknown", "unknown"

# --- Core Fingerprint Generation ---

def generate_device_fingerprint_hash(
    request: Request,
    user_id: str
) -> Tuple[str, str, str, Optional[str], Optional[str], Optional[float], Optional[float]]:
    """
    Generate a simplified device fingerprint hash based on OS and Country Code,
    and return detailed geolocation data.
    Returns the hash, OS name, country code, city, region, latitude, and longitude.
    """
    client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
    user_agent = request.headers.get("User-Agent", "unknown")

    # Extract OS name
    _, _, os_name, _, _ = parse_user_agent(user_agent)
    
    # Get country code and detailed geo data from IP
    geo_data = get_geo_data_from_ip(client_ip)
    country_code = geo_data.get("country_code", "Unknown")
    city = geo_data.get("city")
    region = geo_data.get("region")
    latitude = geo_data.get("latitude")
    longitude = geo_data.get("longitude")

    # Create the combined string for hashing
    # Use a consistent format and include user_id as salt for privacy and uniqueness per user
    fingerprint_string = f"{os_name}:{country_code}:{user_id}"
    device_hash = hashlib.sha256(fingerprint_string.encode()).hexdigest()

    logger.debug(f"Generated device hash: {device_hash[:8]}... (OS: {os_name}, Country: {country_code}) for user {user_id[:6]}...")
    return device_hash, os_name, country_code, city, region, latitude, longitude

# Removed: DeviceFingerprint Pydantic model
# Removed: calculate_risk_level function
# Removed: should_require_2fa function
# Removed: STORED_FINGERPRINT_FIELDS constant
# Removed: RISK_THRESHOLD_2FA constant
