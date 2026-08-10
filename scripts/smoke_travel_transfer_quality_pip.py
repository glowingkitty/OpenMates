#!/usr/bin/env python3
"""Live pip SDK smoke for travel transfer-quality metadata.

Purpose: verify the generated Python app-skill method calls the real dev API
with min_transfer_minutes and preserves transfer-quality response fields.
Security: reads API-key auth from environment or --api-key and never prints the
credential.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(ROOT / "packages" / "openmates-python"))

from openmates import OpenMates  # noqa: E402


DEFAULT_API_URL = "https://api.dev.openmates.org"
DEFAULT_DEVICE_ID = "travel-transfer-quality-pip-smoke"
CLI_DIST = ROOT / "frontend/packages/openmates-cli/dist/cli.js"
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
        cwd=ROOT,
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


def _is_device_approval_error(exc: Exception) -> bool:
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


def build_payload(min_transfer_minutes: int) -> dict[str, Any]:
    return {
        "requests": [
            {
                "id": "travel-transfer-quality-pip-smoke",
                "legs": [{"origin": "Berlin", "destination": "Hamburg", "date": _future_date()}],
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


def _extract_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _result_groups(data: dict[str, Any]) -> list[dict[str, Any]]:
    groups = data.get("results")
    if not isinstance(groups, list):
        raise AssertionError(f"Travel SDK response did not include result groups: {json.dumps(data)[:900]}")
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


def validate_travel_contract(payload: dict[str, Any], min_transfer_minutes: int) -> dict[str, Any]:
    serialized = json.dumps(payload)
    leaked = [marker for marker in SECRET_LEAK_MARKERS if marker in serialized]
    if leaked:
        raise AssertionError(f"Travel response leaked forbidden provider/auth markers: {leaked}")

    data = _extract_data(payload)
    groups = _result_groups(data)
    first_group = groups[0] if groups else None
    results = first_group.get("results") if isinstance(first_group, dict) else None
    if not isinstance(results, list):
        raise AssertionError(f"Travel SDK response group missing results: {first_group!r}")
    if not results:
        reason = first_group.get("no_result_reason") or first_group.get("error")
        if not isinstance(reason, str) or not reason:
            raise AssertionError("Empty travel SDK response must explain no results")
        return {"status": "passed", "mode": "empty_with_reason", "reason": reason, "result_count": 0, "provider": data.get("provider")}

    transfer_quality_results = 0
    optimized_count = 0
    layover_count = 0
    amenity_layover_count = 0
    for result in results:
        if not isinstance(result, dict):
            continue
        quality = result.get("transfer_quality")
        if isinstance(quality, dict):
            if quality.get("min_transfer_minutes") != min_transfer_minutes:
                raise AssertionError(f"Unexpected min transfer metadata: {quality!r}")
            transfer_quality_results += 1
        optimization = result.get("optimization")
        if isinstance(optimization, dict) and optimization.get("optimized_by") == "openmates":
            if optimization.get("badge") != "Optimized by OpenMates":
                raise AssertionError(f"Optimized result missing badge: {optimization!r}")
            optimized_count += 1
        for layover in _layovers(result):
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

    if transfer_quality_results == 0:
        raise AssertionError("Travel SDK results did not include transfer_quality metadata")
    return {
        "status": "passed",
        "mode": "results",
        "provider": data.get("provider"),
        "result_count": len(results),
        "transfer_quality_results": transfer_quality_results,
        "layover_count": layover_count,
        "amenity_layover_count": amenity_layover_count,
        "optimized_count": optimized_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live Travel transfer-quality pip SDK smoke.")
    parser.add_argument("--api", default=DEFAULT_API_URL)
    parser.add_argument("--api-key", default=os.getenv("OPENMATES_TEST_ACCOUNT_API_KEY") or os.getenv("OPENMATES_API_KEY") or "")
    parser.add_argument(
        "--create-api-key-from-cli-session",
        action="store_true",
        help="Create and revoke a temporary API key using the current logged-in CLI session.",
    )
    parser.add_argument("--min-transfer-minutes", type=int, default=15)
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()
    if not args.api_key and args.create_api_key_from_cli_session:
        name = f"travel-transfer-quality-pip-smoke-{os.getpid()}"
        with _api_key_from_cli_session(args.api, name) as (temporary_api_key, key_id):
            args.api_key = temporary_api_key
            try:
                summary = run_sdk_smoke(args)
            except Exception as exc:
                if not _is_device_approval_error(exc):
                    raise
                approved_devices = _approve_pending_key_devices(args.api, key_id, {"pip"})
                if not approved_devices:
                    raise RuntimeError("No pending pip API-key device was available to approve") from exc
                summary = run_sdk_smoke(args)
            summary["temporary_key_device_approval"] = "via_cli_session"
            print_summary(summary, args.json_output)
            return 0

    if not args.api_key:
        print("Missing OPENMATES_TEST_ACCOUNT_API_KEY, OPENMATES_API_KEY, --api-key, or --create-api-key-from-cli-session", file=sys.stderr)
        return 2

    summary = run_sdk_smoke(args)
    print_summary(summary, args.json_output)
    return 0


def run_sdk_smoke(args: argparse.Namespace) -> dict[str, Any]:
    client = OpenMates(api_key=args.api_key, api_url=args.api, device_id=DEFAULT_DEVICE_ID)
    response = client.apps.travel.search_connections(build_payload(args.min_transfer_minutes))
    summary = validate_travel_contract(response, args.min_transfer_minutes)
    summary["api_url"] = args.api
    summary["sdk"] = "pip"
    return summary


def print_summary(summary: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Travel transfer-quality pip SDK smoke passed: {summary['mode']} ({summary.get('result_count', 0)} results)")


if __name__ == "__main__":
    raise SystemExit(main())
