"""Dependency-light loader support for pure S3 service unit tests.

The integration deploy checkout intentionally does not install boto3. These
stubs expose only import-time symbols; individual tests replace all clients and
never perform network operations.
"""

from __future__ import annotations

import importlib
import sys
import types


def ensure_s3_dependencies() -> None:
    """Install minimal boto modules only when optional runtime packages are absent."""
    try:
        importlib.import_module("boto3")
        importlib.import_module("botocore.config")
        importlib.import_module("botocore.exceptions")
        return
    except ModuleNotFoundError:
        pass

    boto3_module = types.ModuleType("boto3")
    boto3_module.client = lambda *_args, **_kwargs: None

    botocore_module = types.ModuleType("botocore")
    config_module = types.ModuleType("botocore.config")
    exceptions_module = types.ModuleType("botocore.exceptions")

    class Config:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

    class ClientError(Exception):
        def __init__(self, response=None, operation_name="") -> None:
            super().__init__(operation_name)
            self.response = response or {"Error": {}}

    class BotocoreTransportError(Exception):
        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__(self.__class__.__name__)

    config_module.Config = Config
    for name in (
        "ClientError",
        "ConnectionClosedError",
        "ConnectTimeoutError",
        "EndpointConnectionError",
        "HTTPClientError",
        "ReadTimeoutError",
    ):
        setattr(
            exceptions_module,
            name,
            ClientError if name == "ClientError" else type(name, (BotocoreTransportError,), {}),
        )

    botocore_module.config = config_module
    botocore_module.exceptions = exceptions_module
    sys.modules.setdefault("boto3", boto3_module)
    sys.modules.setdefault("botocore", botocore_module)
    sys.modules.setdefault("botocore.config", config_module)
    sys.modules.setdefault("botocore.exceptions", exceptions_module)


def load_s3_service_module():
    ensure_s3_dependencies()
    return importlib.import_module("backend.core.api.app.services.s3.service")
