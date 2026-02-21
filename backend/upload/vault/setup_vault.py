#!/usr/bin/env python3
"""
Vault Setup Script for the OpenMates Uploads Service (Local Vault)

This script sets up a local HashiCorp Vault instance on the uploads VM.
It is intentionally much simpler than the core Vault setup because the
uploads Vault only stores API credentials (S3, SightEngine) — no transit
engine, no user keys, no complex policies.

What this script does:
  1. Waits for the local Vault (dev mode) to become available
  2. Enables the KV v2 secrets engine
  3. Creates a read-only policy for the app-uploads service
  4. Creates a scoped API token with read-only KV access
  5. Migrates SECRET__* env vars into Vault KV (same convention as core)
  6. Writes the API token to /vault-data/api.token for app-uploads to read

The local Vault runs in dev mode (in-memory storage). If it restarts,
this setup script re-runs automatically and re-populates from env vars.
This is by design — the env vars are the source of truth, and this Vault
is a hardened runtime cache that protects secrets from process-level exploits.

Security model:
  - The app-uploads service token can ONLY read KV secrets (no write, no transit)
  - Even if app-uploads is fully compromised via a malicious file exploit,
    the attacker only gets read access to S3 + SightEngine credentials
  - They get ZERO access to the main Vault, Directus, or any user data
"""

import asyncio
import logging
import os
import stat
import sys

import httpx

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("uploads-vault-setup")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

VAULT_ADDR = os.environ.get("VAULT_ADDR", "http://vault:8200")
VAULT_TOKEN = os.environ.get("VAULT_TOKEN", "root")
API_TOKEN_FILE = "/vault-data/api.token"
SECRET_PREFIX = "SECRET__"


# ---------------------------------------------------------------------------
# Vault API helpers
# ---------------------------------------------------------------------------

async def vault_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    data: dict | None = None,
) -> dict | None:
    """Make a request to the local Vault API."""
    url = f"{VAULT_ADDR}/v1/{path}"
    headers = {"X-Vault-Token": VAULT_TOKEN}

    try:
        if method == "get":
            resp = await client.get(url, headers=headers)
        elif method == "post":
            resp = await client.post(url, headers=headers, json=data)
        else:
            resp = await getattr(client, method)(url, headers=headers, json=data)

        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json() if resp.text else {}
    except httpx.HTTPStatusError as e:
        logger.error(f"Vault HTTP error on {path}: {e.response.status_code} {e.response.text[:200]}")
        raise
    except Exception as e:
        logger.error(f"Vault request error on {path}: {e}")
        raise


async def wait_for_vault(client: httpx.AsyncClient, max_retries: int = 30, delay: float = 2.0) -> None:
    """Wait for the local Vault dev server to become available."""
    logger.info(f"Waiting for Vault at {VAULT_ADDR}...")
    for attempt in range(max_retries):
        try:
            resp = await client.get(f"{VAULT_ADDR}/v1/sys/health", timeout=5.0)
            logger.info(f"Vault health check: status={resp.status_code}")
            return  # Vault is up (200=initialized+unsealed in dev mode)
        except Exception as e:
            if attempt < max_retries - 1:
                logger.debug(f"Vault not ready (attempt {attempt + 1}/{max_retries}): {e}")
                await asyncio.sleep(delay)
            else:
                raise RuntimeError(f"Vault did not become available after {max_retries} attempts")


# ---------------------------------------------------------------------------
# KV engine setup
# ---------------------------------------------------------------------------

async def enable_kv_engine(client: httpx.AsyncClient) -> None:
    """Enable KV v2 secrets engine if not already enabled."""
    logger.info("Checking KV v2 secrets engine...")
    try:
        mounts = await vault_request(client, "get", "sys/mounts")
        if mounts and "kv/" in mounts.get("data", {}):
            logger.info("KV v2 engine already enabled")
            return

        logger.info("Enabling KV v2 secrets engine...")
        await vault_request(client, "post", "sys/mounts/kv", {
            "type": "kv",
            "options": {"version": "2"},
            "description": "KV store for uploads service API credentials",
        })
        logger.info("KV v2 engine enabled successfully")
    except Exception as e:
        logger.error(f"Failed to enable KV engine: {e}")
        raise


# ---------------------------------------------------------------------------
# Policy creation
# ---------------------------------------------------------------------------

async def create_uploads_policy(client: httpx.AsyncClient) -> None:
    """
    Create a read-only policy for the app-uploads service.

    This policy only allows reading from kv/data/providers/* paths.
    The app-uploads service cannot write secrets, manage keys, or do
    anything beyond fetching its runtime credentials.
    """
    logger.info("Creating uploads-service read-only policy...")

    policy_hcl = """
    # Uploads service policy — READ-ONLY access to provider credentials.
    # This is the ONLY policy assigned to the app-uploads token.

    # Allow reading provider secrets (S3, SightEngine, future keys)
    path "kv/data/providers/*" {
      capabilities = ["read"]
    }

    # Allow listing provider paths (needed for initialization checks)
    path "kv/metadata/providers/*" {
      capabilities = ["list", "read"]
    }

    # Allow token self-lookup (for health checks)
    path "auth/token/lookup-self" {
      capabilities = ["read"]
    }
    """

    await vault_request(client, "post", "sys/policies/acl/uploads-service", {
        "policy": policy_hcl,
    })
    logger.info("uploads-service policy created/updated")


# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------

async def create_uploads_token(client: httpx.AsyncClient) -> str:
    """
    Create a scoped token for the app-uploads service.

    The token has:
    - uploads-service policy only (read-only KV access)
    - 1-year TTL (re-created on every stack restart anyway since dev mode)
    - Renewable for safety
    """
    logger.info("Creating uploads-service API token...")

    result = await vault_request(client, "post", "auth/token/create", {
        "policies": ["uploads-service"],
        "display_name": "uploads-service-token",
        "ttl": "8760h",  # 1 year
        "renewable": True,
    })

    if not result or "auth" not in result:
        raise RuntimeError("Failed to create uploads service token: invalid response")

    token = result["auth"]["client_token"]
    masked = f"{token[:4]}...{token[-4:]}" if len(token) >= 8 else "****"
    logger.info(f"Uploads service token created: {masked}")
    return token


def save_api_token(token: str) -> None:
    """Save the API token to the shared volume for app-uploads to read."""
    os.makedirs(os.path.dirname(API_TOKEN_FILE), exist_ok=True)
    with open(API_TOKEN_FILE, "w") as f:
        f.write(token)
    # 644 permissions — app-uploads container needs to read this
    os.chmod(API_TOKEN_FILE, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    logger.info(f"API token saved to {API_TOKEN_FILE}")


# ---------------------------------------------------------------------------
# Secret migration (SECRET__PROVIDER__KEY → kv/data/providers/{provider})
# ---------------------------------------------------------------------------

def find_secrets_in_env() -> dict[str, tuple[str, str, str]]:
    """
    Parse SECRET__PROVIDER__KEY env vars into Vault paths.

    Returns dict of env_var_name → (vault_path, vault_key, value).
    Uses the same naming convention as the core Vault setup.
    """
    secrets = {}
    for env_var, value in os.environ.items():
        if not env_var.startswith(SECRET_PREFIX):
            continue
        if not value or not value.strip() or value == "IMPORTED_TO_VAULT":
            continue

        remainder = env_var[len(SECRET_PREFIX):]
        parts = remainder.split("__", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            logger.warning(f"Skipping unparseable env var: {env_var}")
            continue

        provider = parts[0].lower()
        key = parts[1].lower()
        vault_path = f"kv/data/providers/{provider}"
        secrets[env_var] = (vault_path, key, value)

    return secrets


async def migrate_secrets(client: httpx.AsyncClient) -> int:
    """
    Write SECRET__* env vars to Vault KV.

    Merges with existing data at each path to avoid overwriting
    secrets from other env vars targeting the same provider path.
    Returns the number of secrets successfully written.
    """
    env_secrets = find_secrets_in_env()
    if not env_secrets:
        logger.info("No SECRET__* env vars found to migrate")
        return 0

    logger.info(f"Found {len(env_secrets)} secrets to migrate to Vault KV")

    # Group by vault_path to do fewer writes
    by_path: dict[str, dict[str, str]] = {}
    for env_var, (vault_path, key, value) in env_secrets.items():
        if vault_path not in by_path:
            by_path[vault_path] = {}
        by_path[vault_path][key] = value

    count = 0
    for vault_path, kv_data in by_path.items():
        try:
            # Read existing data at this path (merge, don't overwrite)
            existing = {}
            try:
                resp = await vault_request(client, "get", vault_path)
                if resp and "data" in resp and "data" in resp["data"]:
                    existing = resp["data"]["data"]
            except Exception:
                pass  # Path doesn't exist yet, that's fine

            # Merge new secrets into existing
            existing.update(kv_data)
            await vault_request(client, "post", vault_path, {"data": existing})

            for key in kv_data:
                logger.info(f"  Wrote secret '{key}' to {vault_path}")
                count += 1

        except Exception as e:
            logger.error(f"Failed to write secrets to {vault_path}: {e}", exc_info=True)

    return count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    """Main setup routine for the uploads local Vault."""
    logger.info("=" * 60)
    logger.info("OpenMates Uploads — Local Vault Setup")
    logger.info("=" * 60)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Wait for Vault
        await wait_for_vault(client)

        # 2. Enable KV v2 engine
        await enable_kv_engine(client)

        # 3. Create read-only policy for uploads service
        await create_uploads_policy(client)

        # 4. Create scoped API token
        token = await create_uploads_token(client)
        save_api_token(token)

        # 5. Migrate secrets from env vars to Vault KV
        migrated = await migrate_secrets(client)

        logger.info("=" * 60)
        logger.info("Vault Setup Complete")
        logger.info(f"  Secrets migrated: {migrated}")
        logger.info(f"  API token file: {API_TOKEN_FILE}")
        logger.info("  Policy: uploads-service (read-only KV)")
        logger.info("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Vault setup failed: {e}", exc_info=True)
        sys.exit(1)
