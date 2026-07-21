#!/usr/bin/env python3
# scripts/api_tests/test_revolut_business_api.py
#
# Manual Revolut Business Sandbox probe for the Finance connected-account provider.
# The script loads credentials from process env or a local .env file, never prints
# secret values, and only calls read-only token/accounts/transactions surfaces.
#
# Spec: docs/specs/finance-check-accounts-v1/spec.yml

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.shared.providers.revolut_business.client import (  # noqa: E402
    REVOLUT_BUSINESS_SANDBOX_API_BASE_URL,
    RevolutBusinessClient,
)
from backend.shared.providers.revolut_business.oauth import (  # noqa: E402
    RevolutBusinessTokenExchangeError,
    exchange_revolut_business_refresh_token,
)


DEFAULT_ENV_FILE = Path(".env")
DEFAULT_TRANSACTION_COUNT = 10
REQUIRED_REFRESH_ENV_NAMES = [
    "REVOLUT_BUSINESS_SANDBOX_REFRESH_TOKEN",
    "REVOLUT_BUSINESS_REFRESH_TOKEN",
]
REQUIRED_CLIENT_ID_ENV_NAMES = [
    "REVOLUT_BUSINESS_SANDBOX_CLIENT_ID",
    "REVOLUT_BUSINESS_CLIENT_ID",
]
PRIVATE_KEY_ENV_NAMES = [
    "REVOLUT_BUSINESS_SANDBOX_PRIVATE_KEY_PEM",
    "REVOLUT_BUSINESS_PRIVATE_KEY_PEM",
]
PRIVATE_KEY_FILE_ENV_NAMES = [
    "REVOLUT_BUSINESS_SANDBOX_PRIVATE_KEY_FILE",
    "REVOLUT_BUSINESS_PRIVATE_KEY_FILE",
]
CLIENT_ASSERTION_ENV_NAMES = [
    "REVOLUT_BUSINESS_SANDBOX_CLIENT_ASSERTION",
    "REVOLUT_BUSINESS_CLIENT_ASSERTION",
]
ACCESS_TOKEN_ENV_NAMES = [
    "REVOLUT_BUSINESS_SANDBOX_ACCESS_TOKEN",
    "REVOLUT_BUSINESS_ACCESS_TOKEN",
]


class MissingRevolutCredentials(RuntimeError):
    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__("Missing Revolut Sandbox credentials: " + ", ".join(missing))


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value.replace("\\n", "\n")


def first_env(names: list[str]) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    return ""


def read_private_key_pem() -> str:
    private_key = first_env(PRIVATE_KEY_ENV_NAMES)
    if private_key:
        return private_key
    private_key_file = first_env(PRIVATE_KEY_FILE_ENV_NAMES)
    if not private_key_file:
        return ""
    return Path(private_key_file).expanduser().read_text(encoding="utf-8").strip()


def build_refresh_envelope() -> tuple[str, dict[str, Any]]:
    refresh_token = first_env(REQUIRED_REFRESH_ENV_NAMES)
    client_id = first_env(REQUIRED_CLIENT_ID_ENV_NAMES)
    client_assertion = first_env(CLIENT_ASSERTION_ENV_NAMES)
    private_key_pem = read_private_key_pem()
    missing: list[str] = []
    if not refresh_token:
        missing.append("one of " + "/".join(REQUIRED_REFRESH_ENV_NAMES))
    if not client_id:
        missing.append("one of " + "/".join(REQUIRED_CLIENT_ID_ENV_NAMES))
    if not client_assertion and not private_key_pem:
        missing.append(
            "one of "
            + "/".join(CLIENT_ASSERTION_ENV_NAMES + PRIVATE_KEY_ENV_NAMES + PRIVATE_KEY_FILE_ENV_NAMES)
        )
    if missing:
        raise MissingRevolutCredentials(missing)

    envelope: dict[str, Any] = {
        "provider": "revolut_business",
        "environment": "sandbox",
        "client_id": client_id,
        "refresh_token": refresh_token,
    }
    if client_assertion:
        envelope["client_assertion"] = client_assertion
    else:
        envelope["private_key_pem"] = private_key_pem
    return refresh_token, envelope


