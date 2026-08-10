"""
Account authentication-method capability contract tests.

These tests keep account security available without cloud billing and require
storage failures to remain explicit instead of becoming false capability state.
No credentials, secrets, or external services are used.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes.auth_routes.auth_methods import get_auth_methods


@pytest.mark.asyncio
async def test_get_auth_methods_returns_all_capabilities() -> None:
    directus = SimpleNamespace(
        get_items=AsyncMock(
            side_effect=[
                [{"id": "passkey"}],
                [{"login_method": "password"}, {"login_method": "recovery_key"}],
                [{"encrypted_tfa_secret": "encrypted"}],
            ]
        ),
    )

    result = await get_auth_methods(
        request=SimpleNamespace(),
        current_user=SimpleNamespace(id="00000000-0000-4000-8000-000000000001"),
        directus_service=directus,
    )

    assert result.has_passkey is True
    assert result.has_2fa is True
    assert result.has_password is True
    assert result.has_recovery_key is True


@pytest.mark.asyncio
async def test_get_auth_methods_fails_closed_when_storage_is_unavailable() -> None:
    directus = SimpleNamespace(
        get_items=AsyncMock(side_effect=RuntimeError("storage unavailable")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_auth_methods(
            request=SimpleNamespace(),
            current_user=SimpleNamespace(id="00000000-0000-4000-8000-000000000001"),
            directus_service=directus,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Authentication methods temporarily unavailable"


@pytest.mark.asyncio
async def test_get_auth_methods_requires_strict_storage_reads() -> None:
    directus = SimpleNamespace(
        get_items=AsyncMock(
            side_effect=[[], [], [{"encrypted_tfa_secret": None}]],
        ),
    )

    await get_auth_methods(
        request=SimpleNamespace(),
        current_user=SimpleNamespace(id="00000000-0000-4000-8000-000000000001"),
        directus_service=directus,
    )

    assert directus.get_items.await_count == 3
    for call in directus.get_items.await_args_list:
        assert call.kwargs["raise_on_error"] is True


@pytest.mark.asyncio
async def test_get_auth_methods_rejects_developer_api_keys() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await get_auth_methods(
            request=SimpleNamespace(state=SimpleNamespace(auth_source="api_key")),
            current_user=SimpleNamespace(id="00000000-0000-4000-8000-000000000001"),
            directus_service=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "First-party session required"
