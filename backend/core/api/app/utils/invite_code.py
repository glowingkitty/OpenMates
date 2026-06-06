import logging
import os
from typing import TYPE_CHECKING, Tuple, Dict, Any, Optional, List

if TYPE_CHECKING:
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.cache import CacheService

logger = logging.getLogger(__name__)

def _parse_signup_allowed_domains(primary_domain: Optional[str], test_domains_env: Optional[str]) -> List[str]:
    """
    Build a normalized allowlist of email domains for signup.
    
    This function centralizes parsing for:
    - SIGNUP_DOMAIN_RESTRICTION (primary domain restriction)
    - SIGNUP_TEST_EMAIL_DOMAINS (comma-separated test domains)
    
    The allowlist is used in auth flows to explicitly permit only known domains
    during development or automated test runs.
    """
    allowed_domains: List[str] = []
    
    # Primary domain restriction (usually one domain, but self-host setup may
    # write a comma-separated allowlist).
    if primary_domain:
        for domain in primary_domain.split(","):
            normalized = domain.strip()
            if normalized:
                allowed_domains.append(normalized)
    
    # Additional test domains are provided as a comma-separated list.
    if test_domains_env:
        for domain in test_domains_env.split(","):
            normalized = domain.strip()
            if normalized:
                allowed_domains.append(normalized)
    
    # Normalize to lowercase and de-duplicate while preserving order.
    normalized_domains: List[str] = []
    for domain in allowed_domains:
        domain_lower = domain.lower()
        if domain_lower not in normalized_domains:
            normalized_domains.append(domain_lower)
    
    return normalized_domains

def _get_self_host_signup_mode() -> str:
    mode = os.getenv("SELF_HOST_SIGNUP_MODE", "invite_only").strip().lower()
    if mode not in {"invite_only", "domain_allowlist", "invite_and_domain"}:
        logger.warning("Invalid SELF_HOST_SIGNUP_MODE=%s; falling back to invite_only", mode)
        return "invite_only"
    return mode

def is_email_domain_allowed(email: Optional[str], allowed_domains: List[str]) -> Tuple[bool, Optional[str]]:
    """Validate an email against the exact-domain allowlist used for signup."""
    email_parts = email.split('@') if isinstance(email, str) else []
    email_domain = email_parts[1].lower() if len(email_parts) == 2 else None
    return bool(email_domain and email_domain in allowed_domains), email_domain

async def validate_invite_code(invite_code: str, directus_service: "DirectusService", cache_service: "CacheService") -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Validate the invite code.
    
    Returns:
    - Tuple of (is_valid, message, code_data)
    - code_data contains the invite code properties or None if invalid
    """
    cache_key = f"invite_code:{invite_code}"
    code_data = await cache_service.get(cache_key)
    
    if code_data is None:
        logger.info(f"Invite code {invite_code} not found in cache, fetching from Directus")
        code_data = await directus_service.get_invite_code(invite_code)
        
        if code_data:
            await cache_service.set(cache_key, code_data)
    
    if code_data is None:
        logger.warning(f"Invite code {invite_code} is invalid")
        return False, "Invalid invite code", None
    
    logger.info(f"Invite code {invite_code} is valid")
    return True, "Invite code is valid", code_data


async def get_signup_requirements(
    directus_service: "DirectusService",
    cache_service: "CacheService"
) -> Tuple[bool, bool, Optional[List[str]]]:
    """
    Determine signup requirements based on server edition and configuration.
    
    IMPORTANT: SIGNUP_DOMAIN_RESTRICTION and SIGNUP_TEST_EMAIL_DOMAINS are ALWAYS enforced
    when set, regardless of server edition. This allows restricting dev servers while
    still permitting automated test signups from approved domains.
    
    For self-hosted edition:
    - SELF_HOST_SIGNUP_MODE=invite_only: require invite code
    - SELF_HOST_SIGNUP_MODE=domain_allowlist: require allowed email domain
    - SELF_HOST_SIGNUP_MODE=invite_and_domain: require both
    
    For non-self-hosted (production/development):
    - If SIGNUP_DOMAIN_RESTRICTION or SIGNUP_TEST_EMAIL_DOMAINS is set: enforce domain restriction (in addition to SIGNUP_LIMIT logic)
    - Use SIGNUP_LIMIT logic for invite code requirements
    
    Args:
        directus_service: DirectusService instance for database queries
        cache_service: CacheService instance for caching
        
    Returns:
        Tuple of (require_invite_code, require_domain_restriction, domain_restriction_value):
        - require_invite_code: True if invite code is required
        - require_domain_restriction: True if domain restriction is required
        - domain_restriction_value: The domain allowlist if set, None otherwise
    """
    from backend.core.api.app.utils.server_mode import get_server_edition
    
    server_edition = get_server_edition()
    self_host_domains = os.getenv("SELF_HOST_SIGNUP_ALLOWED_DOMAINS")
    domain_restriction = self_host_domains if server_edition == "self_hosted" else os.getenv("SIGNUP_DOMAIN_RESTRICTION")
    test_domains_env = os.getenv("SIGNUP_TEST_EMAIL_DOMAINS")
    allowed_domains = _parse_signup_allowed_domains(domain_restriction, test_domains_env)
    
    # Domain restrictions are ALWAYS enforced when configured (for all server editions).
    require_domain_restriction = bool(allowed_domains)
    
    # For self-hosted edition, enforce explicit operator-selected signup modes.
    if server_edition == "self_hosted":
        mode = _get_self_host_signup_mode()
        require_invite_code = mode in {"invite_only", "invite_and_domain"}
        require_domain_restriction = mode in {"domain_allowlist", "invite_and_domain"}

        if require_domain_restriction and not allowed_domains:
            logger.warning(
                "Self-hosted signup mode %s requires allowed domains, but none are configured; "
                "falling back to invite_only",
                mode,
            )
            return True, False, None

        logger.info(
            "Self-hosted signup mode %s: invite_required=%s, domain_required=%s",
            mode,
            require_invite_code,
            require_domain_restriction,
        )
        return (
            require_invite_code,
            require_domain_restriction,
            allowed_domains if require_domain_restriction else None,
        )
    
    # For non-self-hosted (production/development), use SIGNUP_LIMIT logic
    signup_limit = int(os.getenv("SIGNUP_LIMIT", "0"))
    
    if signup_limit == 0:
        logger.info("SIGNUP_LIMIT is 0 - open signup enabled (invite codes not required)")
        return False, require_domain_restriction, allowed_domains if allowed_domains else None
    else:
        # SIGNUP_LIMIT > 0: require invite codes when completed signups count reaches the limit
        # Check if we have this value cached
        cached_require_invite_code = await cache_service.get("require_invite_code")
        if cached_require_invite_code is not None:
            require_invite_code = cached_require_invite_code
        else:
            # Get the count of users who completed signup (not just registered)
            # This counts users who completed payment/signup (last_opened is not a signup path)
            completed_signups = await directus_service.get_completed_signups_count()
            require_invite_code = completed_signups >= signup_limit
            # Cache this value for quick access
            await cache_service.set("require_invite_code", require_invite_code, ttl=172800)  # Cache for 48 hours
            logger.info(f"Completed signups count: {completed_signups}, signup limit: {signup_limit}, require_invite_code: {require_invite_code}")
        
        logger.info(f"Invite code requirement check: limit={signup_limit}, required={require_invite_code}")
        return require_invite_code, require_domain_restriction, allowed_domains if allowed_domains else None
