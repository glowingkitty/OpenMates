# backend/tests/test_vault_token_handoff.py
#
# Regression tests for Vault api.token handoff safety. The API startup script
# must not accept a stale token file just because Vault itself is unsealed and
# healthy. It must validate the token with lookup-self before starting the API.
#
# These tests mock the Vault HTTP API so they run without a live Vault instance.
# Production incident context: an invalid api.token caused auth/encryption calls
# to fail at runtime while health checks still reported Vault as reachable.

from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest


@pytest.mark.asyncio
async def test_validate_token_file_rejects_missing_token():
    from core.api.app.utils.vault_token_check import validate_token_file

    with patch("os.path.exists", return_value=False):
        result = await validate_token_file("http://vault:8200", "/vault-data/api.token")

    assert result.valid is False
    assert result.reason == "missing_token_file"


@pytest.mark.asyncio
async def test_validate_token_file_rejects_invalid_vault_token():
    from core.api.app.utils.vault_token_check import validate_token_file

    response = MagicMock()
    response.status_code = 403
    response.text = '{"errors":["permission denied"]}'

    client = AsyncMock()
    client.get = AsyncMock(return_value=response)

    with patch("os.path.exists", return_value=True), patch("builtins.open", mock_open(read_data="hvs.invalid")):
        result = await validate_token_file("http://vault:8200", "/vault-data/api.token", client=client)

    assert result.valid is False
    assert result.reason == "invalid_token"
    client.get.assert_awaited_once_with(
        "http://vault:8200/v1/auth/token/lookup-self",
        headers={"X-Vault-Token": "hvs.invalid"},
    )


@pytest.mark.asyncio
async def test_validate_token_file_accepts_valid_token_with_required_policies():
    from core.api.app.utils.vault_token_check import validate_token_file

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "data": {
            "ttl": 86400,
            "policies": ["default", "api-service", "api-encryption"],
        }
    }

    client = AsyncMock()
    client.get = AsyncMock(return_value=response)

    with patch("os.path.exists", return_value=True), patch("builtins.open", mock_open(read_data="hvs.valid")):
        result = await validate_token_file("http://vault:8200", "/vault-data/api.token", client=client)

    assert result.valid is True
    assert result.reason == "valid"
    assert result.ttl_seconds == 86400


@pytest.mark.asyncio
async def test_validate_token_file_rejects_token_missing_required_policies():
    from core.api.app.utils.vault_token_check import validate_token_file

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "data": {
            "ttl": 86400,
            "policies": ["default", "api-service"],
        }
    }

    client = AsyncMock()
    client.get = AsyncMock(return_value=response)

    with patch("os.path.exists", return_value=True), patch("builtins.open", mock_open(read_data="hvs.valid")):
        result = await validate_token_file("http://vault:8200", "/vault-data/api.token", client=client)

    assert result.valid is False
    assert result.reason == "missing_policies"
    assert result.missing_policies == ["api-encryption"]
