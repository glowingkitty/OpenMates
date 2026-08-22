#!/usr/bin/env python3
# contract-test-file: tooling
"""
OpenMatesCloud overlay boot smoke check.

This operator-run script verifies that the deployed dev API is serving as an
official-cloud overlay runtime without mutating payment state. It performs public
read-only health/status checks, sends a deliberately invalid payment webhook to
prove route registration stops at signature validation, and optionally inspects
local Docker container env for the CLI overlay markers.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError


DEFAULT_API_URL = "https://api.dev.openmates.org"
WEBHOOK_ROUTE_REGISTERED_STATUSES = {400, 401, 422}
OVERLAY_PACKAGE_ENV = "OPENMATES_CLOUD_OVERLAY_PACKAGE"
OVERLAY_ENABLED_ENV = "OPENMATES_CLOUD_OVERLAY_ENABLED"
EXPECTED_OVERLAY_PACKAGE = "OpenMatesCloud"
EXPECTED_WORKER_QUEUES = {
    "task-worker": {"email"},
    "user-init-worker": {"user_init"},
    "core-worker": {"persistence"},
    "user-tasks-worker": {"user_tasks"},
    "reminder-worker": {"reminder"},
}


class CloudOverlayBootError(RuntimeError):
    pass


def _json_request(api_url: str, path: str) -> dict[str, Any]:
    req = urllib_request.Request(
        f"{api_url.rstrip('/')}/{path.lstrip('/')}",
        method="GET",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib_request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise CloudOverlayBootError(f"GET {path} failed with HTTP {exc.code}: {body}") from exc
    except (URLError, TimeoutError) as exc:
        raise CloudOverlayBootError(f"GET {path} failed: {exc}") from exc


def _webhook_probe_status(api_url: str) -> int:
    req = urllib_request.Request(
        f"{api_url.rstrip('/')}/v1/payments/webhook",
        method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        data=b"{}",
    )
    try:
        with urllib_request.urlopen(req, timeout=30) as response:
            return response.status
    except HTTPError as exc:
        exc.read()
        return exc.code
    except (URLError, TimeoutError) as exc:
        raise CloudOverlayBootError(f"POST /v1/payments/webhook probe failed: {exc}") from exc


def _docker_env(container_name: str) -> dict[str, str]:
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{json .Config.Env}}", container_name],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise CloudOverlayBootError(
            f"docker inspect failed for {container_name}: {result.stderr.strip()}"
        )
    env_values = json.loads(result.stdout or "[]")
    return dict(item.split("=", 1) for item in env_values if "=" in item)


def _check_cli_overlay_containers() -> list[str]:
    findings: list[str] = []
    api_env = _docker_env("api")
    if api_env.get(OVERLAY_ENABLED_ENV) != "true":
        raise CloudOverlayBootError("api container does not have OPENMATES_CLOUD_OVERLAY_ENABLED=true")
    if api_env.get(OVERLAY_PACKAGE_ENV) != EXPECTED_OVERLAY_PACKAGE:
        raise CloudOverlayBootError("api container does not have the OpenMatesCloud overlay marker")
    findings.append("api overlay env present")

    for container_name in ("task-worker", "user-init-worker", "core-worker", "user-tasks-worker", "reminder-worker", "task-scheduler"):
        env = _docker_env(container_name)
        if env.get(OVERLAY_PACKAGE_ENV) != EXPECTED_OVERLAY_PACKAGE:
            raise CloudOverlayBootError(f"{container_name} missing OpenMatesCloud overlay marker")
        findings.append(f"{container_name} overlay env present")

    for container_name, expected_queues in EXPECTED_WORKER_QUEUES.items():
        worker_queues = set((_docker_env(container_name).get("CELERY_QUEUES") or "").split(","))
        if not expected_queues.issubset(worker_queues):
            raise CloudOverlayBootError(
                f"{container_name} is missing required queues: {sorted(expected_queues)}"
            )
        findings.append(f"{container_name} required queues present")
    return findings


def _redact(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("/"):
        return "<redacted-path>"
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify OpenMatesCloud overlay boot state.")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--cli-overlay", action="store_true", help="Inspect local Docker containers for CLI overlay env markers.")
    parser.add_argument("--redact", action="store_true", help="Redact local paths in JSON output.")
    args = parser.parse_args()

    try:
        health = _json_request(args.api_url, "/v1/health")
        status = _json_request(args.api_url, "/v1/settings/server-status")
        if status.get("is_self_hosted") is not False:
            raise CloudOverlayBootError("server-status does not report official-cloud runtime")
        if status.get("payment_enabled") is not True:
            raise CloudOverlayBootError("server-status does not report payment_enabled=true")

        webhook_status = _webhook_probe_status(args.api_url)
        if webhook_status not in WEBHOOK_ROUTE_REGISTERED_STATUSES:
            raise CloudOverlayBootError(
                "payment webhook route did not stop at signature validation "
                f"(HTTP {webhook_status})"
            )

        cli_overlay_findings = _check_cli_overlay_containers() if args.cli_overlay else []
        output = {
            "ok": True,
            "api_url": args.api_url,
            "health_status": health.get("status") or health.get("overall_status") or "present",
            "server_status": {
                "is_self_hosted": status.get("is_self_hosted"),
                "payment_enabled": status.get("payment_enabled"),
                "server_edition": status.get("server_edition"),
            },
            "webhook_probe_status": webhook_status,
            "cli_overlay_findings": cli_overlay_findings,
        }
        print(json.dumps(_redact(output) if args.redact else output, indent=2, sort_keys=True))
        return 0
    except CloudOverlayBootError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
