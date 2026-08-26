#!/usr/bin/env python3
"""Verify AI-memory removal through real OpenMates client surfaces.

The verifier logs a disposable CLI home into an existing test account, exercises
the dev API through REST, CLI, npm SDK, or pip SDK, and revokes temporary API
keys. It never prints credentials, plaintext memories, or session cookies.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from verify_usage_overview_cli_sdk import (
    NPM_SDK_ENTRY,
    PYTHON_SDK_PATH,
    VerificationError,
    _approve_pending_key_devices,
    _create_api_key,
    _is_device_approval_error,
    _load_dotenv,
    _revoke_api_key,
    _run,
    _run_cli_json,
    _sdk_device_identity,
    _session_cookie_header,
    _setup_cli,
)


ROOT = Path(__file__).resolve().parents[1]
REMOVED_APP_ID = "ai"
REMOVED_ITEM_TYPE = "communication_style"
RETAINED_APP_ID = "code"
RETAINED_ITEM_TYPE = "preferred_tech"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def _request_json(
    api_url: str,
    path: str,
    *,
    env: dict[str, str],
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib_request.Request(
        f"{api_url.rstrip('/')}/{path.lstrip('/')}",
        method=method,
        data=data,
        headers={
            "Accept": "application/json",
            "Cookie": _session_cookie_header(env),
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
    )
    try:
        with urllib_request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib_error.HTTPError as exc:
        payload = json.loads(exc.read().decode("utf-8", errors="replace") or "{}")
        return exc.code, payload


def _apps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("apps") or payload.get("data") or []
    if isinstance(raw, dict):
        raw = raw.get("apps") or []
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _memory_types(app: dict[str, Any]) -> list[dict[str, Any]]:
    raw = app.get("settings_and_memories") or app.get("settingsAndMemories") or []
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _validate_types(payload: dict[str, Any]) -> dict[str, int]:
    apps = _apps(payload)
    _require(bool(apps), "Memory type response did not include app metadata")
    by_id = {str(app.get("id") or app.get("app_id") or ""): app for app in apps}
    ai_types = _memory_types(by_id.get(REMOVED_APP_ID, {}))
    retained_types = _memory_types(by_id.get(RETAINED_APP_ID, {}))
    retained_ids = {str(item.get("id") or item.get("item_type") or "") for item in retained_types}
    _require(
        not ai_types,
        f"AI memory types remain discoverable: {[str(item.get('id') or item.get('item_type') or '') for item in ai_types]}",
    )
    _require(RETAINED_ITEM_TYPE in retained_ids, "Retained Code memory type is not discoverable")
    return {"aiTypeCount": len(ai_types), "retainedTypeCount": len(retained_types)}


def _removed_entry(entry_id: str | None = None) -> dict[str, Any]:
    return {
        "id": entry_id or str(uuid.uuid4()),
        "app_id": REMOVED_APP_ID,
        "item_key": "removed-ai-memory-verification",
        "item_type": REMOVED_ITEM_TYPE,
        "encrypted_item_json": "verification-ciphertext",
        "encrypted_app_key": "",
        "created_at": 1,
        "updated_at": 1,
        "item_version": 1,
    }


def verify_rest(api_url: str, *, env: dict[str, str]) -> dict[str, Any]:
    _, types_payload = _request_json(api_url, "/v1/sdk/memories/types", env=env)
    counts = _validate_types(types_payload)
    status, payload = _request_json(
        api_url,
        "/v1/sdk/memories",
        env=env,
        method="POST",
        body={"entry": _removed_entry()},
    )
    _require(status == 410, f"REST AI-memory create returned {status}, expected 410")
    _require("no longer supported" in str(payload).lower(), "REST rejection did not expose the removal reason")
    list_status, listed = _request_json(
        api_url,
        f"/v1/sdk/memories?{urllib_parse.urlencode({'app_id': REMOVED_APP_ID})}",
        env=env,
    )
    _require(list_status == 200 and listed.get("memories") == [], "REST AI-memory list was not empty")
    return {"surface": "rest", **counts, "removedWriteStatus": status}


def verify_cli(*, env: dict[str, str]) -> dict[str, Any]:
    ai_types = _run_cli_json(["settings", "memories", "types", "--app-id", REMOVED_APP_ID], env=env)
    retained_types = _run_cli_json(["settings", "memories", "types", "--app-id", RETAINED_APP_ID], env=env)
    _require(ai_types == [], "CLI still exposes AI memory types")
    _require(any(item.get("item_type") == RETAINED_ITEM_TYPE for item in retained_types), "CLI lost the retained Code memory type")
    command = [
        "node",
        "dist/cli.js",
        "settings",
        "memories",
        "create",
        "--app-id",
        REMOVED_APP_ID,
        "--item-type",
        REMOVED_ITEM_TYPE,
        "--data",
        json.dumps({"title": "verification"}),
        "--json",
    ]
    result = subprocess.run(command, cwd=ROOT / "frontend/packages/openmates-cli", env=env, text=True, capture_output=True, check=False, timeout=60)
    _require(result.returncode != 0, "CLI accepted removed AI memory creation")
    _require("unknown memory type" in f"{result.stdout}\n{result.stderr}".lower(), "CLI rejection did not identify the removed type")
    return {"surface": "cli", "aiTypeCount": 0, "retainedTypeCount": len(retained_types)}


def _npm_script() -> str:
    return f"""
