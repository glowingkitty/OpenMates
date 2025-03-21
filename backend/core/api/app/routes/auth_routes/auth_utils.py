from fastapi import Request, HTTPException, status
import logging
import regex
import hashlib
from typing import Tuple

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
