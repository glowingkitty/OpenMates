#!/usr/bin/env python3
"""Live REST smoke for Maps Geoapify enrichment.

Targets the real OpenMates app-skill REST endpoint and verifies the approved
contract: unauthenticated calls are rejected, authenticated Maps search returns
Google results with source-labelled Geoapify/OSM enrichment or an explicit
no-verified-results explanation, and required amenities are not satisfied by
unknown OSM fields. The script never prints API keys.
"""

from __future__ import annotations

import argparse
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
DEFAULT_DEVICE_ID = "maps-geoapify-live-smoke"
APP_SKILL_PATH = "/v1/apps/maps/skills/search"
UNKNOWN_VALUES = {None, False, "", "unknown", "no"}
REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_DIST = REPO_ROOT / "frontend/packages/openmates-cli/dist/cli.js"


def _canonical_amenity(value: str) -> str:
    aliases = {
        "air-conditioning": "air_conditioning",
        "airConditioning": "air_conditioning",
        "wifi": "internet_access",
        "wi-fi": "internet_access",
        "internet": "internet_access",
        "wheelchairAccess": "wheelchair",
        "outdoorSeating": "outdoor_seating",
    }
    if value in aliases:
        return aliases[value]
    normalized = []
    for char in value:
        if char.isupper():
            normalized.append("_")
            normalized.append(char.lower())
        elif char in {"-", " "}:
            normalized.append("_")
        else:
            normalized.append(char)
    return "".join(normalized).strip("_")


def _amenity_filters(required: list[str]) -> dict[str, str]:
    filters: dict[str, str] = {}
    for amenity in required:
        if amenity == "air_conditioning":
            filters["airConditioning"] = "required"
        elif amenity == "internet_access":
            filters["internetAccess"] = "free_required"
        elif amenity == "outdoor_seating":
            filters["outdoorSeating"] = "required"
        else:
            filters[amenity] = "required"
    return filters


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


def _request_json(
    *,
    api_url: str,
    payload: dict[str, Any],
    api_key: str | None,
    device_id: str,
    expect_auth_error: bool = False,
) -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-OpenMates-SDK": "cli",
        "X-OpenMates-Device-Identity": device_id,
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib_request.Request(
        f"{api_url.rstrip('/')}{APP_SKILL_PATH}",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=90) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        data = json.loads(exc.read().decode("utf-8") or "{}")
        if expect_auth_error:
            return exc.code, data
        raise RuntimeError(f"Maps skill request failed with HTTP {exc.code}: {data}") from exc


def _extract_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _first_group(data: dict[str, Any]) -> dict[str, Any]:
    results = data.get("results")
    if not isinstance(results, list) or not results:
        raise AssertionError(f"Maps response did not include result groups: {json.dumps(data)[:800]}")
    group = results[0]
    if not isinstance(group, dict):
        raise AssertionError(f"Maps response first group is invalid: {group!r}")
    return group


def _field_is_verified(field_record: Any) -> bool:
    if not isinstance(field_record, dict):
        return False
    value = field_record.get("value")
    if value in UNKNOWN_VALUES:
        return False
    if isinstance(value, dict):
        return any(item not in UNKNOWN_VALUES for item in value.values())
    return True


