"""Regression tests for app metadata provider availability checks.

These tests protect Settings > Apps visibility from provider-specific secret
shapes. App skills can use credentials that are not named `api_key`; the app
store metadata endpoint must still treat those skills as configured so the
frontend does not hide them after user-specific skill filtering.
"""

from __future__ import annotations

import pytest

from backend.core.api.app.routes.apps import check_provider_api_key_available


class FakeSecretsManager:
    vault_token = "test-token"
    vault_url = "http://vault.test"

    async def get_secret(self, *, secret_path: str, secret_key: str) -> str | None:
        if secret_path == "kv/data/providers/edamam" and secret_key in {"app_id", "app_key"}:
            return "configured"
        return None


@pytest.mark.anyio
async def test_edamam_availability_accepts_app_id_and_app_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SECRET__EDAMAM__API_KEY", raising=False)
    monkeypatch.delenv("SECRET__EDAMAM__APP_ID", raising=False)
    monkeypatch.delenv("SECRET__EDAMAM__APP_KEY", raising=False)

    assert await check_provider_api_key_available("edamam", FakeSecretsManager()) is True
