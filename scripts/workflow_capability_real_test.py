#!/usr/bin/env python3
"""Real dev-server Workflow capability smoke test.

This script uses the built OpenMates CLI against a real API URL and a paired CLI
session. It validates expanded enabled capabilities, deferred unavailable
reasons, help-app metadata, and representative YAML enablement diagnostics.
No mocked OpenMates API calls are used.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from workflow_real_test_helpers import resolve_cli_path, run_cli_json


EXPECTED_ENABLED = {
    "ai.ask",
    "events.search",
    "math.calculate",
    "news.search",
    "weather.forecast",
    "web.read",
    "web.search",
}
EXPECTED_DISABLED = {
    "calendar.get-events": "WORKFLOW_CONNECTED_ACCOUNT_REQUIRED",
    "tasks.search": "WORKFLOW_CLIENT_ENCRYPTED_DATA_REQUIRED",
    "images.vectorize": "WORKFLOW_FILE_OR_EMBED_INPUT_REQUIRED",
    "code.run": "WORKFLOW_RUNTIME_UNSUPPORTED",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real Workflow capability checks through the OpenMates CLI")
    parser.add_argument("--api-url", default="https://api.dev.openmates.org")
    parser.add_argument("--cli-path")
    parser.add_argument("--home")
    args = parser.parse_args()

    cli_path = resolve_cli_path(args.cli_path)
    capabilities = run_cli_json(cli_path, args.api_url, ["workflows", "capabilities"], home=args.home)
    by_id = {item["id"]: item for item in capabilities}

    missing_enabled = sorted(item for item in EXPECTED_ENABLED if not by_id.get(item, {}).get("enabled"))
    if missing_enabled:
        raise RuntimeError(f"Expected enabled capabilities missing or disabled: {missing_enabled}")
    for capability_id, reason in EXPECTED_DISABLED.items():
        capability = by_id.get(capability_id)
        if not capability or capability.get("enabled") is not False or capability.get("reason") != reason:
            raise RuntimeError(f"Expected {capability_id} disabled with {reason}, got {capability}")

    math_help = run_cli_json(cli_path, args.api_url, ["workflows", "help-app", "math.calculate"], home=args.home)
    if math_help.get("metadata", {}).get("workflow", {}).get("effect") != "compute":
        raise RuntimeError(f"math.calculate help metadata missing compute effect: {math_help}")

    with tempfile.TemporaryDirectory(prefix="openmates-workflow-capability-") as tmp:
        valid_yaml = Path(tmp) / "valid.yml"
        valid_yaml.write_text(
            """
title: Real capability validation
start_when:
  manual: {}
steps:
  - id: math
    use_app_skill: math.calculate
    input:
      expression: 2 + 2
""".strip()
            + "\n",
            encoding="utf-8",
        )
        valid = run_cli_json(cli_path, args.api_url, ["workflows", "validate", "--file", str(valid_yaml)], home=args.home)
        if valid.get("draft_valid") is not True or valid.get("enable_ready") is not True:
            raise RuntimeError(f"Expected math workflow to validate ready, got {valid}")

        deferred_yaml = Path(tmp) / "deferred.yml"
        deferred_yaml.write_text(
            """
title: Deferred capability validation
start_when:
  manual: {}
steps:
  - id: tasks
    use_app_skill: tasks.search
    input:
      query: private task text
""".strip()
            + "\n",
            encoding="utf-8",
        )
        deferred = run_cli_json(cli_path, args.api_url, ["workflows", "validate", "--file", str(deferred_yaml)], home=args.home)
        diagnostic_codes = {item.get("code") for item in deferred.get("diagnostics", [])}
        if deferred.get("enable_ready") is not False or "WORKFLOW_CAPABILITY_UNAVAILABLE" not in diagnostic_codes:
            raise RuntimeError(f"Expected deferred workflow to be unavailable, got {deferred}")

    print("PASS real Workflow capability CLI smoke test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
