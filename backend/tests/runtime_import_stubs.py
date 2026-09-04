# backend/tests/runtime_import_stubs.py
#
# Optional production dependencies are not installed in every lightweight local
# pytest environment. Contract tests that do not exercise those services install
# inert stubs before importing route modules with runtime-only dependencies.

from __future__ import annotations

import importlib.util
import re
import sys
import types
from types import SimpleNamespace


def _module_missing(name: str) -> bool:
    if name in sys.modules:
        return False
    return importlib.util.find_spec(name) is None


def install_code_route_import_stubs() -> None:
    if _module_missing("toon_format"):
        toon_format_stub = types.ModuleType("toon_format")

        def _stub_encode(value: dict) -> str:
            return "\n".join(f"{key}: {item}" for key, item in value.items())

        def _stub_decode(value: str) -> dict:
            decoded: dict[str, str] = {}
            for line in value.splitlines():
                key, _, item = line.partition(": ")
                if key:
                    decoded[key] = item
            return decoded

        toon_format_stub.encode = _stub_encode
        toon_format_stub.decode = _stub_decode
        sys.modules.setdefault("toon_format", toon_format_stub)

    if _module_missing("celery"):
        celery_stub = types.ModuleType("celery")
        tasks_stub = types.ModuleType("backend.core.api.app.tasks")
        tasks_stub.__path__ = []
        celery_config_stub = types.ModuleType("backend.core.api.app.tasks.celery_config")
        celery_result_stub = types.ModuleType("celery.result")

        class _CeleryAppStub:
            def send_task(self, *_args, **_kwargs):
                return None

            def task(self, *_args, **_kwargs):
                return lambda func: func

        class _AsyncResultStub:
            pass

        async def _missing_worker_cache_service():
            raise AssertionError("worker cache service is not used by these unit tests")

        celery_config_stub.app = _CeleryAppStub()
        celery_config_stub.get_worker_cache_service = _missing_worker_cache_service
        celery_stub.Celery = _CeleryAppStub
        celery_result_stub.AsyncResult = _AsyncResultStub
        sys.modules.setdefault("celery", celery_stub)
        sys.modules.setdefault("backend.core.api.app.tasks", tasks_stub)
        sys.modules.setdefault("backend.core.api.app.tasks.celery_config", celery_config_stub)
        sys.modules.setdefault("celery.result", celery_result_stub)

    if _module_missing("redis"):
        redis_stub = types.ModuleType("redis")
        redis_asyncio_stub = types.ModuleType("redis.asyncio")

        class _RedisStub:
            def __init__(self, *_args, **_kwargs):
                raise AssertionError("real Redis is not used by these unit tests")

        redis_asyncio_stub.Redis = _RedisStub
        redis_stub.asyncio = redis_asyncio_stub
        redis_stub.exceptions = SimpleNamespace(
            ConnectionError=ConnectionError,
            TimeoutError=TimeoutError,
            RedisError=Exception,
        )
        sys.modules.setdefault("redis", redis_stub)
        sys.modules.setdefault("redis.asyncio", redis_asyncio_stub)

    if _module_missing("aiohttp"):
        aiohttp_stub = types.ModuleType("aiohttp")
        aiohttp_stub.ClientSession = object
        sys.modules.setdefault("aiohttp", aiohttp_stub)

    if _module_missing("dotenv"):
        dotenv_stub = types.ModuleType("dotenv")
        dotenv_stub.load_dotenv = lambda *_args, **_kwargs: None
        sys.modules.setdefault("dotenv", dotenv_stub)

    if _module_missing("slowapi"):
        slowapi_stub = types.ModuleType("slowapi")
        slowapi_util_stub = types.ModuleType("slowapi.util")

        class _LimiterStub:
            def __init__(self, *_args, **_kwargs):
                pass

            def limit(self, *_args, **_kwargs):
                return lambda func: func

        slowapi_stub.Limiter = _LimiterStub
        slowapi_util_stub.get_remote_address = lambda request: "127.0.0.1"
        sys.modules.setdefault("slowapi", slowapi_stub)
        sys.modules.setdefault("slowapi.util", slowapi_util_stub)

    sys.modules.setdefault("regex", re)

    googleapiclient_stub = types.ModuleType("googleapiclient")
    googleapiclient_discovery_stub = types.ModuleType("googleapiclient.discovery")
    googleapiclient_errors_stub = types.ModuleType("googleapiclient.errors")
    googleapiclient_discovery_stub.build = lambda *_args, **_kwargs: None
    googleapiclient_errors_stub.HttpError = Exception
    sys.modules.setdefault("googleapiclient", googleapiclient_stub)
    sys.modules.setdefault("googleapiclient.discovery", googleapiclient_discovery_stub)
    sys.modules.setdefault("googleapiclient.errors", googleapiclient_errors_stub)
