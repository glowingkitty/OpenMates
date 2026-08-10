#!/usr/bin/env python3
"""Live REST API security hardening smoke checks.

Purpose: verify the deployed dev API enforces the strict REST surface taxonomy
with real HTTP requests, temporary scoped API keys, and the existing CLI test
account session.
Security: reads test-account credentials from the normal environment/.env flow,
never prints API-key secrets, and revokes temporary keys before exit.
Run: OPENMATES_API_URL=https://api.dev.openmates.org python3 scripts/api_tests/test_rest_api_security_hardening.py --scenario scope-denials
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_DIR = REPO_ROOT / "frontend/packages/openmates-cli"
CLI_DIST = CLI_DIR / "dist/cli.js"
SDK_ENTRY = "./frontend/packages/openmates-cli/dist/index.js"
DEFAULT_API_URL = "https://api.dev.openmates.org"


class SmokeFailure(RuntimeError):
    pass


def _run(command: list[str], *, cwd: Path = REPO_ROOT, env: dict[str, str] | None = None, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise SmokeFailure(
            f"Command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _ensure_cli_session(api_url: str, *, skip_build: bool) -> None:
    if not skip_build or not CLI_DIST.exists():
        _run(["npm", "run", "build"], cwd=CLI_DIR, timeout=240)
    _run(["node", "scripts/openmates_cli_test_account.mjs", "login", "--api-url", api_url], timeout=180)


def _home_state_session() -> dict[str, Any]:
    session_path = Path.home() / ".openmates" / "session.json"
    if not session_path.exists():
        raise SmokeFailure("No logged-in CLI session found after test-account login.")
    return json.loads(session_path.read_text(encoding="utf-8"))


def _session_cookie_header() -> str:
    cookies = _home_state_session().get("cookies") or {}
    if not isinstance(cookies, dict) or not cookies:
        raise SmokeFailure("Logged-in CLI session has no cookies.")
    return "; ".join(f"{key}={value}" for key, value in cookies.items() if isinstance(value, str))


def _settings_request(api_url: str, path: str, *, method: str = "GET") -> dict[str, Any]:
    req = urllib_request.Request(
        f"{api_url.rstrip('/')}/v1/settings/{path.lstrip('/')}",
        method=method,
        headers={"Accept": "application/json", "Cookie": _session_cookie_header()},
    )
    if method != "GET":
        req.add_header("Content-Type", "application/json")
        req.data = b"{}"
    try:
        with urllib_request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SmokeFailure(f"Settings request {method} {path} failed with HTTP {exc.code}: {body}") from exc


def _node_api_key_action(api_url: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    script = f"""
      import {{ OpenMatesClient }} from '{SDK_ENTRY}';
      const client = new OpenMatesClient({{ apiUrl: process.env.OPENMATES_API_URL }});
      const payload = JSON.parse(process.env.OPENMATES_REST_SMOKE_PAYLOAD);
      if (process.env.OPENMATES_REST_SMOKE_ACTION === 'create') {{
        const result = await client.createApiKey(payload);
        console.log(JSON.stringify({{ apiKey: result.api_key, key: result.key }}));
      }} else if (process.env.OPENMATES_REST_SMOKE_ACTION === 'revoke') {{
        const result = await client.revokeApiKey(payload.id);
        console.log(JSON.stringify({{ revoked: true, result }}));
      }} else {{
        throw new Error('Unsupported action');
      }}
    """
    env = os.environ.copy()
    env["OPENMATES_API_URL"] = api_url
    env["OPENMATES_REST_SMOKE_ACTION"] = action
    env["OPENMATES_REST_SMOKE_PAYLOAD"] = json.dumps(payload)
    result = _run(["node", "--input-type=module", "-e", script], env=env, timeout=180)
    return json.loads(result.stdout.strip())


def _create_api_key(api_url: str, *, name: str, full_access: bool, scopes: dict[str, Any]) -> tuple[str, str]:
    result = _node_api_key_action(
        api_url,
        "create",
        {"name": name, "fullAccess": full_access, "scopes": scopes},
    )
    api_key = result.get("apiKey")
    key = result.get("key") or {}
    key_id = key.get("id")
    if not isinstance(api_key, str) or not api_key.startswith("sk-api-") or not isinstance(key_id, str):
        raise SmokeFailure("Temporary API-key creation returned an invalid shape.")
    return api_key, key_id


def _revoke_api_key(api_url: str, key_id: str) -> None:
    _node_api_key_action(api_url, "revoke", {"id": key_id})


def _http_json(
    api_url: str,
    path: str,
    *,
    method: str = "GET",
    api_key: str | None = None,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-OpenMates-SDK"] = "rest_api"
    req = urllib_request.Request(f"{api_url.rstrip('/')}{path}", method=method, headers=headers, data=data)
    try:
        with urllib_request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw or "{}")
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError:
            parsed = {"raw": raw}
        return exc.code, parsed


def _approve_rest_device(api_url: str, key_id: str) -> list[str]:
    data = _settings_request(api_url, "api-key-devices")
    approved: list[str] = []
    for device in data.get("devices", []):
        if not isinstance(device, dict):
            continue
        if device.get("api_key_id") != key_id or device.get("approved_at") or device.get("access_type") != "rest_api":
            continue
        device_id = device.get("id")
        if isinstance(device_id, str):
            _settings_request(api_url, f"api-key-devices/{device_id}/approve", method="POST")
            approved.append(device_id)
    return approved


def _create_approved_key(api_url: str, *, name: str, full_access: bool, scopes: dict[str, Any]) -> tuple[str, str, list[str]]:
    api_key, key_id = _create_api_key(api_url, name=name, full_access=full_access, scopes=scopes)
    _http_json(api_url, "/v1/user-tasks/metadata", api_key=api_key)
    approved = _approve_rest_device(api_url, key_id)
    return api_key, key_id, approved


def _assert_status(status: int, expected: int, payload: dict[str, Any], label: str) -> None:
    if status != expected:
        raise SmokeFailure(f"{label}: expected HTTP {expected}, got {status}: {payload}")


def _assert_detail_error(payload: dict[str, Any], expected_error: str, label: str) -> None:
    detail = payload.get("detail")
    if not isinstance(detail, dict) or detail.get("error") != expected_error:
        raise SmokeFailure(f"{label}: expected error {expected_error!r}, got {payload}")


def scenario_scope_denials(api_url: str) -> dict[str, Any]:
    key_id = ""
    try:
        api_key, key_id, approved = _create_approved_key(
            api_url,
            name=f"rest-scope-denials-{int(time.time())}",
            full_access=False,
            scopes={},
        )
        unauth_status, unauth_payload = _http_json(api_url, "/v1/user-tasks/metadata")
        _assert_status(unauth_status, 401, unauth_payload, "task metadata missing auth")

        task_metadata_status, task_metadata_payload = _http_json(api_url, "/v1/user-tasks/metadata", api_key=api_key)
        _assert_status(task_metadata_status, 403, task_metadata_payload, "task metadata missing scope")
        _assert_detail_error(task_metadata_payload, "missing_scope", "task metadata missing scope")

        task_content_status, task_content_payload = _http_json(api_url, "/v1/user-tasks/not-real/history", api_key=api_key)
        if task_content_status == 404 and task_content_payload.get("detail") == "FEATURE_DISABLED":
            task_content_result = "feature_disabled"
        else:
            _assert_status(task_content_status, 403, task_content_payload, "encrypted task content blocked")
            _assert_detail_error(task_content_payload, "developer_api_access_not_classified", "encrypted task content blocked")
            task_content_result = "blocked"

        import_status, import_payload = _http_json(
            api_url,
            "/v1/account-imports/preview",
            method="POST",
            api_key=api_key,
            body={"source": "smoke", "chat_count": 0, "source_fingerprints": []},
        )
        _assert_status(import_status, 403, import_payload, "account import missing scope")
        _assert_detail_error(import_payload, "missing_scope", "account import missing scope")

        return {"keyId": key_id, "approvedDevices": approved, "checks": 4, "taskContent": task_content_result}
    finally:
        if key_id:
            _revoke_api_key(api_url, key_id)


def scenario_intended_surfaces(api_url: str) -> dict[str, Any]:
    key_id = ""
    scopes = {
        "workflows": ["workflow:read"],
        "tasks": ["task:read_metadata"],
        "plans": ["plan:read_metadata"],
        "account": ["account:import"],
    }
    try:
        api_key, key_id, approved = _create_approved_key(
            api_url,
            name=f"rest-intended-surfaces-{int(time.time())}",
            full_access=False,
            scopes=scopes,
        )

        for path in ("/v1/health", "/v1/docs", "/v1/geocode/search?q=Berlin"):
            status, payload = _http_json(api_url, path)
            _assert_status(status, 200, payload, f"public {path}")

        schema_status, schema = _http_json(api_url, "/openapi.json")
        _assert_status(schema_status, 200, schema, "openapi")
        paths = set((schema.get("paths") or {}).keys())
        required_paths = {"/v1/user-tasks/metadata", "/v1/user-plans/metadata", "/v1/workflows"}
        missing_paths = sorted(required_paths - paths)
        if missing_paths:
            raise SmokeFailure(f"OpenAPI missing expected paths: {missing_paths}")
        if "/v1/user-tasks/{task_id}" in paths:
            raise SmokeFailure("OpenAPI exposes encrypted task content route")

        workflow_status, workflow_payload = _http_json(api_url, "/v1/workflows", api_key=api_key)
        if workflow_status == 404 and workflow_payload.get("detail") == "FEATURE_DISABLED":
            workflow_result: dict[str, Any] = {"status": "feature_disabled"}
        else:
            _assert_status(workflow_status, 200, workflow_payload, "workflow read scoped")
            workflow_result = {"status": "ok"}

        task_status, task_payload = _http_json(api_url, "/v1/user-tasks/metadata", api_key=api_key)
        _assert_status(task_status, 200, task_payload, "task metadata scoped")

        plan_status, plan_payload = _http_json(api_url, "/v1/user-plans/metadata", api_key=api_key)
        _assert_status(plan_status, 200, plan_payload, "plan metadata scoped")

        import_status, import_payload = _http_json(
            api_url,
            "/v1/account-imports/preview",
            method="POST",
            api_key=api_key,
            body={"source": "smoke", "chat_count": 0, "source_fingerprints": []},
        )
        _assert_status(import_status, 200, import_payload, "account import scoped")

        return {"keyId": key_id, "approvedDevices": approved, "checks": 8, "workflow": workflow_result}
    finally:
        if key_id:
            _revoke_api_key(api_url, key_id)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live REST security hardening smoke checks.")
    parser.add_argument("--api-url", default=os.getenv("OPENMATES_API_URL", DEFAULT_API_URL))
    parser.add_argument("--scenario", choices=("scope-denials", "intended-surfaces", "all"), default="all")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    _ensure_cli_session(args.api_url, skip_build=args.skip_build)
    scenarios = ["scope-denials", "intended-surfaces"] if args.scenario == "all" else [args.scenario]
    results: dict[str, Any] = {"apiUrl": args.api_url, "scenarios": {}}
    for scenario in scenarios:
        if scenario == "scope-denials":
            results["scenarios"][scenario] = scenario_scope_denials(args.api_url)
        elif scenario == "intended-surfaces":
            results["scenarios"][scenario] = scenario_intended_surfaces(args.api_url)
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
