"""Strict API-key account client ``OpenMatesClient`` for the Python SDK.

Purpose: mirror the npm root ``OpenMatesClient`` (frontend/packages/openmates-cli/
src/sdkRootClient.ts). Construction without an explicit API key fails at once with
the typed ``OpenMatesApiKeyRequiredError`` (code ``OPENMATES_SDK_API_KEY_REQUIRED``)
instead of failing lazily at the first request; the legacy ``session`` and
``load_stored_session`` options are refused. It never reads ``OPENMATES_API_KEY``,
CLI state, session files or keychains and never falls back to anonymous use.
``OpenMates`` keeps its documented keyless guest routing and environment fallback.
Spec: specifications/surfaces/sdk (sdk.auth.api-key-only,
examples.sdk_api_key_only.missing-api-key-is-a-typed-error).
Tests: packages/openmates-python/tests/test_root_client_api_key_only.py.
"""

from __future__ import annotations

import os
from typing import Any

from .sdk import DEFAULT_API_URL, OpenMates, OpenMatesConfigError

SDK_API_KEY_REQUIRED_CODE = "OPENMATES_SDK_API_KEY_REQUIRED"

_MIGRATION = (
    "Create an API key in Settings → Developers and pass it explicitly: "
    "OpenMatesClient(api_key=...). The SDK never uses the CLI login."
)
_LEGACY_OPTIONS = ("session", "load_stored_session")


class OpenMatesApiKeyRequiredError(OpenMatesConfigError):
    """Typed refusal: an account client was constructed without an explicit API key."""

    code = SDK_API_KEY_REQUIRED_CODE


class OpenMatesClient(OpenMates):
    """API-key account client that requires an explicit key at construction."""

    def __init__(
        self,
        api_key: str | None = None,
        api_url: str = DEFAULT_API_URL,
        *,
        device_id: str | None = None,
        device_id_path: str | os.PathLike[str] | None = None,
        **legacy: Any,
    ):
        for name in legacy:
            if name in _LEGACY_OPTIONS:
                raise OpenMatesApiKeyRequiredError(
                    f"OpenMatesClient no longer accepts `{name}`; CLI sessions are not SDK credentials. {_MIGRATION}"
                )
            raise OpenMatesConfigError(f"Unknown OpenMatesClient option: {name}")
        if not isinstance(api_key, str) or not api_key.strip():
            raise OpenMatesApiKeyRequiredError(f"OpenMatesClient requires an explicit API key. {_MIGRATION}")
        super().__init__(api_key, api_url, device_id=device_id, device_id_path=device_id_path)

    @classmethod
    def load(
        cls,
        api_key: str | None = None,
        api_url: str = DEFAULT_API_URL,
        *,
        device_id: str | None = None,
        device_id_path: str | os.PathLike[str] | None = None,
        **legacy: Any,
    ) -> "OpenMatesClient":
        """Same as the constructor; mirrors npm ``OpenMatesClient.load``."""
        return cls(api_key, api_url, device_id=device_id, device_id_path=device_id_path, **legacy)
