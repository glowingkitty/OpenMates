# backend/core/api/app/utils/device_fingerprint.py
import hashlib
import json
import logging
import httpx
import ipaddress
from typing import Dict, Any, Optional, Mapping, Tuple, List # Added Tuple, List
from fastapi import Request
from functools import lru_cache
from pydantic import BaseModel, Field # Added BaseModel, Field
import time # Added time
import secrets # Added secrets for JTI later if needed

logger = logging.getLogger(__name__)

# --- Configuration ---
IP_API_URL = "http://ip-api.com/json/"
RISK_THRESHOLD_2FA = 70  # Scale 0-100. Adjust as needed.

# --- Pydantic Model for Fingerprint ---

class DeviceFingerprint(BaseModel):
    # Core identifiers (mostly server-side)
    # ip_address: str # Removed - only needed temporarily for geo lookup
    user_agent: str
    accept_language: Optional[str] = None

    # Derived properties (server-side)
    browser_name: str = "Unknown"
    browser_version: str = "Unknown"
    os_name: str = "Unknown"
    os_version: str = "Unknown"
    device_type: str = "desktop" # mobile, desktop, tablet

    # Geolocation data (server-side)
    country_code: Optional[str] = None # Changed from country
    region: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None # Added
    longitude: Optional[float] = None # Added

    # Hashed client-side signals (optional, from request body)
    screen_hash: Optional[str] = None
    time_zone_hash: Optional[str] = None
    language_hash: Optional[str] = None # Client language hash
    canvas_hash: Optional[str] = None
    webgl_hash: Optional[str] = None
    # installed_fonts_hash: Optional[str] = None # Example from discussion

    # Timestamp of generation
    generated_at: float = Field(default_factory=time.time)

    def to_dict(self, exclude_unset=True, exclude_none=True) -> Dict:
        """Convert model to dictionary, excluding unset/none values by default."""
        return self.dict(exclude_unset=exclude_unset, exclude_none=exclude_none)

    def calculate_stable_hash(self) -> str:
        """
        Generate a stable hash of the fingerprint components relevant for storage
        and comparison, excluding volatile fields like generated_at.
        """
        # Select fields that define the device/environment more stably
        stable_components = {
            "user_agent": self.user_agent,
            "accept_language": self.accept_language,
            "browser_name": self.browser_name,
            "browser_version": self.browser_version,
            "os_name": self.os_name,
            "os_version": self.os_version,
            "device_type": self.device_type,
            "country_code": self.country_code, # Country is relatively stable
            # Client-side hashes are stable by definition
            "screen_hash": self.screen_hash,
            "time_zone_hash": self.time_zone_hash,
            "language_hash": self.language_hash,
            "canvas_hash": self.canvas_hash,
            "webgl_hash": self.webgl_hash,
        }
        # Filter out None values before hashing
        filtered_components = {k: v for k, v in stable_components.items() if v is not None}
        fingerprint_json = json.dumps(filtered_components, sort_keys=True)
        return hashlib.sha256(fingerprint_json.encode()).hexdigest()

# --- Internal Helper Functions (Existing and New) ---

def _is_valid_ip_format(ip: str) -> bool:
    """Check if the IP string is a valid format and not a template placeholder"""
    if not ip or '{' in ip or '}' in ip:
        # logger.debug(f"Rejected invalid or template placeholder IP: {ip}")
        return False
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        # logger.warning(f"Invalid IP format encountered: {ip}")
        return False

def _extract_client_ip(headers: Mapping[str, str], client_host: Optional[str]) -> str:
    """Internal helper to extract client IP from headers and host."""
    # Headers accessed via Mapping should be lower-case
    # logger.debug(f"_extract_client_ip: Headers: {headers}")
    # logger.debug(f"_extract_client_ip: Client host: {client_host}")

    # Try common headers in order of preference
    ip_candidates = [
        headers.get("x-real-ip", ""),
        headers.get("x-forwarded-for", "").split(",")[0].strip(),
        # Add other potential headers if needed (e.g., CF-Connecting-IP)
    ]

    for ip in ip_candidates:
        if ip and _is_valid_ip_format(ip):
            # logger.debug(f"_extract_client_ip: Using header IP: {ip}")
            return ip

    # Fall back to client.host if valid
    if client_host and _is_valid_ip_format(client_host):
        # logger.debug(f"_extract_client_ip: Using client.host fallback: {client_host}")
        return client_host

    logger.warning(f"Could not determine a valid client IP. Headers: {headers}, Host: {client_host}")
    return "unknown"

