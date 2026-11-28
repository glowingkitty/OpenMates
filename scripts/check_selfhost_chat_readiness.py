#!/usr/bin/env python3
"""Probe a local self-hosted core for API readiness and record the result.

Used by .github/workflows/selfhost-smoke-rust.yml at install milestones
(volume-absent, fresh, restart). `volume-absent` runs before any install and
must find no API; every other milestone requires /health and
/v1/settings/server-status to answer with valid JSON. The result is written as
JSON to --output and a failed check exits nonzero.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "http://localhost:8000"
ABSENT_MILESTONES = {"volume-absent"}


def fetch(url: str, timeout: float = 10.0):
    """Return (http_status, body_text); status 0 when the server is unreachable."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, ""
    except (urllib.error.URLError, OSError):
        return 0, ""


def probe(base_url: str = BASE_URL) -> dict:
    health_status, _ = fetch(f"{base_url}/health")
    status_code, body = fetch(f"{base_url}/v1/settings/server-status")
    server_status = None
    if status_code == 200:
        try:
            parsed = json.loads(body)
            server_status = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            server_status = None
    return {
        "health_ok": health_status == 200,
        "server_status_ok": server_status is not None,
        "server_status": server_status,
    }


def evaluate(milestone: str, observed: dict) -> list[str]:
    errors = []
    if milestone in ABSENT_MILESTONES:
        if observed["health_ok"]:
            errors.append("API is already answering before install")
        return errors
    if not observed["health_ok"]:
        errors.append("/health did not return 200")
    if not observed["server_status_ok"]:
        errors.append("/v1/settings/server-status did not return a JSON object")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("source", "image"), required=True)
    parser.add_argument("--milestone", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args(argv)
    observed = probe(args.base_url)
    errors = evaluate(args.milestone, observed)
    result = {"mode": args.mode, "milestone": args.milestone, "ok": not errors,
              "errors": errors, **observed}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    for error in errors:
        print(f"selfhost readiness [{args.mode}/{args.milestone}]: {error}", file=sys.stderr)
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
