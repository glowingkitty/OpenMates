import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def get_allowed_domain() -> Optional[str]:
    """
    Get the allowed domain from domain security service.
    This reads from the encrypted domain_security_allowed.encrypted file.
    
    Returns:
        The allowed domain string from encrypted config or None if not loaded
    """
    # Import here to avoid circular dependencies
    # Access the global _ALLOWED_DOMAIN variable that gets populated
    # when DomainSecurityService.load_security_config() is called
    try:
        from backend.core.api.app.services.domain_security import _ALLOWED_DOMAIN
        return _ALLOWED_DOMAIN
    except ImportError:
        logger.warning("Could not import _ALLOWED_DOMAIN from domain_security module")
        return None

def get_hosting_domain() -> Optional[str]:
    """
    Get the domain the server is hosting on.
    Returns None if running on localhost/IP.
    """
    # Try PRODUCTION_URL first
    production_url = os.getenv("PRODUCTION_URL", "").strip()
    if production_url:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(production_url)
            hostname = parsed.hostname
            # Filter out localhost IPs
            if hostname and hostname.lower() not in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
                return hostname.lower()
        except Exception:
            pass
    
    # Try FRONTEND_URLS
    frontend_urls = os.getenv("FRONTEND_URLS", "").strip()
    if frontend_urls:
        try:
            from urllib.parse import urlparse
            for url in frontend_urls.split(','):
                url = url.strip()
                if url:
                    parsed = urlparse(url)
                    hostname = parsed.hostname
                    # Filter out localhost IPs
                    if hostname and hostname.lower() not in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
                        return hostname.lower()
        except Exception:
            pass
    
    return None

def is_payment_enabled() -> bool:
    """
    Check if payment functionality should be enabled.
    
    Payment is enabled when:
    1. Domain matches the allowed domain from encrypted config (regardless of environment)
    2. OR (development environment AND localhost)
    
    Returns:
        True if payment should be enabled, False otherwise.
    """
    domain = get_hosting_domain()
    is_localhost = domain is None
    
    # Get allowed domain from encrypted config (not hardcoded!)
    allowed_domain = get_allowed_domain()
    is_allowed_domain = domain == allowed_domain if allowed_domain else False
    
    server_env = os.getenv("SERVER_ENVIRONMENT", "development").lower()
    is_development = server_env == "development"
    
    # Case 1: Allowed domain from encrypted config (always enabled)
    if is_allowed_domain:
        return True
        
    # Case 2: Development on localhost (enabled for testing)
    if is_development and is_localhost:
        return True
        
    # All other cases (self-hosted, or dev on custom domain) -> Disabled
    return False

def get_server_edition() -> str:
    """
    Get the server edition string.
    
    Returns:
        "production" - Official production server (matches allowed domain from encrypted config)
        "development" - Development server (localhost or allowed domain in dev mode)
        "self_hosted" - Self-hosted instance
    """
    domain = get_hosting_domain()
    
    # Get allowed domain from encrypted config (not hardcoded!)
    allowed_domain = get_allowed_domain()
    is_allowed_domain = domain == allowed_domain if allowed_domain else False
    
    if is_allowed_domain:
        return "production"
    
    server_env = os.getenv("SERVER_ENVIRONMENT", "development").lower()
    if server_env == "development":
        # If development on localhost, it's development edition
        # If development on other domain (not allowed domain), it's self_hosted (simulated)
        if domain is None: # localhost
            return "development"
        else:
            return "self_hosted"
            
    return "self_hosted"