def is_private_ip(ip_address_str: str) -> bool:
    """Checks if an IP address string belongs to a private or loopback range."""
    # logger.info(f"Checking if IP is private: {ip_address_str[:3]}...")
    if not ip_address_str or ip_address_str.lower() == "unknown" or not _is_valid_ip_format(ip_address_str):
        return False # Treat unknown/invalid as not private
    try:
        ip = ipaddress.ip_address(ip_address_str)
        return ip.is_private or ip.is_loopback
    except ValueError: # Should be caught by _is_valid_ip_format, but belt-and-suspenders
        # logger.warning(f"Invalid IP address format for check: {ip_address_str}")
        return False

@lru_cache(maxsize=1024)
def get_geo_data_from_ip(ip_address: str) -> Dict[str, Any]:
    """
    Get geolocation data from IP address using ip-api.com.
    Adapted to return structure similar to discussion's get_geo_data.
    Uses caching.
    """
    # logger.info(f"Fetching location for IP: {ip_address[:3]}...") # Log only first 3 chars
    default_result = {"country_code": None, "region": None, "city": None, "latitude": None, "longitude": None}

    if ip_address == "unknown" or is_private_ip(ip_address):
        # logger.info(f"Private/Loopback/Unknown IP detected: {ip_address[:3]}.... Returning local/unknown.")
        # Return local network indication, maybe default coords if needed elsewhere
        return {"country_code": "Local", "region": "Local", "city": "Local Network", "latitude": None, "longitude": None}

    try:
        response = httpx.get(
            f"{IP_API_URL}/{ip_address}",
            # Request more fields: regionName
            params={"fields": "status,message,countryCode,regionName,city,lat,lon"},
            timeout=5.0
        )
        response.raise_for_status()
        data = response.json()

        if data.get("status") == "success":
            return {
                "country_code": data.get("countryCode"),
                "region": data.get("regionName"), # Use regionName
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
        # Fallback to basic parsing if library is missing
        browser_name = "Unknown"
        browser_version = "Unknown"
        os_name = "Unknown"
        os_version = "Unknown"
        device_type = "desktop"
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

def generate_device_fingerprint(
    request: Request,
    client_signals: Optional[Dict[str, Any]] = None
) -> DeviceFingerprint:
    """
    Generate a comprehensive device fingerprint from request headers and
    optional client-side signals.
    """
    client_ip = _extract_client_ip(request.headers, request.client.host if request.client else None)
    user_agent = request.headers.get("User-Agent", "unknown")
    accept_language = request.headers.get("Accept-Language")

    # Parse user agent
    browser_name, browser_version, os_name, os_version, device_type = parse_user_agent(user_agent)

    # Get geolocation data
    geo_data = get_geo_data_from_ip(client_ip)

    # Use client signals if provided
    signals = client_signals or {}

    # Create fingerprint object (without ip_address)
    fingerprint = DeviceFingerprint(
        # ip_address=client_ip, # Not stored in the object
        user_agent=user_agent,
        accept_language=accept_language,
        browser_name=browser_name,
        browser_version=browser_version,
        os_name=os_name,
        os_version=os_version,
        device_type=device_type,
        country_code=geo_data.get("country_code"),
        region=geo_data.get("region"),
        city=geo_data.get("city"),
        latitude=geo_data.get("latitude"),
        longitude=geo_data.get("longitude"),
        # Add hashed client signals
        screen_hash=signals.get("screenHash"),
        time_zone_hash=signals.get("timeZoneHash"),
        language_hash=signals.get("languageHash"),
        canvas_hash=signals.get("canvasHash"),
        webgl_hash=signals.get("webGLHash"),
        # installed_fonts_hash=signals.get("fontsHash") # Example
    )

    return fingerprint

# --- Risk Assessment ---

def calculate_risk_level(
    stored_fingerprint_data: Dict[str, Any], # Data stored with refresh token
    current_fingerprint: DeviceFingerprint
) -> int:
    """
    Calculate risk level based on comparing stored fingerprint data
    with the current fingerprint object. Higher score = higher risk.
    """
    risk_score = 0
    current_dict = current_fingerprint.to_dict() # Use current FP object

    # --- Compare key fields ---
    # Compare fields that should be present in stored_fingerprint_data
    # These fields should align with what's included in the stable hash

    # High-impact changes (OS, Browser Family, Device Type)
    if stored_fingerprint_data.get("os_name") != current_dict.get("os_name"):
        risk_score += 25
        logger.debug(f"Risk +25: OS mismatch ('{stored_fingerprint_data.get('os_name')}' vs '{current_dict.get('os_name')}')")
    if stored_fingerprint_data.get("browser_name") != current_dict.get("browser_name"):
        risk_score += 20
        logger.debug(f"Risk +20: Browser mismatch ('{stored_fingerprint_data.get('browser_name')}' vs '{current_dict.get('browser_name')}')")
    if stored_fingerprint_data.get("device_type") != current_dict.get("device_type"):
        risk_score += 30
        logger.debug(f"Risk +30: Device type mismatch ('{stored_fingerprint_data.get('device_type')}' vs '{current_dict.get('device_type')}')")

    # Medium-impact changes (Versions - less critical than family change)
    # Consider if version changes should add risk - often legitimate updates
    # if stored_fingerprint_data.get("browser_version") != current_dict.get("browser_version"):
    #     risk_score += 5 # Lower score for version change
    # if stored_fingerprint_data.get("os_version") != current_dict.get("os_version"):
    #     risk_score += 5 # Lower score for version change

    # Location changes (Focus on Country)
    if stored_fingerprint_data.get("country_code") != current_dict.get("country_code"):
        # Handle case where one is None (e.g., local vs public)
        if stored_fingerprint_data.get("country_code") is not None and current_dict.get("country_code") is not None:
             risk_score += 40  # Major location change
             logger.debug(f"Risk +40: Country mismatch ('{stored_fingerprint_data.get('country_code')}' vs '{current_dict.get('country_code')}')")
        else:
             risk_score += 10 # Change involving local/unknown network
             logger.debug(f"Risk +10: Country change involving local/unknown ('{stored_fingerprint_data.get('country_code')}' vs '{current_dict.get('country_code')}')")

    # IP address change - Expected, low risk unless country also changed (handled above)
    # stored_ip = stored_fingerprint_data.get("ip_address", "") # IP likely not stored
    # current_ip = current_dict.get("ip_address", "")
    # if stored_ip != current_ip:
    #     risk_score += 1 # Very low risk for IP change itself

    # Client-side Hashed Signals (High impact if available and changed)
    client_hashes = ["screen_hash", "time_zone_hash", "language_hash", "canvas_hash", "webgl_hash"]
    for key in client_hashes:
        stored_val = stored_fingerprint_data.get(key)
        current_val = current_dict.get(key)
        if stored_val and current_val and stored_val != current_val:
            risk_score += 15 # Significant weight for mismatch in client hashes
            logger.debug(f"Risk +15: Client hash mismatch for '{key}'")
        elif stored_val and not current_val:
            risk_score += 5 # Client hash was present, now missing
            logger.debug(f"Risk +5: Client hash missing for '{key}'")
        elif not stored_val and current_val:
            risk_score += 2 # Client hash newly added (less risky)
            logger.debug(f"Risk +2: Client hash added for '{key}'")


    # Cap at 100
    final_score = min(risk_score, 100)
    logger.info(f"Calculated risk score: {final_score} (Threshold: {RISK_THRESHOLD_2FA})")
    return final_score

def should_require_2fa(
    stored_fingerprint_data: Dict[str, Any],
    current_fingerprint: DeviceFingerprint
) -> bool:
    """Determine if 2FA should be required based on fingerprint changes."""
    risk_level = calculate_risk_level(stored_fingerprint_data, current_fingerprint)
    return risk_level >= RISK_THRESHOLD_2FA

# --- Deprecated / To be removed ---
# Note: Keep original IP extraction logic for now as it's used by the new functions.
# The old fingerprinting and device record update functions are effectively replaced.
