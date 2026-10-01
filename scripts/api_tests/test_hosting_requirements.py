#!/usr/bin/env python3
# contract-test-file: tooling
"""Dev-only real Jev probe for Hosting domain relevance and quote requirements.

Run after deploying the Hosting skill, with an existing test-account .env:
  python3 scripts/api_tests/test_hosting_requirements.py \
    --env-file /path/to/canonical/.env --revision <deployed-sha> \
    --output /private/path/hosting-requirements.json

The probe uses one grouped search and requires relevance_applied=true. A fallback
ranking result is a failure, even when Gandi returns otherwise valid domains.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import time
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
CLI_DIST = ROOT / "frontend/packages/openmates-cli/dist/cli.js"
SDK_ENTRY = "./frontend/packages/openmates-cli/dist/index.js"
LOGIN_HELPER = ROOT / "scripts/openmates_cli_test_account.mjs"
DEFAULT_API_URL = "https://api.dev.openmates.org"
REQUIREMENTS = "Only names related to cedarcomet; prefer lower evidenced renewal prices and avoid premium domains."
ACCOUNT_KEY = re.compile(r"^OPENMATES_TEST_ACCOUNT(?:_\d+)?_(?:EMAIL|PASSWORD|OTP_KEY)$")
DOMAIN_SUFFIXES = (".com", ".net")


class ProbeFailure(RuntimeError):
    """Safe failure message; private subprocess output stays in memory."""


def _test_account_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ProbeFailure("Test-account env file was not found")
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = (part.strip() for part in line.split("=", 1))
        if ACCOUNT_KEY.fullmatch(name) or name == "OPENMATES_TEST_ACCOUNT_SOURCE_SLOT":
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[name] = value
    if not any(name.endswith("_EMAIL") for name in values) or not any(name.endswith("_PASSWORD") for name in values):
        raise ProbeFailure("Test-account email and password are required")
    return values


def _totp_code(account_env: dict[str, str], login_slot: str) -> str:
    # Auto login can skip unusable configured accounts. Use its confirmed slot.
    if login_slot != "base" and not re.fullmatch(r"(?:[1-9]|1[0-9]|20)", login_slot):
        raise ProbeFailure("Test-account login returned an invalid slot")
    slot = "" if login_slot == "base" else login_slot
    secret = account_env.get(f"OPENMATES_TEST_ACCOUNT_{slot}_OTP_KEY") if slot else None
    secret = secret or account_env.get("OPENMATES_TEST_ACCOUNT_OTP_KEY")
    if not secret:
        raise ProbeFailure("Test-account OTP key is required for sensitive API-key creation")
    normalized = secret.strip().upper().replace(" ", "")
    try:
        key = base64.b32decode(normalized + "=" * (-len(normalized) % 8), casefold=True)
    except ValueError as exc:
        raise ProbeFailure("Test-account OTP key is invalid") from exc
    counter = int(time.time()) // 30
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def _run(command: list[str], *, env: dict[str, str], label: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command, cwd=ROOT, env=env, text=True, capture_output=True,
            check=False, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProbeFailure(f"{label} could not complete ({type(exc).__name__})") from None
    return result


def _node_key_action(env: dict[str, str], action: str, payload: dict[str, Any]) -> dict[str, Any]:
    script = f"""
      import {{ OpenMatesClient }} from '{SDK_ENTRY}';
      import {{ platform, arch }} from 'node:os';
      const client = new OpenMatesClient({{ apiUrl: process.env.OPENMATES_API_URL }});
      const payload = JSON.parse(process.env.OPENMATES_HOSTING_KEY_ACTION_PAYLOAD);
      if (process.env.OPENMATES_HOSTING_KEY_ACTION === 'create') {{
        await client.verifyTotpForCurrentSession(process.env.OPENMATES_HOSTING_TOTP_CODE);
        const result = await client.createApiKey(payload);
        console.log(JSON.stringify({{ apiKey: result.api_key, keyId: result.key?.id }}));
      }} else if (process.env.OPENMATES_HOSTING_KEY_ACTION === 'approve-device') {{
        const result = await client.settingsGet('api-key-devices');
        let approved = 0;
        const cliDeviceId = 'cli:' + platform() + ':' + arch();
        for (const device of result.devices || []) {{
          if (device.api_key_id !== payload.id || device.approved_at ||
              device.access_type !== 'cli' || device.machine_identifier !== cliDeviceId) continue;
          await client.settingsPost(`api-key-devices/${{device.id}}/approve`, {{}});
          approved += 1;
        }}
        console.log(JSON.stringify({{ approved }}));
      }} else if (process.env.OPENMATES_HOSTING_KEY_ACTION === 'revoke') {{
        await client.revokeApiKey(payload.id);
        console.log(JSON.stringify({{ revoked: true }}));
      }} else {{
        throw new Error('Unsupported key action');
      }}
    """
    child_env = {**env, "OPENMATES_HOSTING_KEY_ACTION": action,
                 "OPENMATES_HOSTING_KEY_ACTION_PAYLOAD": json.dumps(payload)}
    result = _run(["node", "--input-type=module", "-e", script], env=child_env, label=f"API-key {action}")
    if result.returncode != 0:
        raise ProbeFailure(f"API-key {action} failed (exit {result.returncode})")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeFailure(f"API-key {action} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ProbeFailure(f"API-key {action} returned an invalid result")
    return value


def _search(env: dict[str, str], api_url: str) -> dict[str, Any]:
    input_data = {"requests": [{
        "id": "cedarcomet-requirements",
        "query": "cedarcomet",
        "tlds": ["com", "net"],
        "country": "DE", "currency": "EUR", "max_results": 3,
        "availability": "prefer_available",
        "relevance_criteria": REQUIREMENTS,
    }]}
    command = ["node", str(CLI_DIST), "--api-url", api_url,
               "apps", "hosting", "search_domains", "--input", json.dumps(input_data), "--json"]
    result = _run(command, env=env, label="Hosting CLI search", timeout=180)
    if result.returncode != 0:
        detail = (result.stdout + "\n" + result.stderr).lower()
        if any(marker in detail for marker in ("device approval", "device not approved", "new device detected")):
            approved = _node_key_action(env, "approve-device", {"id": env["OPENMATES_HOSTING_KEY_ID"]})
            if approved.get("approved", 0) < 1:
                raise ProbeFailure("Temporary API-key device approval was unavailable")
            result = _run(command, env=env, label="Hosting CLI search after device approval", timeout=180)
    if result.returncode != 0:
        raise ProbeFailure(f"Hosting CLI search failed (exit {result.returncode})")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeFailure("Hosting CLI returned invalid JSON") from exc
    data = payload.get("data", payload) if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ProbeFailure("Hosting CLI returned an invalid result")
    return data


def _verify(data: dict[str, Any], revision: str) -> dict[str, Any]:
    groups = data.get("results")
    if data.get("success") is not True or not isinstance(groups, list) or len(groups) != 1:
        raise ProbeFailure("Hosting search did not complete with one successful group")
    group = groups[0]
    if not isinstance(group, dict) or group.get("error"):
        raise ProbeFailure("Hosting search group failed")
    if group.get("relevance_applied") is not True:
        raise ProbeFailure("Real Jev relevance was not applied; fallback is not a pass")
    selected, checked = group.get("results"), group.get("checked_results")
    if not isinstance(selected, list) or not isinstance(checked, list) or not 1 <= len(checked) <= 40 or len(selected) > 3:
        raise ProbeFailure("Hosting selected or checked result bounds are invalid")
    if group.get("id") != "cedarcomet-requirements" or group.get("provider") != "Gandi":
        raise ProbeFailure("Hosting grouped identity or provider was lost")
    if group.get("country") != "DE" or group.get("currency") != "EUR":
        raise ProbeFailure("Hosting tax country or currency was lost")
    seen: set[str] = set()
    for item in checked:
        if not isinstance(item, dict) or not isinstance(item.get("domain_ascii"), str) or not item["domain_ascii"].endswith(DOMAIN_SUFFIXES):
            raise ProbeFailure("Gandi returned a domain outside the requested TLDs")
        name = item["domain_ascii"]
        if name in seen:
            raise ProbeFailure("Hosting checked results contain duplicate domains")
        seen.add(name)
        if item.get("availability") not in {"available", "unavailable", "unknown"}:
            raise ProbeFailure("Hosting returned an invalid availability status")
        if item.get("country") != "DE" or item.get("currency") != "EUR":
            raise ProbeFailure("Hosting result quote context is missing")
        for field in ("registration_tiers", "renewal_tiers"):
            tiers = item.get(field)
            if not isinstance(tiers, list):
                raise ProbeFailure("Hosting quote tiers are missing")
            for tier in tiers:
                if not isinstance(tier, dict) or not isinstance(tier.get("duration_range"), dict):
                    raise ProbeFailure("Hosting quote tier has invalid term context")
                for price_field in ("price_excluding_tax", "price_including_tax", "normal_price"):
                    amount = tier.get(price_field)
                    if amount is not None and (isinstance(amount, bool) or not isinstance(amount, (int, float))):
                        raise ProbeFailure("Hosting quote tier has an invalid numeric price")
    for item in selected:
        if not isinstance(item, dict) or item.get("domain_ascii") not in seen:
            raise ProbeFailure("Selected domain was not part of checked evidence")
        if item.get("availability") not in {"available", "unavailable"}:
            raise ProbeFailure("Selected domain has unknown availability")
    return {
        "revision": revision,
        "skill": "hosting.search_domains",
        "query": "cedarcomet",
        "relevance_applied": True,
        "selected_count": len(selected),
        "checked_count": len(checked),
        "domains": [{"domain": item["domain_ascii"], "availability": item["availability"]} for item in checked],
        "checked_at": group.get("checked_at"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Hosting search with one real dev Jev decision")
    parser.add_argument("--env-file", type=Path, required=True, help="Canonical test-account .env file")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--revision", required=True, help="Deployed dev revision")
    parser.add_argument("--output", type=Path, help="Optional private JSON receipt")
    args = parser.parse_args()
    if urlsplit(args.api_url).scheme != "https" or urlsplit(args.api_url).hostname != "api.dev.openmates.org":
        raise ProbeFailure("This real inference probe only runs against the dev API")
    if not CLI_DIST.is_file():
        raise ProbeFailure("Built local CLI/SDK is required before this probe")
    account_env = _test_account_env(args.env_file)
    with tempfile.TemporaryDirectory(prefix="hosting-requirements-") as state_dir:
        env = {name: value for name, value in os.environ.items()
               if not name.startswith("OPENMATES_TEST_ACCOUNT") and name != "OPENMATES_API_KEY"}
        env.update(account_env)
        env.update({"OPENMATES_STATE_DIR": state_dir,
                    "OPENMATES_PROFILE": "", "OPENMATES_API_URL": args.api_url,
                    "PLAYWRIGHT_WORKER_SLOT": ""})
        login = _run(["node", str(LOGIN_HELPER), "login", "--api-url", args.api_url],
                     env=env, label="Test-account login", timeout=180)
        if login.returncode != 0:
            raise ProbeFailure(f"Test-account login failed (exit {login.returncode})")
        try:
            login_result = json.loads(login.stdout)
        except json.JSONDecodeError as exc:
            raise ProbeFailure("Test-account login returned invalid JSON") from exc
        if not isinstance(login_result, dict) or login_result.get("success") is not True or not isinstance(login_result.get("slot"), str):
            raise ProbeFailure("Test-account login did not identify its successful slot")
        key_id: str | None = None
        receipt: dict[str, Any]
        try:
            # Login already consumed a TOTP code; wait for the next one-use step.
            time.sleep(30 - (time.time() % 30) + 1)
            env["OPENMATES_HOSTING_TOTP_CODE"] = _totp_code(account_env, login_result["slot"])
            created = _node_key_action(env, "create", {
                "name": f"hosting-requirements-{uuid4().hex[:12]}",
                "fullAccess": True,
                "creditLimit": {"period": "lifetime", "credits": 100},
                "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                "scopes": {},
            })
            env.pop("OPENMATES_HOSTING_TOTP_CODE", None)
            api_key, key_id = created.get("apiKey"), created.get("keyId")
            if not isinstance(api_key, str) or not api_key.startswith("sk-api-") or not isinstance(key_id, str):
                raise ProbeFailure("Temporary API-key creation returned an invalid shape")
            env["OPENMATES_API_KEY"] = api_key
            env["OPENMATES_HOSTING_KEY_ID"] = key_id
            receipt = _verify(_search(env, args.api_url), args.revision)
        finally:
            env.pop("OPENMATES_API_KEY", None)
            env.pop("OPENMATES_HOSTING_TOTP_CODE", None)
            if key_id:
                _node_key_action(env, "revoke", {"id": key_id})
        if args.output:
            output = args.output.expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            output.chmod(0o600)
        print(f"PASS hosting.search_domains Jev applied; selected={receipt['selected_count']} checked={receipt['checked_count']} revision={args.revision}")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProbeFailure as exc:
        raise SystemExit(f"FAIL: {exc}") from None
