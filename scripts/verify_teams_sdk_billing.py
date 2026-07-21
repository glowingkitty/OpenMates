#!/usr/bin/env python3
"""Verify Teams SDK billing against the real dev API.

This script is a live gate for Teams V1 SDK parity. It uses the existing CLI
test-account login only to create a disposable team and API key, then exercises
the npm and pip SDK team bank-transfer methods over the public API. It prints
only structured status output and never prints the API key.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from sdk_cli_parity_live_smoke import _approve_pending_key_devices, _is_device_approval_error
import verify_teams_cli_common
from verify_teams_cli_common import CLI_DIR, ROOT, VerificationError, cleanup_team, create_test_team, require, run_cli_json, setup_cli


def run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None, timeout: int = 180, emit_error: bool = True) -> str:
    result = subprocess.run(command, cwd=cwd, env=env or os.environ.copy(), text=True, capture_output=True, check=False, timeout=timeout)
    if result.returncode != 0:
        if emit_error:
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
        raise VerificationError(
            f"Command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result.stdout


def create_api_key() -> tuple[str, str]:
    result = run_cli_json(["settings", "developers", "api-keys", "create", "teams-sdk-billing-verifier", "--yes"], timeout=120)
    key = result.get("key") if isinstance(result.get("key"), dict) else {}
    key_id = str(result.get("id") or result.get("key_id") or key.get("id") or "")
    api_key = str(result.get("api_key") or result.get("key") or "")
    require(bool(key_id), f"API key create response did not include key id: {result}")
    require(api_key.startswith("om_") or len(api_key) > 20, "API key create response did not include a usable key")
    return key_id, api_key


def revoke_api_key(key_id: str) -> None:
    subprocess.run(
        ["node", "dist/cli.js", "settings", "developers", "api-keys", "revoke", key_id, "--yes", "--json"],
        cwd=CLI_DIR,
        env=verify_teams_cli_common.RUN_ENV,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )


def verify_npm_sdk(api_url: str, api_key: str, team_id: str) -> None:
    sdk_path = (CLI_DIR / "dist" / "index.js").as_uri()
    code = f"""
import {{ OpenMates }} from {json.dumps(sdk_path)};
const client = new OpenMates({{ apiKey: process.env.OPENMATES_API_KEY, apiUrl: process.env.OPENMATES_API_URL, deviceId: 'teams-sdk-npm' }});
const teamId = process.env.OPENMATES_TEAM_ID;
const order = await client.teams.createBankTransferOrder(teamId, 110000, {{ emailEncryptionKey: 'sdk-email-key' }});
if (!order.order_id || !order.reference) throw new Error('npm SDK order missing id/reference');
const status = await client.teams.bankTransferStatus(teamId, order.order_id);
if (status.status !== 'pending') throw new Error(`npm SDK unexpected order status: ${{status.status}}`);
const listed = await client.teams.listBankTransferOrders(teamId);
if (!Array.isArray(listed.orders) || !listed.orders.some((item) => item.order_id === order.order_id)) {{
  throw new Error('npm SDK order was not listed');
}}
"""
    env = {**os.environ, "OPENMATES_API_KEY": api_key, "OPENMATES_API_URL": api_url, "OPENMATES_TEAM_ID": team_id}
    run(["node", "--input-type=module", "-e", code], cwd=ROOT, env=env, timeout=180, emit_error=False)


def verify_pip_sdk(api_url: str, api_key: str, team_id: str) -> None:
    code = """
from openmates import OpenMates
import os

client = OpenMates(api_key=os.environ['OPENMATES_API_KEY'], api_url=os.environ['OPENMATES_API_URL'], device_id='teams-sdk-pip')
team_id = os.environ['OPENMATES_TEAM_ID']
order = client.teams.create_bank_transfer_order(team_id, 110000, email_encryption_key='sdk-email-key')
if not order.get('order_id') or not order.get('reference'):
    raise SystemExit('pip SDK order missing id/reference')
status = client.teams.bank_transfer_status(team_id, order['order_id'])
if status.get('status') != 'pending':
    raise SystemExit(f"pip SDK unexpected order status: {status.get('status')}")
listed = client.teams.list_bank_transfer_orders(team_id)
if order['order_id'] not in {item.get('order_id') for item in listed.get('orders', [])}:
    raise SystemExit('pip SDK order was not listed')
"""
    env = {
        **os.environ,
        "OPENMATES_API_KEY": api_key,
        "OPENMATES_API_URL": api_url,
        "OPENMATES_TEAM_ID": team_id,
        "PYTHONPATH": str(ROOT / "packages" / "openmates-python"),
    }
    run(["python3", "-c", code], cwd=ROOT, env=env, timeout=180, emit_error=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Teams SDK billing flow against a real API.")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000", help="Real API URL to test against")
    parser.add_argument("--skip-build", action="store_true", help="Do not rebuild the npm CLI package before running")
    args = parser.parse_args()
    original_home = os.environ.get("HOME")
    try:
        with tempfile.TemporaryDirectory(prefix="openmates-teams-sdk-") as home:
            os.environ["HOME"] = home
            verify_teams_cli_common.RUN_ENV = {
                **os.environ,
                "HOME": home,
                "XDG_CONFIG_HOME": str(Path(home) / ".config"),
            }
            setup_cli(args.api_url, args.skip_build)
            team_id = create_test_team("SDK Teams billing")
            key_id = ""
            try:
                key_id, api_key = create_api_key()
                try:
                    verify_npm_sdk(args.api_url, api_key, team_id)
                except VerificationError as exc:
                    if not _is_device_approval_error(exc):
                        raise
                    approved = _approve_pending_key_devices(args.api_url, key_id, {"npm"})
                    require(bool(approved), "No pending npm SDK device was available to approve")
                    verify_npm_sdk(args.api_url, api_key, team_id)
                try:
                    verify_pip_sdk(args.api_url, api_key, team_id)
                except VerificationError as exc:
                    if not _is_device_approval_error(exc):
                        raise
                    approved = _approve_pending_key_devices(args.api_url, key_id, {"pip"})
                    require(bool(approved), "No pending pip SDK device was available to approve")
                    verify_pip_sdk(args.api_url, api_key, team_id)
            finally:
                if key_id:
                    revoke_api_key(key_id)
                cleanup_team(team_id)
        print(json.dumps({"scenario": "sdk-billing", "api_url": args.api_url, "status": "passed", "team_id_prefix": team_id[:8]}, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001 - structured verifier output for CI/dev logs.
        print(json.dumps({"scenario": "sdk-billing", "api_url": args.api_url, "status": "failed", "error": str(exc)}, indent=2))
        return 1
    finally:
        if original_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = original_home


if __name__ == "__main__":
    raise SystemExit(main())
