from fastapi import Request, HTTPException, status
import logging
import regex
import hashlib
import os
from typing import Tuple, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

async def verify_allowed_origin(request: Request):
    """
    Security dependency to verify the request originates from an allowed origin.
    This prevents direct API access to auth endpoints that should only be used by the frontend.
    """
    origin = request.headers.get("origin")
    allowed_origins = request.app.state.allowed_origins
    
    if not origin or origin not in allowed_origins:
        logger.warning(f"Unauthorized origin access to auth endpoint: {request.url.path}, Origin: {origin}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Authentication endpoints can only be accessed from authorized applications"
        )
    
    return True

def get_cookie_domain(request: Request) -> Optional[str]:
    """
    Intelligently determine the cookie domain for cross-subdomain authentication.
    
    This function enables secure cookie sharing between frontend and backend subdomains
    while maintaining compatibility with local development environments.
    
    Logic:
    1. Check for manual override via COOKIE_DOMAIN environment variable
    2. Extract parent domain from Origin header if present
    3. Fall back to extracting from allowed origins in app config
    4. Skip domain parameter for localhost/127.0.0.1 (development mode)
    5. Return parent domain with leading dot for production subdomains
    
    Examples:
    - localhost:5174 → None (same-origin cookies work fine)
    - openmates.org → ".openmates.org" (enables cross-subdomain sharing)
    - app.dev.openmates.org → ".openmates.org" (handles nested subdomains)
    
    Returns:
        Optional[str]: Cookie domain string (e.g., ".openmates.org") or None for localhost
    """
    # 1. Check for manual override (useful for special deployment scenarios)
    manual_domain = os.getenv("COOKIE_DOMAIN")
    if manual_domain:
        logger.info(f"Using manually configured COOKIE_DOMAIN: {manual_domain}")
        return manual_domain
    
    # 2. Try to extract domain from Origin header (most reliable for current request)
    origin = request.headers.get("origin")
    if origin:
        parsed_origin = urlparse(origin)
        hostname = parsed_origin.hostname
        
        if hostname:
            # Skip domain parameter for localhost and IP addresses
            if hostname in ["localhost", "127.0.0.1"] or hostname.startswith("192.168."):
                logger.debug(f"Detected localhost/local IP ({hostname}), skipping cookie domain")
                return None
            
            # Extract parent domain for production subdomains
            # e.g., "openmates.org" → "openmates.org"
            # e.g., "app.dev.openmates.org" → "openmates.org"
            parts = hostname.split(".")
            if len(parts) >= 2:
                # Get the last two parts (domain.tld)
                parent_domain = ".".join(parts[-2:])
                cookie_domain = f".{parent_domain}"
                logger.debug(f"Extracted cookie domain from Origin: {cookie_domain} (origin: {origin})")
                return cookie_domain
    
    # 3. Fallback: Extract from allowed_origins in app config
    if hasattr(request.app.state, "allowed_origins"):
        allowed_origins = request.app.state.allowed_origins
        for allowed_origin in allowed_origins:
            parsed = urlparse(allowed_origin)
            hostname = parsed.hostname
            
            if hostname and hostname not in ["localhost", "127.0.0.1"]:
                parts = hostname.split(".")
                if len(parts) >= 2:
                    parent_domain = ".".join(parts[-2:])
                    cookie_domain = f".{parent_domain}"
                    logger.debug(f"Extracted cookie domain from allowed_origins: {cookie_domain}")
                    return cookie_domain
    
    # 4. No domain detected - will use default same-origin behavior
    logger.debug("No specific cookie domain detected, using default same-origin cookies")
    return None

def validate_username(username: str) -> Tuple[bool, str]:
    """Validate username according to our requirements with international character support"""
    if not username:
        return False, "Username is required"
    
    if len(username) < 3:
        return False, "Username must be at least 3 characters"
    
    if len(username) > 20:
        return False, "Username cannot be longer than 20 characters"
    
    # Check for at least one letter (including international letters)
    if not regex.search(r'\p{L}', username):
        return False, "Username must contain at least one letter"
    
    # Allow letters (including international), numbers, dots, and underscores
    if not regex.fullmatch(r'[\p{L}\p{M}0-9._]+', username):
        return False, "Username can only contain letters, numbers, dots, and underscores"
    
    return True, ""

def validate_password(password: str) -> Tuple[bool, str]:
    """Validate password according to our requirements with international character support"""
    if not password:
        return False, "Password is required"
    
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    
    if len(password) > 60:
        return False, "Password cannot be longer than 60 characters"
    
    # Check for at least one letter (including international letters)
    if not regex.search(r'\p{L}', password):
        return False, "Password must contain at least one letter"
    
    # Check for at least one number
    if not regex.search(r'[0-9]', password):
        return False, "Password must contain at least one number"
    
    # Check for at least one special character (anything not a letter or number)
    if not regex.search(r'[^\p{L}\p{N}]', password):
        return False, "Password must contain at least one special character"
    
    return True, ""

def get_token_hash(token: str) -> str:
    """Create a SHA-256 hash of a token for secure storage"""
    return hashlib.sha256(token.encode()).hexdigest()
