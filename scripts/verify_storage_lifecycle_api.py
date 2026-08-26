#!/usr/bin/env python3
"""Verify the internal regional-storage API contract on the real dev runtime.

Host mode delegates into the API container so the internal token never crosses
the container boundary. Runtime mode checks missing-token denial and authorized
sanitized health output; object replication itself is proven by the separate
real CLI image-chat verifier.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]


def validate_health_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the sanitized internal health response without private data."""
    required = {
        "configured_regions",
        "regions",
        "pending_replication",
        "pending_deletion",
        "result_truncated",
    }
    if not required.issubset(payload):
        raise RuntimeError("regional_health_fields_missing")
    configured = payload["configured_regions"]
    if not isinstance(configured, list) or not configured:
        raise RuntimeError("configured_regions_missing")
    return {
        "configured_region_count": len(configured),
        "health_row_count": len(payload["regions"]),
        "pending_replication": int(payload["pending_replication"]),
        "pending_deletion": int(payload["pending_deletion"]),
        "result_truncated": bool(payload["result_truncated"]),
    }


def _runtime_verify() -> dict[str, Any]:
    token = os.getenv("INTERNAL_API_SHARED_TOKEN")
    if not token:
        raise RuntimeError("internal_token_unavailable")
    url = "http://127.0.0.1:8000/internal/storage/health"
    denied = httpx.get(url, timeout=15)
    if denied.status_code != 401:
        raise RuntimeError("missing_internal_token_not_denied")
    authorized = httpx.get(
        url,
        headers={"X-Internal-Service-Token": token},
        timeout=30,
    )
    if authorized.status_code != 200:
        raise RuntimeError(f"authorized_health_failed:{authorized.status_code}")
    return {
        "status": "passed",
        "access_model": "internal_only",
        "missing_token_status": denied.status_code,
        **validate_health_payload(authorized.json()),
        "object_keys_in_output": False,
    }


def _host_verify(api_url: str) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "docker",
            "exec",
            "api",
            "python",
            "/app/scripts/verify_storage_lifecycle_api.py",
            "--runtime",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError("runtime_api_verification_failed")
    report = json.loads(completed.stdout)
    try:
        public = httpx.get(f"{api_url.rstrip('/')}/internal/storage/health", timeout=15)
    except httpx.RequestError:
        report.update({
            "status": "blocked",
            "failure_class": "public_ingress_unreachable",
            "public_ingress_status": "unreachable",
        })
        return report
    if public.status_code != 404:
        raise RuntimeError(f"internal_route_publicly_reachable:{public.status_code}")
    report["public_ingress_status"] = public.status_code
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", choices=("dev",), default="dev")
    parser.add_argument("--scenario", choices=("all",), default="all")
    parser.add_argument("--api-url", default="https://api.dev.openmates.org")
    parser.add_argument("--runtime", action="store_true")
    args = parser.parse_args()
    try:
        report = _runtime_verify() if args.runtime else _host_verify(args.api_url)
    except Exception as exc:
        report = {
            "status": "failed",
            "failure_class": str(exc),
            "object_keys_in_output": False,
        }
        print(json.dumps(report, separators=(",", ":")))
        return 1
    print(json.dumps(report, separators=(",", ":")))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
