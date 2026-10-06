"""Short lived approval for client-encrypted Team display names.

Only the request that checks a name sees its plaintext. Redis stores a random
token's digest, the actor, and an expiry; no display name is persisted.
"""

import hashlib
import re
import secrets
import time
import unicodedata

APPROVAL_TTL_SECONDS = 600


def normalize_team_name(name: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", name).strip().lower().split())


def validate_team_name(name: str, domain_security_service: object) -> bool:
    normalized = normalize_team_name(name)
    if not normalized or len(normalized) > 100 or any(ord(ch) < 32 for ch in normalized):
        return False
    if not getattr(domain_security_service, "config_loaded", False):
        return False
    # Reuse the already loaded, signed and encrypted domain policy. Examine
    # normalized words as well as the complete name without exposing entries.
    candidates = {normalized, *re.findall(r"[\w.-]+", normalized)}
    for candidate in candidates:
        blocked, _reason = domain_security_service.is_domain_restricted(candidate)
        if blocked:
            return False
    words = set(re.findall(r"[\w]+", normalized))
    for restricted_domain in getattr(domain_security_service, "restricted_domains", ()):
        if isinstance(restricted_domain, str):
            brand = restricted_domain.lower().split(".", 1)[0]
            if brand in words:
                return False
    return True


def _cache_key(token: str) -> str:
    return "team:name-approval:" + hashlib.sha256(token.encode()).hexdigest()


async def issue_name_approval(cache: object, actor_user_id: str) -> tuple[str, int]:
    token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + APPROVAL_TTL_SECONDS
    saved = await cache.set(_cache_key(token), {"user_id": actor_user_id, "expires_at": expires_at}, ttl=APPROVAL_TTL_SECONDS)
    if saved is False:
        raise RuntimeError("Team name approval unavailable")
    return token, expires_at


async def consume_name_approval(cache: object, actor_user_id: str, token: str | None) -> bool:
    if not token:
        return False
    key = _cache_key(token)
    if hasattr(cache, "get_and_delete"):
        approval = await cache.get_and_delete(key)
    else:
        approval = await cache.get(key)
    if not isinstance(approval, dict) or approval.get("user_id") != actor_user_id or int(approval.get("expires_at") or 0) <= time.time():
        return False
    if not hasattr(cache, "get_and_delete"):
        await cache.delete(key)
    return True
