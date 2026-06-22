"""OpenMates Python SDK facade.

Purpose: provide a lazy API-key client for Python integrations.
Architecture: thin REST facade over public /v1 endpoints.
Security: API keys are bearer credentials and are never persisted by this class.
Tests: packages/openmates-python/tests/test_sdk.py.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

import requests


DEFAULT_API_URL = "https://api.openmates.org"
DEFAULT_TIMEOUT_SECONDS = 60


class OpenMatesConfigError(RuntimeError):
    """Raised when the SDK is missing required configuration."""


class OpenMatesApiError(RuntimeError):
    """Raised when the OpenMates API returns a non-success response."""

    def __init__(self, status_code: int, data: Any):
        super().__init__(f"OpenMates API request failed with HTTP {status_code}")
        self.status_code = status_code
        self.data = data


@dataclass(frozen=True)
class ChatResponse:
    """Simple response wrapper for chat messages."""

    content: str | None = None
    raw: dict[str, Any] | None = None


class OpenMates:
    """Lazy API-key SDK client."""

    def __init__(self, api_key: str | None = None, api_url: str = DEFAULT_API_URL):
        self._api_key = api_key or os.getenv("OPENMATES_API_KEY")
        self._api_url = api_url.rstrip("/")
        self.apps = OpenMatesApps(self)
        self.chats = OpenMatesChats(self)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._api_key:
            raise OpenMatesConfigError("OpenMates API key is required")

        response = requests.post(
            f"{self._api_url}{path}",
            json=payload,
            headers=self._headers(),
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        return self._parse_response(response)

    def _get(self, path: str) -> dict[str, Any]:
        if not self._api_key:
            raise OpenMatesConfigError("OpenMates API key is required")

        response = requests.get(
            f"{self._api_url}{path}",
            headers=self._headers(has_body=False),
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        return self._parse_response(response)

    def _headers(self, *, has_body: bool = True) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "X-OpenMates-SDK": "pip",
            "X-OpenMates-Device-Identity": os.name,
        }
        if has_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _parse_response(self, response: Any) -> dict[str, Any]:
        data = response.json()
        if response.status_code >= 400:
            raise OpenMatesApiError(response.status_code, data)
        return data


class OpenMatesApps:
    """App-skill SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client

    def run(self, app_id: str, skill_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
        return self._client._post(
            f"/v1/apps/{app_id}/skills/{skill_id}",
            {"input_data": input_data, "parameters": {}},
        )


class OpenMatesChats:
    """Chat SDK namespace."""

    def __init__(self, client: OpenMates):
        self._client = client

    def create(self, *, save_to_account: bool = False) -> "OpenMatesChat":
        return OpenMatesChat(self._client, save_to_account=save_to_account)

    def list(self, *, limit: int = 10, offset: int = 0) -> list[dict[str, Any]]:
        data = self._client._get(f"/v1/sdk/chats?limit={limit}&offset={offset}")
        return data.get("chats", [])


class OpenMatesChat:
    """Single SDK chat handle."""

    def __init__(self, client: OpenMates, *, save_to_account: bool):
        self._client = client
        self._save_to_account = save_to_account

    def send(self, message: str) -> ChatResponse:
        data = self._client._post(
            "/v1/sdk/chats",
            {"message": message, "save_to_account": self._save_to_account},
        )
        response = data.get("response") or {}
        return ChatResponse(content=response.get("content"), raw=data)
