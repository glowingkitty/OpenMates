#!/usr/bin/env python3
"""Verify storage-outage transitions and dev notification delivery.

The drill evaluates the CLI policy at controlled timestamps to prove one
warning, one one-hour escalation, and one recovery. It separately exercises all
requested host-owned dev delivery channels and stores only stable event names,
delivery status, and sanitized receipts.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CLI_DIR = ROOT / "frontend" / "packages" / "openmates-cli"
EVIDENCE_DIR = ROOT / "test-results" / "s3-outage-alerts"


def _subject_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "origin/dev"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _transition_drill() -> dict[str, Any]:
    module_url = (CLI_DIR / "src" / "serverHealth.ts").resolve().as_uri()
    source = f"""
      import {{ applyRuntimeCheckResults }} from {json.dumps(module_url)};
      const failed = [{{ id: 'core.object_storage', status: 'failed', required: false, failureClass: 'storage_unavailable' }}];
      const passed = [{{ id: 'core.object_storage', status: 'passed', required: false }}];
      let state;
      const events = [];
      for (const [timestamp, checks] of [
        ['2026-08-25T00:00:00.000Z', failed],
        ['2026-08-25T00:01:00.000Z', failed],
        ['2026-08-25T01:01:00.000Z', failed],
        ['2026-08-25T01:02:00.000Z', passed],
      ]) {{
        const result = applyRuntimeCheckResults(state, checks, timestamp);
        state = result.state;
        events.push(...result.events.map((event) => ({{ ...event, timestamp }})));
      }}
      console.log(JSON.stringify({{ events, finalState: state.checks['core.object_storage'] }}));
    """
    completed = subprocess.run(
        ["npx", "tsx", "--eval", source],
        cwd=CLI_DIR,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError("compiled_transition_drill_failed")
    payload = json.loads(completed.stdout)
    event_types = [event.get("type") for event in payload.get("events", [])]
    if event_types != ["service_unhealthy", "service_critical", "recovered"]:
        raise RuntimeError("unexpected_storage_transition_sequence")
    final_state = payload.get("finalState") or {}
    if final_state.get("incidentOpen") is not False or final_state.get("consecutiveFailures") != 0:
        raise RuntimeError("storage_incident_did_not_recover")
    return {
        "status": "passed",
        "events": payload.get("events"),
        "final_state": {
            "incident_open": final_state.get("incidentOpen"),
            "consecutive_failures": final_state.get("consecutiveFailures"),
        },
    }


def _delivery_drill(channels: str) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for event_kind in ("incident", "critical", "recovery"):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "verify_post_update_notifications.py"),
                "--target",
                "dev",
                "--channels",
                channels,
                "--event-kind",
                event_kind,
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("notification_delivery_drill_invalid_json") from exc
        if completed.returncode != 0 or payload.get("status") != "passed":
            raise RuntimeError(f"notification_delivery_drill_failed:{event_kind}")
        results[event_kind] = payload
    return {"status": "passed", "events": results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=["development"], required=True)
    parser.add_argument("--channels", default="email,discord,webhook")
    args = parser.parse_args()
    evidence: dict[str, Any] = {
        "environment": args.environment,
        "subject_commit": _subject_commit(),
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        evidence["transitions"] = _transition_drill()
        evidence["delivery"] = _delivery_drill(args.channels)
    except Exception as exc:
        evidence.update({"status": "failed", "failure_class": str(exc)})
    else:
        evidence["status"] = "passed"

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    evidence_path = EVIDENCE_DIR / f"development-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": evidence["status"], "evidence": str(evidence_path.relative_to(ROOT))}))
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