import {{ OpenMates }} from {json.dumps(NPM_SDK_ENTRY)};
const client = new OpenMates({{
  apiKey: process.env.OPENMATES_SMOKE_API_KEY,
  apiUrl: process.env.OPENMATES_API_URL,
  deviceId: process.env.OPENMATES_SMOKE_DEVICE_ID,
}});
const types = await client.memories.types();
let rejected = false;
try {{
  await client.memories.create({{appId: 'ai', itemType: 'communication_style', data: {{title: 'verification'}}}});
}} catch (error) {{
  rejected = /410|no longer supported/i.test(String(error));
}}
console.log(JSON.stringify({{types, rejected}}));
"""


def _pip_script() -> str:
    return """
import json
import os
import sys
sys.path.insert(0, os.fspath(%r))
from openmates import OpenMates
client = OpenMates(api_key=os.environ["OPENMATES_SMOKE_API_KEY"], api_url=os.environ["OPENMATES_API_URL"], device_id=os.environ["OPENMATES_SMOKE_DEVICE_ID"])
types = client.memories.types()
rejected = False
try:
    client.memories.create({"appId": "ai", "itemType": "communication_style", "data": {"title": "verification"}})
except Exception as error:
    rejected = "410" in str(error) or "no longer supported" in str(error).lower()
print(json.dumps({"types": types, "rejected": rejected}))
""" % os.fspath(PYTHON_SDK_PATH)


def _run_sdk(surface: str, *, env: dict[str, str]) -> dict[str, Any]:
    command = ["node", "--input-type=module", "-e", _npm_script()] if surface == "npm" else ["python3", "-c", _pip_script()]
    result = _run(command, cwd=ROOT, env=env, timeout=120)
    payload = json.loads(result.stdout.strip())
    counts = _validate_types(payload["types"])
    _require(payload.get("rejected") is True, f"{surface} SDK accepted removed AI memory creation")
    return {"surface": surface, **counts, "removedWriteRejected": True}


def verify_sdk(surface: str, api_url: str, *, env: dict[str, str]) -> dict[str, Any]:
    key_id, api_key = _create_api_key(api_url, env=env)
    sdk_env = {
        **env,
        "OPENMATES_API_URL": api_url,
        "OPENMATES_SMOKE_API_KEY": api_key,
        "OPENMATES_SMOKE_DEVICE_ID": _sdk_device_identity(surface).replace("usage-overview", "ai-memory-removal"),
    }
    try:
        try:
            return _run_sdk(surface, env=sdk_env)
        except RuntimeError as exc:
            if not _is_device_approval_error(exc):
                raise
            approved = _approve_pending_key_devices(api_url, key_id, {surface}, env=env)
            _require(bool(approved), f"No pending {surface} SDK device was available to approve")
            return _run_sdk(surface, env=sdk_env)
    finally:
        _revoke_api_key(key_id, api_url, env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify AI-memory removal against the real dev API.")
    parser.add_argument("--surface", choices=["rest", "cli", "npm", "pip", "all"], default="all")
    parser.add_argument("--api-url", default=os.getenv("OPENMATES_API_URL", "https://api.dev.openmates.org"))
    parser.add_argument("--slot", default=os.getenv("OPENMATES_TEST_ACCOUNT_SOURCE_SLOT"))
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    api_url = args.api_url.rstrip("/")
    with tempfile.TemporaryDirectory(prefix="openmates-ai-memory-removal-") as temp_home:
        env = os.environ.copy()
        _load_dotenv(env)
        env.update({"HOME": temp_home, "USERPROFILE": temp_home, "OPENMATES_API_URL": api_url})
        _setup_cli(api_url, slot=args.slot, skip_build=args.skip_build, env=env)
        surfaces = ["rest", "cli", "npm", "pip"] if args.surface == "all" else [args.surface]
        results: dict[str, Any] = {}
        for surface in surfaces:
            if surface == "rest":
                results[surface] = verify_rest(api_url, env=env)
            elif surface == "cli":
                results[surface] = verify_cli(env=env)
            else:
                results[surface] = verify_sdk(surface, api_url, env=env)

    print(json.dumps({"success": True, "apiUrl": api_url, "results": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except VerificationError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
