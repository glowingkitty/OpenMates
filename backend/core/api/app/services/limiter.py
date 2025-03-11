from slowapi import Limiter
from slowapi.util import get_remote_address

# Configure rate limiter
limiter = Limiter(key_func=get_remote_address, default_limits=["30/minute"])
