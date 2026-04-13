# backend/tests/provider_contracts/conftest.py
#
# Shared fixtures for reverse-engineered provider contract probes.
#   * secrets_manager: initialised SecretsManager (needs Vault, so this suite
#     can only run inside app-ai-worker — GHA is excluded).
#   * webshare_proxy_url: rotating residential proxy for providers that
#     rate-limit or IP-block datacenter egress.
#   * browser_headers: realistic Chrome-on-Linux header set shared across
#     scrapers.
#
# All fixtures are module-scoped so a single probe run reuses the same
# SecretsManager and proxy credentials across every provider test.

from __future__ import annotations

import pytest
import pytest_asyncio

from backend.core.api.app.utils.secrets_manager import SecretsManager


@pytest_asyncio.fixture
async def secrets_manager() -> SecretsManager:
    sm = SecretsManager()
    await sm.initialize()
    return sm


@pytest_asyncio.fixture
async def webshare_proxy_url(secrets_manager: SecretsManager) -> str:
    username = await secrets_manager.get_secret(
        secret_path="kv/data/providers/webshare",
        secret_key="proxy_username",
    )
    password = await secrets_manager.get_secret(
        secret_path="kv/data/providers/webshare",
        secret_key="proxy_password",
    )
    if not username or not password:
        pytest.skip("Webshare proxy credentials not available in Vault")
    return f"http://{username}-rotate:{password}@p.webshare.io:80/"


@pytest.fixture(scope="module")
def browser_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    }
