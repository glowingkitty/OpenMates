from slowapi import Limiter
from slowapi.util import get_remote_address

# Configure rate limiter.
# NOTE: No default_limits — every route that needs rate limiting MUST use an
# explicit @limiter.limit() decorator.  A global default_limits silently rate-
# limits undecorated routes and, worse, falls back as a catch-all when slowapi
# fails to match a dynamically-registered handler to its _route_limits registry
# (see apps_api.py skill handlers).  Explicit-only avoids phantom 429s.
limiter = Limiter(key_func=get_remote_address)
