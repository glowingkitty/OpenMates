#!/usr/bin/env python3
"""Verify deployed privacy-safe AI observability infrastructure.

The current milestone verifies OpenObserve trace retention from the live dev
containers without printing credentials or raw telemetry. Baseline and alert
verification are intentionally added only after seven complete dev days.
Architecture: contracts/architecture/ai-request-observability/contract.yml
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any


EXPECTED_RETENTION_DAYS = 14
MAX_RETENTION_DAYS = 30
OPENOBSERVE_CONTAINER = "openobserve"
API_CONTAINER = "api"
TRACE_STREAM = "default"


def _run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "command failed").strip())
    return result.stdout.strip()


def _container_config() -> dict[str, Any]:
    raw = _run(["docker", "inspect", OPENOBSERVE_CONTAINER])
    records = json.loads(raw)
    if len(records) != 1:
        raise RuntimeError("OpenObserve container inspection returned an unexpected result")
    return records[0].get("Config") or {}


def _global_retention_days(config: dict[str, Any]) -> int:
    prefix = "ZO_COMPACT_DATA_RETENTION_DAYS="
    values = [value[len(prefix):] for value in config.get("Env") or [] if value.startswith(prefix)]
    if len(values) != 1:
        raise RuntimeError("OpenObserve global retention is not configured exactly once")
    try:
        return int(values[0])
    except ValueError as exc:
        raise RuntimeError("OpenObserve global retention is not an integer") from exc


def _trace_stream_retention_days() -> int:
    probe = (
        "import json,os,httpx;"
        "r=httpx.get('http://openobserve:5080/api/default/streams',"
        "auth=(os.environ.get('OPENOBSERVE_ROOT_EMAIL',''),"
        "os.environ.get('OPENOBSERVE_ROOT_PASSWORD','')),timeout=30);"
        "r.raise_for_status();"
        "streams=[s for s in r.json().get('list',[]) "
        "if s.get('name')=='default' and s.get('stream_type')=='traces'];"
        "assert len(streams)==1, 'trace stream missing';"
        "print(int((streams[0].get('settings') or {}).get('data_retention') or 0))"
    )
    return int(_run(["docker", "exec", API_CONTAINER, "python", "-c", probe]))


def verify_retention() -> dict[str, Any]:
    config = _container_config()
    global_days = _global_retention_days(config)
    stream_days = _trace_stream_retention_days()
    effective_days = stream_days or global_days
    passed = effective_days == EXPECTED_RETENTION_DAYS and effective_days <= MAX_RETENTION_DAYS
    return {
        "status": "passed" if passed else "failed",
        "image": config.get("Image", "unknown"),
        "trace_stream": TRACE_STREAM,
        "stream_retention_days": stream_days,
        "inherits_global_retention": stream_days == 0,
        "global_retention_days": global_days,
        "effective_retention_days": effective_days,
        "policy_maximum_days": MAX_RETENTION_DAYS,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify AI observability infrastructure")
    parser.add_argument("command", choices=["retention"])
    parser.add_argument("--target", choices=["dev"], default="dev")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()

    try:
        result = verify_retention()
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"AI observability verification failed: {exc}", file=sys.stderr)
        return 1

    if args.json_output:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            f"{result['status'].upper()}: OpenObserve {result['image']} trace stream "
            f"retains data for {result['effective_retention_days']} days "
            f"(policy maximum {result['policy_maximum_days']} days)"
        )
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