async def resolve_access_token() -> tuple[str, dict[str, Any]]:
    access_token = first_env(ACCESS_TOKEN_ENV_NAMES)
    if access_token:
        return access_token, {"source": "access_token_env", "rotated_refresh_token": False}

    refresh_token, envelope = build_refresh_envelope()
    started_at = time.time()
    result = await exchange_revolut_business_refresh_token(
        refresh_token,
        {"refresh_token_envelope": envelope},
    )
    access_token = str(result.get("access_token") or "")
    if not access_token:
        raise RevolutBusinessTokenExchangeError("Revolut token exchange did not return an access token")
    return access_token, {
        "source": "refresh_token_exchange",
        "duration_seconds": round(time.time() - started_at, 2),
        "expires_in": result.get("expires_in"),
        "rotated_refresh_token": bool(result.get("rotated_refresh_token_bundle")),
    }


async def test_token_exchange() -> dict[str, Any]:
    refresh_token, envelope = build_refresh_envelope()
    started_at = time.time()
    result = await exchange_revolut_business_refresh_token(
        refresh_token,
        {"refresh_token_envelope": envelope},
    )
    access_token = str(result.get("access_token") or "")
    if not access_token:
        raise RevolutBusinessTokenExchangeError("Revolut token exchange did not return an access token")
    return {
        "status": "pass",
        "access_token_present": bool(access_token),
        "source": "refresh_token_exchange",
        "duration_seconds": round(time.time() - started_at, 2),
        "expires_in": result.get("expires_in"),
        "rotated_refresh_token": bool(result.get("rotated_refresh_token_bundle")),
    }


async def test_list_accounts() -> dict[str, Any]:
    access_token, token_metadata = await resolve_access_token()
    started_at = time.time()
    client = RevolutBusinessClient(
        access_token=access_token,
        base_url=REVOLUT_BUSINESS_SANDBOX_API_BASE_URL,
    )
    accounts = await client.list_accounts()
    return {
        "status": "pass",
        "duration_seconds": round(time.time() - started_at, 2),
        "token_source": token_metadata["source"],
        "account_count": len(accounts),
        "accounts": [
            {
                "id_prefix": account.id[:8],
                "name": account.name,
                "currency": account.currency,
                "state": account.state,
                "has_balance": account.balance is not None,
            }
            for account in accounts[:5]
        ],
    }


async def test_list_transactions() -> dict[str, Any]:
    access_token, token_metadata = await resolve_access_token()
    started_at = time.time()
    client = RevolutBusinessClient(
        access_token=access_token,
        base_url=REVOLUT_BUSINESS_SANDBOX_API_BASE_URL,
    )
    accounts = await client.list_accounts()
    account_id = accounts[0].id if accounts else None
    transactions = await client.list_transactions(account_id=account_id, count=DEFAULT_TRANSACTION_COUNT)
    return {
        "status": "pass",
        "duration_seconds": round(time.time() - started_at, 2),
        "token_source": token_metadata["source"],
        "account_id_prefix": account_id[:8] if account_id else None,
        "transaction_count": len(transactions),
        "transactions": [
            {
                "id_prefix": transaction.id[:8],
                "account_id_prefix": transaction.account_id[:8],
                "created_at": transaction.created_at,
                "amount": transaction.amount,
                "currency": transaction.currency,
                "state": transaction.state,
            }
            for transaction in transactions[:5]
        ],
    }


TESTS = {
    "token_exchange": test_token_exchange,
    "list_accounts": test_list_accounts,
    "list_transactions": test_list_transactions,
}


async def run(args: argparse.Namespace) -> None:
    load_env_file(Path(args.env_file))
    if args.list:
        for name in sorted(TESTS):
            print(name)
        return

    selected = TESTS if args.test == "all" else {args.test: TESTS[args.test]}
    results: dict[str, Any] = {}
    for name, test_fn in selected.items():
        started_at = time.time()
        try:
            results[name] = await test_fn()
        except MissingRevolutCredentials as exc:
            results[name] = {"status": "skip", "missing": exc.missing}
        except Exception as exc:
            results[name] = {
                "status": "fail",
                "duration_seconds": round(time.time() - started_at, 2),
                "error": f"{type(exc).__name__}: {exc}",
            }

    print(json.dumps(results, indent=2, sort_keys=True))
    failed = [name for name, result in results.items() if result.get("status") == "fail"]
    skipped = [name for name, result in results.items() if result.get("status") == "skip"]
    if failed:
        sys.exit(1)
    if skipped and not args.allow_skip:
        sys.exit(2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe Revolut Business Sandbox read-only Finance APIs")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="Optional .env file to load before reading process env")
    parser.add_argument("--test", choices=["all", *sorted(TESTS)], default="all", help="Test to run")
    parser.add_argument("--list", action="store_true", help="List available tests")
    parser.add_argument("--allow-skip", action="store_true", help="Exit 0 when credentials are missing")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
