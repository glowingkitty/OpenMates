"""
Directus cookie normalization helpers.

Directus deployments may expose the refresh token cookie as either
``directus_refresh_token`` or ``refresh_token``. The OpenMates API always
renames that cookie to ``auth_refresh_token`` before sending it to browsers.
Keeping this logic isolated makes auth session finalization testable without
importing the full FastAPI route stack.
"""

from typing import Optional


DIRECTUS_REFRESH_COOKIE_NAMES = {"directus_refresh_token", "refresh_token"}


def normalize_directus_cookie(name: str) -> str:
    """Map Directus auth cookie names to OpenMates auth cookie names."""
    if name in DIRECTUS_REFRESH_COOKIE_NAMES:
        return "auth_refresh_token"
    if name.startswith("directus_"):
        return "auth_" + name[9:]
    return name


def extract_directus_refresh_token(cookies: dict[str, str]) -> Optional[str]:
    """Return the Directus refresh token regardless of Directus cookie naming."""
    for name in DIRECTUS_REFRESH_COOKIE_NAMES:
        token = cookies.get(name)
        if token:
            return token
    return None
