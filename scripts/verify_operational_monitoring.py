#!/usr/bin/env python3
"""
Run the real packaged CLI operational-report delivery path against Docker.

The verifier builds the local CLI, requests an explicitly labeled test report,
checks independent channel receipts, and stores only redacted evidence. It does
not inspect secrets or treat process exit alone as proof of delivery.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI_DIR = ROOT / "frontend" / "packages" / "openmates-cli"
EVIDENCE_DIR = ROOT / "test-results" / "operational-monitoring"
TARGET_ENVIRONMENTS = {"dev": "development", "self-host": "self_host", "prod": "production"}
VALID_CHANNELS = {"email", "discord"}


def _parse_output(stdout: str) -> dict:
    decoder = json.JSONDecoder()
    for index, character in enumerate(stdout):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(stdout[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("command") == "monitoring digest":
            return value
    raise ValueError("CLI did not return a structured operational-report result")


def _receipts_accepted(result: dict, *, channels: set[str], environment: str, returncode: int) -> bool:
    receipts = result.get("receipts") or []
    return (
        result.get("deliveryState") == "accepted"
        and {receipt.get("channel") for receipt in receipts} == channels
        and all(receipt.get("environment") == environment for receipt in receipts)
        and all(receipt.get("state") == "accepted" for receipt in receipts)
        and returncode == 0
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=sorted(TARGET_ENVIRONMENTS), required=True)
    parser.add_argument("--window-hours", type=int, choices=[24], default=24)
    parser.add_argument("--send", default="email,discord")
    parser.add_argument("--role", choices=["core", "upload", "preview"], default="core")
    parser.add_argument("--path", type=Path, default=ROOT)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--allow-production", action="store_true")
    args = parser.parse_args()

    if args.target == "prod" and not args.allow_production:
        parser.error("production delivery requires --allow-production after explicit rollout approval")
    channels = {item.strip() for item in args.send.split(",") if item.strip()}
    if not channels or channels - VALID_CHANNELS:
        parser.error("--send must contain email, discord, or both")

    if not args.skip_build:
        subprocess.run(["npm", "run", "build"], cwd=CLI_DIR, check=True)
    command = [
        "node", str(CLI_DIR / "dist" / "cli.js"), "server", "monitoring", "digest",
        "--path", str(args.path.resolve()), "--role", args.role,
        "--channel", ",".join(sorted(channels)), "--test", "--json",
    ]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    try:
        result = _parse_output(completed.stdout)
    except ValueError as error:
        print(f"FAIL: {error}")
        return 1

    expected_environment = TARGET_ENVIRONMENTS[args.target]
    receipts = result.get("receipts") or []
    accepted = _receipts_accepted(
        result, channels=channels, environment=expected_environment, returncode=completed.returncode,
    )
    evidence = {
        "target": args.target,
        "environment": expected_environment,
        "window_hours": args.window_hours,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "accepted": accepted,
        "report_id": result.get("reportId"),
        "report_sha256": result.get("reportSha256"),
        "receipts": receipts,
    }
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    evidence_path = EVIDENCE_DIR / f"verification-{args.target}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"{'PASS' if accepted else 'FAIL'}: {evidence_path.relative_to(ROOT)}")
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
