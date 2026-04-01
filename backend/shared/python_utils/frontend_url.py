# backend/shared/python_utils/frontend_url.py
#
# Shared helper to resolve the frontend base URL for email deep links.
#
# Priority: FRONTEND_URL > first HTTPS entry in FRONTEND_URLS > fallback.
# Ensures email links point to the correct domain on both dev and production.

import os

# Default production URL used when no env var is set
_DEFAULT_FRONTEND_URL = "https://openmates.org"


def get_frontend_base_url() -> str:
    """
    Resolve the frontend base URL for constructing email deep links.

    1. ``FRONTEND_URL`` (explicit override, preferred)
    2. First HTTPS URL from ``FRONTEND_URLS`` (comma-separated CORS origins)
    3. Hardcoded fallback ``https://openmates.org``

    Returns:
        Base URL without trailing slash, e.g. ``https://app.dev.openmates.org``
    """
    explicit = os.getenv("FRONTEND_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")

    # Derive from FRONTEND_URLS (comma-separated list used for CORS).
    # Pick the first HTTPS entry to avoid linking to http://localhost.
    urls_csv = os.getenv("FRONTEND_URLS", "").strip()
    if urls_csv:
        for url in urls_csv.split(","):
            url = url.strip()
            if url.startswith("https://"):
                return url.rstrip("/")

    return _DEFAULT_FRONTEND_URL
