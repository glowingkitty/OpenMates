#!/usr/bin/env python3
"""
Vault Setup Script for the OpenMates Upload Server.

Mirrors the core API vault-setup pattern:
  - Initializes Vault on first run (saves unseal key + root token to persistent volume)
  - Auto-unseals on subsequent restarts using the saved unseal key
  - Creates a read-only KV policy + scoped API token (saved to /app/data/api.token)
  - Migrates SECRET__* env vars into Vault KV on first run
  - Skips already-migrated secrets (IMPORTED_TO_VAULT sentinel or migration flag in Vault)

After first successful run, replace SECRET__* values in .env with IMPORTED_TO_VAULT
(or remove them). The vault-data Docker volume keeps secrets across container restarts.
"""

import asyncio
import logging
import os
import stat
import sys
from typing import Optional

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

VAULT_ADDR      = os.environ.get("VAULT_ADDR", "http://vault:8200")
VAULT_TOKEN_ENV = os.environ.get("VAULT_TOKEN", "")  # Only used as fallback

DATA_DIR        = "/app/data"
UNSEAL_KEY_FILE = f"{DATA_DIR}/unseal.key"
ROOT_TOKEN_FILE = f"{DATA_DIR}/root.token"
API_TOKEN_FILE  = f"{DATA_DIR}/api.token"

SECRET_PREFIX              = "SECRET__"
MIGRATION_FLAG_PATH        = "kv/data/system_flags/migration_status"
MIGRATION_FLAG_KEY         = "initial_env_secrets_migrated"
AUTO_UNSEAL                = os.environ.get("VAULT_AUTO_UNSEAL", "true").lower() == "true"

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

async def vault_get(client: httpx.AsyncClient, path: str, token: str) -> Optional[dict]:
    url = f"{VAULT_ADDR}/v1/{path}"
    try:
        resp = await client.get(url, headers={"X-Vault-Token": token}, timeout=10.0)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json() if resp.text else {}
    except httpx.HTTPStatusError as e:
        logger.error(f"GET {path}: {e.response.status_code} {e.response.text[:200]}")
        raise


async def vault_post(client: httpx.AsyncClient, path: str, token: str, data: dict) -> Optional[dict]:
    url = f"{VAULT_ADDR}/v1/{path}"
    try:
        resp = await client.post(url, headers={"X-Vault-Token": token}, json=data, timeout=10.0)
        resp.raise_for_status()
        return resp.json() if resp.text else {}
    except httpx.HTTPStatusError as e:
        logger.error(f"POST {path}: {e.response.status_code} {e.response.text[:200]}")
        raise


async def wait_for_vault(client: httpx.AsyncClient, max_retries: int = 60, delay: float = 3.0) -> dict:
    """Wait for Vault to respond. Returns the health/init status JSON."""
    logger.info(f"Waiting for Vault at {VAULT_ADDR}...")
    for attempt in range(max_retries):
        try:
            resp = await client.get(f"{VAULT_ADDR}/v1/sys/health", timeout=5.0)
            # health returns non-200 for sealed/uninit but still valid JSON
            data = resp.json()
            logger.info(f"Vault health: initialized={data.get('initialized')}, sealed={data.get('sealed')}")
            return data
        except Exception as e:
            if attempt < max_retries - 1:
                logger.debug(f"Vault not ready ({attempt+1}/{max_retries}): {e}")
                await asyncio.sleep(delay)
            else:
                raise RuntimeError(f"Vault did not become available after {max_retries} attempts")
    return {}  # unreachable

# ---------------------------------------------------------------------------
# Persistent file helpers
# ---------------------------------------------------------------------------

def _write_file(path: str, content: str, mode: int) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, mode)


def _read_file(path: str) -> Optional[str]:
    try:
        with open(path, "r") as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def save_unseal_key(key: str) -> None:
    if os.path.exists(UNSEAL_KEY_FILE):
        logger.info("Unseal key already saved, not overwriting")
        return
    _write_file(UNSEAL_KEY_FILE, key, stat.S_IRUSR | stat.S_IWUSR)  # 600
    logger.info(f"Unseal key saved to {UNSEAL_KEY_FILE}")


def save_root_token(token: str) -> None:
    _write_file(ROOT_TOKEN_FILE, token, stat.S_IRUSR | stat.S_IWUSR)  # 600
    logger.info(f"Root token saved to {ROOT_TOKEN_FILE}")