def _validate_maps_contract(data: dict[str, Any], required: list[str]) -> dict[str, Any]:
    group = _first_group(data)
    items = group.get("results")
    if not isinstance(items, list):
        raise AssertionError(f"Maps response group did not include results: {group!r}")

    if not items:
        summary = group.get("filter_summary")
        warnings = group.get("warnings")
        if not isinstance(summary, dict) or summary.get("status") != "no_verified_results":
            raise AssertionError(f"Empty strict response must explain no verified results: {group!r}")
        if not isinstance(warnings, list) or not warnings:
            raise AssertionError(f"Empty strict response must include a warning: {group!r}")
        return {
            "status": "passed",
            "mode": "no_verified_results",
            "provider": data.get("provider"),
            "required": required,
            "verified_count": summary.get("verified_count"),
        }

    for item in items:
        enrichment = item.get("osm_enrichment")
        if not isinstance(enrichment, dict):
            raise AssertionError(f"Result missing osm_enrichment: {item!r}")
        if enrichment.get("provider") != "Geoapify":
            raise AssertionError(f"Unexpected enrichment provider: {enrichment!r}")
        if enrichment.get("data_source") != "OpenStreetMap via Geoapify":
            raise AssertionError(f"Unexpected enrichment data source: {enrichment!r}")
        fields = enrichment.get("fields")
        if not isinstance(fields, dict):
            raise AssertionError(f"Enrichment missing fields: {enrichment!r}")
        for amenity in required:
            if not _field_is_verified(fields.get(amenity)):
                raise AssertionError(f"Required amenity {amenity} was not verified: {fields.get(amenity)!r}")

    serialized = json.dumps(data)
    if "SECRET__GEOAPIFY" in serialized or "apiKey" in serialized or "api_key" in serialized:
        raise AssertionError("Maps response leaked provider key metadata")

    return {
        "status": "passed",
        "mode": "verified_results",
        "provider": data.get("provider"),
        "required": required,
        "result_count": len(items),
        "first_result": items[0].get("name"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live Maps Geoapify REST smoke.")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--api-key", default=os.getenv("OPENMATES_TEST_ACCOUNT_API_KEY", ""))
    parser.add_argument(
        "--create-api-key-from-cli-session",
        action="store_true",
        help="Create and revoke a temporary API key using the current logged-in CLI session.",
    )
    parser.add_argument("--device-id", default=DEFAULT_DEVICE_ID)
    parser.add_argument("--query", required=True)
    parser.add_argument("--require", action="append", default=[])
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()

    api_key = args.api_key
    if not api_key and args.create_api_key_from_cli_session:
        name = f"maps-geoapify-rest-smoke-{int(time.time())}"
        with _api_key_from_cli_session(args.api_url, name) as (temporary_api_key, key_id):
            args.api_key = temporary_api_key
            args.temporary_key_id = key_id
            return _run_smoke(args)

    if not api_key:
        print("Missing OPENMATES_TEST_ACCOUNT_API_KEY or --api-key", file=sys.stderr)
        return 2

    return _run_smoke(args)


def _run_smoke(args: argparse.Namespace) -> int:
    api_key = args.api_key

    required = [_canonical_amenity(item) for item in args.require]
    payload = {
        "requests": [
            {
                "id": "maps-geoapify-live-smoke",
                "query": args.query,
                "pageSize": 10,
                "osmEnrichment": "required" if required else "auto",
                "amenityFilters": _amenity_filters(required),
            }
        ]
    }

    auth_status, _auth_body = _request_json(
        api_url=args.api_url,
        payload=payload,
        api_key=None,
        device_id=args.device_id,
        expect_auth_error=True,
    )
    if auth_status not in {401, 403}:
        raise AssertionError(f"Unauthenticated Maps app-skill call returned HTTP {auth_status}, expected 401/403")

    try:
        status, body = _request_json(
            api_url=args.api_url,
            payload=payload,
            api_key=api_key,
            device_id=args.device_id,
        )
    except RuntimeError as exc:
        key_id = getattr(args, "temporary_key_id", None)
        if not isinstance(key_id, str) or not _is_device_approval_error(exc):
            raise
        approved_devices = _approve_pending_key_devices(args.api_url, key_id, {"cli"})
        if not approved_devices:
            raise RuntimeError("No pending CLI API-key device was available to approve") from exc
        status, body = _request_json(
            api_url=args.api_url,
            payload=payload,
            api_key=api_key,
            device_id=args.device_id,
        )
    if status != 200:
        raise AssertionError(f"Authenticated Maps app-skill call returned HTTP {status}")
    summary = _validate_maps_contract(_extract_data(body), required)
    summary["api_url"] = args.api_url
    summary["auth_boundary"] = "unauthenticated_rejected"
    if args.json_output:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Maps Geoapify smoke passed: {summary['mode']} ({summary.get('result_count', 0)} results)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
