import inspect
from functools import wraps
from typing import Any

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _has_real_request_arg(func: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> bool:
    try:
        bound = inspect.signature(func).bind_partial(*args, **kwargs)
    except TypeError:
        return False
    return isinstance(bound.arguments.get("request"), Request)


class OpenMatesLimiter(Limiter):
    def limit(self, *args: Any, **kwargs: Any) -> Any:
        decorator = super().limit(*args, **kwargs)

        def direct_call_safe_decorator(func: Any) -> Any:
            limited_func = decorator(func)

            if inspect.iscoroutinefunction(func):

                @wraps(func)
                async def async_wrapper(*func_args: Any, **func_kwargs: Any) -> Any:
                    if _has_real_request_arg(func, func_args, func_kwargs):
                        return await limited_func(*func_args, **func_kwargs)
                    return await func(*func_args, **func_kwargs)

                return async_wrapper

            @wraps(func)
            def sync_wrapper(*func_args: Any, **func_kwargs: Any) -> Any:
                if _has_real_request_arg(func, func_args, func_kwargs):
                    return limited_func(*func_args, **func_kwargs)
                return func(*func_args, **func_kwargs)

            return sync_wrapper

        return direct_call_safe_decorator

# Configure rate limiter.
# NOTE: No default_limits — every route that needs rate limiting MUST use an
# explicit @limiter.limit() decorator.  A global default_limits silently rate-
# limits undecorated routes and, worse, falls back as a catch-all when slowapi
# fails to match a dynamically-registered handler to its _route_limits registry
# (see apps_api.py skill handlers).  Explicit-only avoids phantom 429s.
limiter = OpenMatesLimiter(key_func=get_remote_address)
