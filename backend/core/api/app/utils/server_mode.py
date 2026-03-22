import os
import logging
from typing import Optional, Tuple
from urllib.parse import urlparse

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

def is_domain_allowed_or_subdomain(domain: Optional[str], allowed_domain: Optional[str]) -> bool:
    """
    Check if a domain is the allowed domain or a subdomain of it.
    
    This function handles subdomain matching so that subdomains of the official
    domain are all considered as the official domain.
    
    Args:
        domain: The domain to check (e.g., "app.dev.example.org")
        allowed_domain: The allowed base domain from encrypted config (e.g., "example.org")
        
    Returns:
        True if domain is the allowed domain or a subdomain of it, False otherwise
        
    Examples:
        is_domain_allowed_or_subdomain("app.dev.example.org", "example.org") -> True
        is_domain_allowed_or_subdomain("dev.example.org", "example.org") -> True
        is_domain_allowed_or_subdomain("example.org", "example.org") -> True
        is_domain_allowed_or_subdomain("other.com", "example.org") -> False
        is_domain_allowed_or_subdomain("malicious-example.org", "example.org") -> False
    """
    # If either domain is None, return False
    if not domain or not allowed_domain:
        return False
    
    # Normalize domains to lowercase for comparison
    domain = domain.lower().strip()
    allowed_domain = allowed_domain.lower().strip()
    
    # Exact match: domain is the allowed domain
    if domain == allowed_domain:
        return True
    
    # Check if domain is a subdomain of allowed_domain
    # A subdomain must end with "." + allowed_domain
    # This prevents false positives like "malicious-domain.org"
    if domain.endswith(f".{allowed_domain}"):
        return True
    
    return False

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
    1. Domain matches the allowed domain from encrypted config OR is a subdomain of it (regardless of environment)
    2. OR (development environment AND localhost)
    3. OR (development environment AND domain is a *.dev.{allowed_domain} subdomain)
    
    Note: This function may be called before encrypted config is loaded (during router registration).
    In that case, it will try to load the config, or check environment variables for dev subdomain patterns.
    
    Returns:
        True if payment should be enabled, False otherwise.
    """
    domain = get_hosting_domain()
    is_localhost = domain is None
    
    server_env = os.getenv("SERVER_ENVIRONMENT", "development").lower()
    is_development = server_env == "development"
    
    # Case 1: Development on localhost (enabled for testing)
    if is_development and is_localhost:
        return True
    
    # Case 2: Check if domain matches allowed domain or is a subdomain
    # Get allowed domain from encrypted config (may be None if not loaded yet)
    allowed_domain = get_allowed_domain()
    
    if allowed_domain:
        # Config is loaded - use proper domain matching
        is_allowed_domain = is_domain_allowed_or_subdomain(domain, allowed_domain)
        if is_allowed_domain:
            return True
    else:
        # Config not loaded yet (e.g., during router registration)
        # Try to load it now if we're in production mode and have a domain
        # This ensures payment is enabled correctly even during router registration
        if not is_development and domain:
            try:
                from backend.core.api.app.services.domain_security import DomainSecurityService
                domain_security_service = DomainSecurityService()
                domain_security_service.load_security_config()
                # Now try to get the allowed domain again
                allowed_domain = get_allowed_domain()
                if allowed_domain:
                    is_allowed_domain = is_domain_allowed_or_subdomain(domain, allowed_domain)
                    if is_allowed_domain:
                        logger.debug(f"Payment enabled: Production domain '{domain}' matches allowed domain '{allowed_domain}' (config loaded during router registration)")
                        return True
            except SystemExit:
                # Re-raise SystemExit - if config can't be loaded, server should not start
                raise
            except Exception as e:
                # If config can't be loaded for other reasons, log warning but don't fail
                # This allows the server to start even if config loading fails during router registration
                # The config will be loaded again during lifespan startup, where it will fail properly if needed
                logger.warning(f"Could not load domain security config during payment check: {e}. Will retry during lifespan startup.")
        
        # Fallback: Check if domain matches dev subdomain pattern
        # This handles the case where we're on dev.openmates.org or *.dev.openmates.org
        # We check for common dev subdomain patterns
        if domain:
            domain_lower = domain.lower()
            # Check for *.dev.* pattern (e.g., app.dev.openmates.org, dev.openmates.org)
            # This is a safe fallback for development servers
            if is_development and (".dev." in domain_lower or domain_lower.startswith("dev.")):
                logger.debug(f"Payment enabled: Development server detected on dev subdomain: {domain}")
                return True
    
    # All other cases (self-hosted, or dev on custom domain) -> Disabled
    return False

def get_server_edition() -> str:
    """
    Get the server edition string.
    
    Returns:
        "production" - Official production server (matches allowed domain from encrypted config or is a non-dev subdomain)
        "development" - Development server (allowed domain dev subdomain like *.dev.{allowed_domain})
        "self_hosted" - Self-hosted instance (including localhost)
    """
    domain = get_hosting_domain()
    
    # Get allowed domain from encrypted config (not hardcoded!)
    allowed_domain = get_allowed_domain()
    # Check if domain is the allowed domain or a subdomain of it
    # This handles subdomains of the official domain being treated as official
    is_allowed_domain = is_domain_allowed_or_subdomain(domain, allowed_domain)
    
    if is_allowed_domain:
        # It's an official domain - check if it's a dev subdomain
        if allowed_domain and domain:
            if is_dev_subdomain(domain, allowed_domain):
                return "development"
        elif domain:
            # Config not loaded yet - check for dev subdomain pattern
            domain_lower = domain.lower()
            server_env = os.getenv("SERVER_ENVIRONMENT", "development").lower()
            is_development = server_env == "development"
            if is_development and (".dev." in domain_lower or domain_lower.startswith("dev.")):
                return "development"
        # Official domain but not a dev subdomain - production
        return "production"
    
    # All other cases (localhost, custom domains, etc.) are self-hosted
    # localhost is treated as self-hosted, not development edition
    return "self_hosted"

def extract_domain_from_request(request) -> Optional[str]:
    """
    Extract the domain from the incoming request.
    
    This function checks the request headers to determine the actual domain
    the client is accessing. This is more secure than relying on environment
    variables alone, as it validates against the actual request.
    
    Priority order:
    1. Origin header (most reliable for CORS requests)
    2. Host header (fallback for direct API access)
    
    Args:
        request: FastAPI Request object
        
    Returns:
        Domain string (e.g., "app.dev.example.org") or None if localhost/IP
        
    Examples:
        extract_domain_from_request(request with Origin: "https://app.dev.example.org") -> "app.dev.example.org"
        extract_domain_from_request(request with Host: "api.example.org:8000") -> "api.example.org"
        extract_domain_from_request(request with localhost) -> None
    """
    # Try Origin header first (most reliable for browser requests)
    origin = request.headers.get("origin")
    if origin:
        try:
            parsed = urlparse(origin)
            hostname = parsed.hostname
            if hostname:
                # Filter out localhost and IP addresses
                if hostname.lower() not in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
                    return hostname.lower()
        except Exception as e:
            logger.debug(f"Failed to parse Origin header: {e}")
    
    # Fallback to Host header
    host = request.headers.get("host")
    if host:
        try:
            # Host header may include port (e.g., "api.example.org:8000")
            # Extract just the hostname part
            hostname = host.split(":")[0].strip()
            if hostname:
                # Filter out localhost and IP addresses
                if hostname.lower() not in ["localhost", "127.0.0.1", "::1", "0.0.0.0"]:
                    return hostname.lower()
        except Exception as e:
            logger.debug(f"Failed to parse Host header: {e}")
    
    # No valid domain found (likely localhost or IP)
    return None

def is_dev_subdomain(domain: str, allowed_domain: Optional[str]) -> bool:
    """
    Check if a domain is a development subdomain (matches pattern *.dev.{allowed_domain}).
    
    Args:
        domain: The domain to check (e.g., "app.dev.example.org")
        allowed_domain: The official domain from encrypted config (e.g., "example.org")
        
    Returns:
        True if domain matches *.dev.{allowed_domain} pattern, False otherwise
        
    Examples:
        is_dev_subdomain("app.dev.example.org", "example.org") -> True
        is_dev_subdomain("dev.example.org", "example.org") -> True
        is_dev_subdomain("api.dev.example.org", "example.org") -> True
        is_dev_subdomain("example.org", "example.org") -> False
        is_dev_subdomain("app.example.org", "example.org") -> False
    """
    if not domain or not allowed_domain:
        return False
    
    domain = domain.lower().strip()
    allowed_domain = allowed_domain.lower().strip()
    
    # Check if domain matches *.dev.{allowed_domain} pattern
    # This matches subdomains like "app.dev.example.org" or "dev.example.org"
    dev_pattern = f".dev.{allowed_domain}"
    if domain.endswith(dev_pattern) or domain == f"dev.{allowed_domain}":
        return True
    
    return False

def validate_request_domain(request) -> Tuple[Optional[str], bool, str]:
    """
    Validate the request domain against the official domain from encrypted config.
    
    This function extracts the domain from the request and checks if it matches
    the official domain or is a subdomain of it. This provides request-based
    security validation that cannot be easily spoofed by environment variables.
    
    It also detects development subdomains (*.dev.{official_domain}) to distinguish
    between production, development, and self-hosted instances.
    
    Args:
        request: FastAPI Request object
        
    Returns:
        Tuple of (domain: Optional[str], is_self_hosted: bool, edition: str)
        - domain: The extracted domain from the request (or None for localhost)
        - is_self_hosted: True if domain doesn't match official domain, False if it matches
        - edition: "production" | "development" | "self_hosted"
          - "production": Official domain or non-dev subdomain
          - "development": *.dev.{official_domain} subdomain
          - "self_hosted": Other domains or localhost
        
    Examples:
        validate_request_domain(request from "app.dev.example.org") -> ("app.dev.example.org", False, "development")
        validate_request_domain(request from "example.org") -> ("example.org", False, "production")
        validate_request_domain(request from "app.example.org") -> ("app.example.org", False, "production")
        validate_request_domain(request from "malicious.com") -> ("malicious.com", True, "self_hosted")
        validate_request_domain(request from localhost) -> (None, True, "self_hosted")
    """
    # Extract domain from request
    request_domain = extract_domain_from_request(request)
    
    # Get official domain from encrypted config
    allowed_domain = get_allowed_domain()
    
    # If no domain extracted (localhost), it's self-hosted
    if not request_domain:
        return None, True, "self_hosted"
    
    # Check if request domain matches official domain or is a subdomain
    is_official = is_domain_allowed_or_subdomain(request_domain, allowed_domain)
    
    if not is_official:
        # Not an official domain - self-hosted
        return request_domain, True, "self_hosted"
    
    # It's an official domain - check if it's a dev subdomain
    if is_dev_subdomain(request_domain, allowed_domain):
        return request_domain, False, "development"
    
    # Official domain but not dev subdomain - production
    return request_domain, False, "production"
