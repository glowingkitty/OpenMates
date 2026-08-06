#!/usr/bin/env python3
"""Verify deployed runtime-health behavior against the local dev Docker stack.

This script exercises the packaged verifier through the real API container and
real Celery/Redis services. Its controlled failure uses an unknown synthetic
task name only in development, leaves containers running, then requires a clean
recovery run. It never invokes model providers or mutates payment resources.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any


def subject_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "origin/dev"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def run_verifier(*, injected_worker_failure: bool = False) -> tuple[int, dict[str, Any]]:
    command = ["docker", "exec"]
    if injected_worker_failure:
        command.extend(["-e", "OPENMATES_RUNTIME_HEALTH_PROBE_TASK=runtime_health.missing_probe"])
    command.extend(["api", "python", "-m", "backend.scripts.runtime_health_verifier", "--role", "core", "--json"])
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=70)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("runtime verifier did not return one JSON document") from exc
    return result.returncode, payload


def container_is_healthy() -> bool:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}} {{.State.Health.Status}}", "api"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == "true healthy"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["dev"], required=True)
    parser.add_argument("--scenario", choices=["success", "injected-worker-failure", "billing-no-spend"], required=True)
    args = parser.parse_args()

    if args.scenario == "billing-no-spend":
        _code, payload = run_verifier()
        if payload.get("effective_mode") != "official_cloud":
            print(json.dumps({"status": "blocked", "reason": "official_cloud_overlay_unavailable", "subject_commit": subject_commit()}))
            return 2
        billing_checks = [check for check in payload["checks"] if check["id"].startswith("billing.")]
        passed = bool(billing_checks) and all(check["status"] == "passed" for check in billing_checks)
        print(json.dumps({"status": "passed" if passed else "failed", "checks": billing_checks, "subject_commit": subject_commit()}))
        return 0 if passed else 1

    if args.scenario == "success":
        code, payload = run_verifier()
        passed = code == 0 and payload.get("status") == "passed"
        print(json.dumps({"status": "passed" if passed else "failed", "result": payload, "subject_commit": subject_commit()}))
        return 0 if passed else 1

    failed_code, failed = run_verifier(injected_worker_failure=True)
    worker_check = next((check for check in failed.get("checks", []) if check["id"] == "core.worker_queue"), None)
    remained_healthy = container_is_healthy()
    recovery_code, recovery = run_verifier()
    passed = (
        failed_code != 0
        and worker_check is not None
        and worker_check["status"] == "failed"
        and remained_healthy
        and recovery_code == 0
        and recovery.get("status") == "passed"
    )
    print(json.dumps({
        "status": "passed" if passed else "failed",
        "injected_check": worker_check,
        "containers_remained_healthy": remained_healthy,
        "recovery_status": recovery.get("status"),
        "subject_commit": subject_commit(),
    }))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