def save_api_token(token: str) -> None:
    _write_file(API_TOKEN_FILE, token, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)  # 644
    logger.info(f"API token saved to {API_TOKEN_FILE}")

# ---------------------------------------------------------------------------
# Vault operations
# ---------------------------------------------------------------------------

async def initialize_vault(client: httpx.AsyncClient) -> str:
    """Initialize Vault and return the root token. Saves unseal key and root token to disk."""
    logger.info("Initializing Vault for the first time...")
    resp = await client.post(
        f"{VAULT_ADDR}/v1/sys/init",
        json={"secret_shares": 1, "secret_threshold": 1},
        timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()
    root_token = data["root_token"]
    unseal_key  = data["keys"][0]

    save_unseal_key(unseal_key)
    save_root_token(root_token)

    print("\n" + "=" * 72, flush=True)
    print("VAULT INITIALIZED — SAVE THESE CREDENTIALS OFFLINE NOW", flush=True)
    print("=" * 72, flush=True)
    print(f"ROOT TOKEN : {root_token}", flush=True)
    print(f"UNSEAL KEY : {unseal_key}", flush=True)
    print("=" * 72, flush=True)
    print("You will NOT see these again. Store them securely offline.", flush=True)
    print("=" * 72 + "\n", flush=True)

    return root_token


async def unseal_vault(client: httpx.AsyncClient) -> None:
    """Unseal Vault using the saved unseal key."""
    unseal_key = _read_file(UNSEAL_KEY_FILE)
    if not unseal_key:
        logger.error("No unseal key found — cannot auto-unseal. Unseal manually:")
        logger.error("  docker exec uploads-vault vault operator unseal <KEY>")
        raise RuntimeError("Unseal key not found")
    resp = await client.post(
        f"{VAULT_ADDR}/v1/sys/unseal",
        json={"key": unseal_key},
        timeout=10.0,
    )
    resp.raise_for_status()
    result = resp.json()
    if result.get("sealed"):
        raise RuntimeError("Vault still sealed after unseal attempt")
    logger.info("Vault unsealed successfully")


async def enable_kv_engine(client: httpx.AsyncClient, token: str) -> None:
    mounts = await vault_get(client, "sys/mounts", token)
    if mounts and "kv/" in mounts.get("data", {}):
        logger.info("KV v2 engine already enabled")
        return
    await vault_post(client, "sys/mounts/kv", token, {
        "type": "kv",
        "options": {"version": "2"},
        "description": "KV store for upload service API credentials",
    })
    logger.info("KV v2 engine enabled")


async def create_policy(client: httpx.AsyncClient, token: str) -> None:
    policy_hcl = """
    # uploads-service policy — READ-ONLY access to provider credentials.

    path "kv/data/providers/*" {
      capabilities = ["read"]
    }

    path "kv/metadata/providers/*" {
      capabilities = ["list", "read"]
    }

    path "auth/token/lookup-self" {
      capabilities = ["read"]
    }
    """
    await vault_post(client, "sys/policies/acl/uploads-service", token, {"policy": policy_hcl})
    logger.info("uploads-service policy created/updated")


async def create_or_reuse_api_token(client: httpx.AsyncClient, root_token: str) -> str:
    """Return an existing valid api token or create a new one."""
    existing = _read_file(API_TOKEN_FILE)
    if existing:
        # Validate it still works
        try:
            resp = await vault_get(client, "auth/token/lookup-self", existing)
            if resp and resp.get("data", {}).get("ttl", 0) > 0:
                policies = resp["data"].get("policies", [])
                if "uploads-service" in policies:
                    logger.info("Existing API token is valid, reusing it")
                    return existing
        except Exception:
            pass
        logger.info("Existing API token invalid or expired, creating a new one")

    result = await vault_post(client, "auth/token/create", root_token, {
        "policies": ["uploads-service"],
        "display_name": "uploads-service-token",
        "ttl": "8760h",
        "renewable": True,
    })
    if not result or "auth" not in result:
        raise RuntimeError(f"Unexpected response from Vault token/create: {result!r}")
    token = result["auth"]["client_token"]
    masked = f"{token[:4]}...{token[-4:]}"
    logger.info(f"API token created: {masked}")
    save_api_token(token)
    return token


# ---------------------------------------------------------------------------
# Secret migration
# ---------------------------------------------------------------------------

def find_secrets_in_env() -> dict[str, tuple[str, str]]:
    """
    Parse SECRET__PROVIDER__KEY env vars.
    Returns {env_var: (vault_path, vault_key)}, skipping IMPORTED_TO_VAULT values.
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
        vault_path = f"kv/data/providers/{parts[0].lower()}"
        vault_key  = parts[1].lower()
        secrets[env_var] = (vault_path, vault_key)
    return secrets


async def check_migration_done(client: httpx.AsyncClient, token: str) -> bool:
    resp = await vault_get(client, MIGRATION_FLAG_PATH, token)
    if resp and resp.get("data", {}).get("data", {}).get(MIGRATION_FLAG_KEY) is True:
        return True
    return False


async def migrate_secrets(client: httpx.AsyncClient, token: str) -> None:
    """Write SECRET__* env vars to Vault KV. Idempotent — merges with existing data."""
    env_secrets = find_secrets_in_env()
    if not env_secrets:
        logger.info("No SECRET__* env vars to migrate (all already IMPORTED_TO_VAULT or none set)")
        return

    # Group by vault_path
    by_path: dict[str, dict[str, str]] = {}
    for env_var, (vault_path, vault_key) in env_secrets.items():
        by_path.setdefault(vault_path, {})[vault_key] = os.environ[env_var]

    for vault_path, kv_data in by_path.items():
        # Merge with existing
        existing: dict = {}
        try:
            resp = await vault_get(client, vault_path, token)
            if resp and "data" in resp and "data" in resp["data"]:
                existing = resp["data"]["data"]
        except Exception:
            pass
        existing.update(kv_data)
        await vault_post(client, vault_path, token, {"data": existing})
        for key in kv_data:
            logger.info(f"  Wrote '{key}' to {vault_path}")

    logger.info(f"Migrated {sum(len(v) for v in by_path.values())} secrets to Vault KV")


async def set_migration_flag(client: httpx.AsyncClient, token: str) -> None:
    await vault_post(client, MIGRATION_FLAG_PATH, token, {"data": {MIGRATION_FLAG_KEY: True}})
    logger.info("Migration flag set in Vault KV")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    logger.info("=" * 60)
    logger.info("OpenMates Upload Server — Vault Setup")
    logger.info("=" * 60)

    async with httpx.AsyncClient(timeout=30.0) as client:

        # 1. Wait for Vault
        health = await wait_for_vault(client)
        initialized = health.get("initialized", False)
        sealed       = health.get("sealed", True)

        # 2. Initialize if needed (first ever boot)
        if not initialized:
            root_token = await initialize_vault(client)
            # Vault auto-unseals during init
        else:
            # Load saved root token
            root_token = _read_file(ROOT_TOKEN_FILE)
            if not root_token:
                logger.error("Vault is initialized but no saved root token found.")
                logger.error(f"Ensure {ROOT_TOKEN_FILE} exists on the vault-setup-data volume.")
                sys.exit(1)

            # Unseal if sealed
            if sealed:
                if not AUTO_UNSEAL:
                    logger.warning("AUTO_UNSEAL=false — skipping auto-unseal")
                else:
                    await unseal_vault(client)

        # 3. Enable KV engine
        await enable_kv_engine(client, root_token)

        # 4. Create policy
        await create_policy(client, root_token)

        # 5. Create or reuse API token
        await create_or_reuse_api_token(client, root_token)

        # 6. Migrate secrets (first run only — subsequent runs skip via migration flag)
        already_migrated = await check_migration_done(client, root_token)
        if already_migrated:
            logger.info("Secrets already migrated to Vault (migration flag found)")
            # Still sync any new SECRET__* vars added since last run
            await migrate_secrets(client, root_token)
        else:
            await migrate_secrets(client, root_token)
            await set_migration_flag(client, root_token)

    logger.info("=" * 60)
    logger.info("Vault Setup Complete")
    logger.info(f"  API token: {API_TOKEN_FILE}")
    logger.info(f"  Unseal key: {UNSEAL_KEY_FILE}")
    logger.info(f"  Root token: {ROOT_TOKEN_FILE}")
    logger.info("=" * 60)
    logger.info("After verifying secrets are in Vault, set SECRET__* values")
    logger.info("in .env to IMPORTED_TO_VAULT to prevent re-processing.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Vault setup failed: {e}", exc_info=True)
        sys.exit(1)
