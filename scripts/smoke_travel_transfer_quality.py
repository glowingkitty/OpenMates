#!/usr/bin/env python3
"""Live REST smoke for travel transfer-quality metadata.

Purpose: verify the travel/search_connections app-skill contract against the
real dev API, including auth boundaries and transfer-quality fields.
Security: uses API-key auth from environment or --api-key and never prints the
credential. Provider keys and raw long provider payloads must not appear in the
response.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError


DEFAULT_API_URL = "https://api.dev.openmates.org"
DEFAULT_DEVICE_ID = "travel-transfer-quality-rest-smoke"
APP_SKILL_PATH = "/v1/apps/travel/skills/search_connections"
TASK_POLL_TIMEOUT_SECONDS = 180
TASK_POLL_INTERVAL_SECONDS = 2
REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_DIST = REPO_ROOT / "frontend/packages/openmates-cli/dist/cli.js"
SECRET_LEAK_MARKERS = (
    "SECRET__GEOAPIFY",
    "apiKey",
    "api_key",
    "access_token",
    "Authorization",
)


def _parse_json_output(output: str) -> dict[str, Any]:
    start = output.find("{")
    if start < 0:
        raise RuntimeError(f"Expected JSON object in CLI output, got:\n{output}")
    return json.loads(output[start:])


def _api_key_id(create_result: dict[str, Any]) -> str | None:
    key = create_result.get("key")
    if isinstance(key, dict) and isinstance(key.get("id"), str):
        return key["id"]
    if isinstance(create_result.get("id"), str):
        return create_result["id"]
    return None


def _run_cli_json(args: list[str], *, api_url: str, env: dict[str, str]) -> dict[str, Any]:
    if not CLI_DIST.exists():
        raise RuntimeError("Missing CLI dist/cli.js. Run: cd frontend/packages/openmates-cli && npm run build")
    result = subprocess.run(
        ["node", os.fspath(CLI_DIST), *args, "--json"],
        cwd=REPO_ROOT,
        env={**env, "OPENMATES_API_URL": api_url},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"CLI command failed with exit {result.returncode}: {result.stderr or result.stdout}")
    return _parse_json_output(result.stdout)


def _session_cookie_header() -> str:
    session_path = Path.home() / ".openmates" / "session.json"
    if not session_path.exists():
        raise RuntimeError("No logged-in CLI session found; run `openmates login` before temporary-key smoke.")
    session = json.loads(session_path.read_text(encoding="utf-8"))
    cookies = session.get("cookies") or {}
    if not isinstance(cookies, dict) or not cookies:
        raise RuntimeError("Logged-in CLI session has no cookies; run `openmates login` again.")
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
        raise RuntimeError(f"Settings request {method} {path} failed with HTTP {exc.code}: {body}") from exc


def _approve_pending_key_devices(api_url: str, key_id: str, access_types: set[str]) -> list[str]:
    data = _settings_request(api_url, "api-key-devices")
    approved: list[str] = []
    for device in data.get("devices", []):
        if not isinstance(device, dict):
            continue
        if device.get("api_key_id") != key_id or device.get("approved_at"):
            continue
        if device.get("access_type") not in access_types:
            continue
        device_id = device.get("id")
        if not isinstance(device_id, str):
            continue
        _settings_request(api_url, f"api-key-devices/{device_id}/approve", method="POST")
        approved.append(device_id)
    return approved


def _is_device_approval_error(exc: RuntimeError) -> bool:
    message = str(exc)
    return "approved_device_required" in message or "New device detected" in message or "HTTP 403" in message


@contextmanager
def _api_key_from_cli_session(api_url: str, name: str):
    env = os.environ.copy()
    created = _run_cli_json(["settings", "developers", "api-keys", "create", name, "--yes"], api_url=api_url, env=env)
    api_key = created.get("api_key")
    key_id = _api_key_id(created)
    if not isinstance(api_key, str) or not api_key.startswith("sk-api-"):
        raise RuntimeError("CLI did not return a one-time API key")
    if not isinstance(key_id, str) or not key_id:
        raise RuntimeError("CLI did not return API key id")
    try:
        yield api_key, key_id
    finally:
        try:
            _run_cli_json(["settings", "developers", "api-keys", "revoke", key_id, "--yes"], api_url=api_url, env=env)
        except Exception as exc:  # noqa: BLE001 - cleanup must not mask smoke result.
            print(f"WARNING: failed to revoke temporary API key {key_id}: {exc}", file=sys.stderr)


def _future_date(days_ahead: int = 14) -> str:
    return (date.today() + timedelta(days=days_ahead)).isoformat()


def build_payload(scenario: str, min_transfer_minutes: int) -> dict[str, Any]:
    if scenario != "deutschland-ticket-regional":
        raise ValueError(f"Unsupported scenario: {scenario}")
    return {
        "requests": [
            {
                "id": "travel-transfer-quality-smoke",
                "legs": [
                    {
                        "origin": "Berlin",
                        "destination": "Hamburg",
                        "date": _future_date(),
                    }
                ],
                "providers": ["deutsche_bahn"],
                "transport_methods": ["train"],
                "owned_passes": ["deutschland_ticket"],
                "pass_only": True,
                "rail_products": ["regional", "regional_express", "s_bahn"],
                "min_transfer_minutes": min_transfer_minutes,
                "max_results": 8,
            }
        ]
    }


def _request_json(
    *,
    api_url: str,
    path: str,
    method: str = "POST",
    payload: dict[str, Any] | None = None,
    api_key: str | None,
    device_id: str,
    expect_auth_error: bool = False,
    timeout: int = 120,
) -> tuple[int, dict[str, Any]]:
    headers = {
        "Accept": "application/json",
        "X-OpenMates-SDK": "cli",
        "X-OpenMates-Device-Identity": device_id,
    }
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib_request.Request(
        f"{api_url.rstrip('/')}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib_request.urlopen(req, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body_text or "{}")
        except json.JSONDecodeError:
            data = {"error": body_text[:500]}
        if expect_auth_error:
            return exc.code, data
        raise RuntimeError(f"Travel skill request failed with HTTP {exc.code}: {data}") from exc


def _extract_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _wrap_resolved(original: dict[str, Any], result: Any) -> dict[str, Any]:
    if "success" in original:
        return {**original, "data": result if isinstance(result, dict) else {"result": result}}
    return result if isinstance(result, dict) else {"result": result}


def _resolve_async_response(api_url: str, body: dict[str, Any], api_key: str, device_id: str) -> dict[str, Any]:
    data = _extract_data(body)
    task_ids: list[str] = []
    if isinstance(data.get("task_id"), str):
        task_ids = [data["task_id"]]
    elif isinstance(data.get("task_ids"), list):
        task_ids = [item for item in data["task_ids"] if isinstance(item, str)]
    if not task_ids:
        return body

    started = time.monotonic()
    results: list[Any] = []
    for task_id in task_ids:
        while time.monotonic() - started < TASK_POLL_TIMEOUT_SECONDS:
            status, task = _request_json(
                api_url=api_url,
                path=f"/v1/tasks/{task_id}",
                method="GET",
                payload=None,
                api_key=api_key,
                device_id=device_id,
                timeout=30,
            )
            if status != 200:
                raise AssertionError(f"Task poll returned HTTP {status}")
            if task.get("status") == "completed":
                results.append(task.get("result"))
                break
            if task.get("status") == "failed":
                raise AssertionError(f"Task {task_id} failed: {task.get('error')}")
            time.sleep(TASK_POLL_INTERVAL_SECONDS)
        else:
            raise TimeoutError(f"Task {task_id} did not complete within {TASK_POLL_TIMEOUT_SECONDS}s")
    if len(results) == 1:
        return _wrap_resolved(body, results[0])
    return _wrap_resolved(body, {"results": results})


def _result_groups(data: dict[str, Any]) -> list[dict[str, Any]]:
    groups = data.get("results")
    if not isinstance(groups, list):
        raise AssertionError(f"Travel response did not include result groups: {json.dumps(data)[:900]}")
    return [group for group in groups if isinstance(group, dict)]


def _layovers(result: dict[str, Any]) -> list[dict[str, Any]]:
    layovers: list[dict[str, Any]] = []
    for leg in result.get("legs", []) or []:
        if not isinstance(leg, dict):
            continue
        for layover in leg.get("layovers", []) or []:
            if isinstance(layover, dict):
                layovers.append(layover)
    return layovers


def validate_travel_transfer_contract(payload: dict[str, Any], min_transfer_minutes: int) -> dict[str, Any]:
    serialized = json.dumps(payload)
    leaked = [marker for marker in SECRET_LEAK_MARKERS if marker in serialized]
    if leaked:
        raise AssertionError(f"Travel response leaked forbidden provider/auth markers: {leaked}")

    data = _extract_data(payload)
    groups = _result_groups(data)
    if not groups:
        raise AssertionError("Travel response included no result groups")
    first_group = groups[0]
    results = first_group.get("results")
    if not isinstance(results, list):
        raise AssertionError(f"Travel response group missing results: {first_group!r}")
    if not results:
        reason = first_group.get("no_result_reason") or first_group.get("error")
        if not isinstance(reason, str) or not reason:
            raise AssertionError(f"Empty travel response must explain no results: {first_group!r}")
        return {
            "status": "passed",
            "mode": "empty_with_reason",
            "reason": reason,
            "provider": data.get("provider"),
            "result_count": 0,
        }

    transfer_quality_count = 0
    optimized_count = 0
    amenity_layover_count = 0
    layover_count = 0
    for raw_result in results:
        if not isinstance(raw_result, dict):
            continue
        quality = raw_result.get("transfer_quality")
        if isinstance(quality, dict):
            if quality.get("min_transfer_minutes") != min_transfer_minutes:
                raise AssertionError(f"Unexpected min transfer metadata: {quality!r}")
            transfer_quality_count += 1
        optimization = raw_result.get("optimization")
        if isinstance(optimization, dict) and optimization.get("optimized_by") == "openmates":
            if optimization.get("badge") != "Optimized by OpenMates":
                raise AssertionError(f"Optimized result missing badge: {optimization!r}")
            optimized_count += 1
        for layover in _layovers(raw_result):
            layover_count += 1
            duration = layover.get("duration_minutes")
            if isinstance(duration, int) and duration < min_transfer_minutes:
                raise AssertionError(f"Result includes too-short transfer after filtering: {layover!r}")
            amenities = layover.get("amenities")
            if isinstance(amenities, dict):
                groups_value = amenities.get("groups")
                if not isinstance(groups_value, dict):
                    raise AssertionError(f"Transfer amenities missing groups: {amenities!r}")
                for key in ("food_drink", "shops", "toilets"):
                    if key not in groups_value:
                        raise AssertionError(f"Transfer amenities missing {key}: {amenities!r}")
                amenity_layover_count += 1

    if transfer_quality_count == 0:
        raise AssertionError("Travel results did not include transfer_quality metadata")

    return {
        "status": "passed",
        "mode": "results",
        "provider": data.get("provider"),
        "result_count": len(results),
        "transfer_quality_results": transfer_quality_count,
        "layover_count": layover_count,
        "amenity_layover_count": amenity_layover_count,
        "optimized_count": optimized_count,
    }


def run_rest_smoke(args: argparse.Namespace) -> dict[str, Any]:
    payload = build_payload(args.scenario, args.min_transfer_minutes)
    auth_status, _auth_body = _request_json(
        api_url=args.api,
        path=APP_SKILL_PATH,
        payload=payload,
        api_key=None,
        device_id=args.device_id,
        expect_auth_error=True,
    )
    if auth_status not in {401, 403}:
        raise AssertionError(f"Unauthenticated travel app-skill call returned HTTP {auth_status}, expected 401/403")

    status, body = _request_json(
        api_url=args.api,
        path=APP_SKILL_PATH,
        payload=payload,
        api_key=args.api_key,
        device_id=args.device_id,
    )
    if status != 200:
        raise AssertionError(f"Authenticated travel app-skill call returned HTTP {status}")
    resolved = _resolve_async_response(args.api, body, args.api_key, args.device_id)
    summary = validate_travel_transfer_contract(resolved, args.min_transfer_minutes)
    summary.update(
        {
            "api_url": args.api,
            "auth_boundary": "unauthenticated_rejected",
            "access_model": "authenticated first-party/developer app-skill REST",
            "encryption_boundary": "plaintext travel parameters only; no client-side encrypted chat/memory/key material",
        }
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live Travel transfer-quality REST smoke.")
    parser.add_argument("--api", default=DEFAULT_API_URL, help="OpenMates API URL")
    parser.add_argument("--api-key", default=os.getenv("OPENMATES_TEST_ACCOUNT_API_KEY") or os.getenv("OPENMATES_API_KEY") or "")
    parser.add_argument(
        "--create-api-key-from-cli-session",
        action="store_true",
        help="Create and revoke a temporary API key using the current logged-in CLI session.",
    )
    parser.add_argument("--device-id", default=DEFAULT_DEVICE_ID)
    parser.add_argument("--scenario", default="deutschland-ticket-regional")
    parser.add_argument("--min-transfer-minutes", type=int, default=10)
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()

    if not args.api_key and args.create_api_key_from_cli_session:
        name = f"travel-transfer-quality-rest-smoke-{int(time.time())}"
        with _api_key_from_cli_session(args.api, name) as (temporary_api_key, key_id):
            args.api_key = temporary_api_key
            try:
                summary = run_rest_smoke(args)
            except RuntimeError as exc:
                if not _is_device_approval_error(exc):
                    raise
                approved_devices = _approve_pending_key_devices(args.api, key_id, {"cli"})
                if not approved_devices:
                    raise RuntimeError("No pending CLI API-key device was available to approve") from exc
                summary = run_rest_smoke(args)
            summary["temporary_key_device_approval"] = "via_cli_session"
            if args.json_output:
                print(json.dumps(summary, indent=2))
            else:
                print(f"Travel transfer-quality REST smoke passed: {summary['mode']} ({summary.get('result_count', 0)} results)")
            return 0

    if not args.api_key:
        print("Missing OPENMATES_TEST_ACCOUNT_API_KEY, OPENMATES_API_KEY, --api-key, or --create-api-key-from-cli-session", file=sys.stderr)
        return 2
    summary = run_rest_smoke(args)
    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Travel transfer-quality REST smoke passed: {summary['mode']} ({summary.get('result_count', 0)} results)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
