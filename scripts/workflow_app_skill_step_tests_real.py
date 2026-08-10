#!/usr/bin/env python3
"""Run real Workflow step tests for enabled app-skill capabilities.

The script creates one disabled workflow containing each enabled testable
capability returned by the dev API, then executes step-test runs through the
OpenMates CLI. Provider failures are recorded in the final report; CLI/session
and workflow infrastructure failures remain hard failures.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from workflow_real_test_helpers import dump_yaml_value, resolve_cli_path, run_cli, run_cli_json, step_id_for


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real Workflow app-skill step tests through the OpenMates CLI")
    parser.add_argument("--api-url", default="https://api.dev.openmates.org")
    parser.add_argument("--cli-path")
    parser.add_argument("--home")
    parser.add_argument("--max-paid-runs-per-skill", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0, help="Optional cap for local debugging; 0 means all testable capabilities")
    args = parser.parse_args()

    cli_path = resolve_cli_path(args.cli_path)
    capabilities = run_cli_json(cli_path, args.api_url, ["workflows", "capabilities"], home=args.home)
    selected = [item for item in capabilities if item.get("enabled") is True and item.get("metadata", {}).get("workflow", {}).get("test_allowed") is True]
    if args.limit > 0:
        selected = selected[: args.limit]
    if not selected:
        raise RuntimeError("No enabled testable workflow capabilities returned by the API")

    with tempfile.TemporaryDirectory(prefix="openmates-workflow-step-tests-") as tmp:
        workflow_file = Path(tmp) / "expanded-step-tests.yml"
        workflow_file.write_text(_workflow_yaml(selected), encoding="utf-8")
        created = run_cli_json(cli_path, args.api_url, ["workflows", "create", "--file", str(workflow_file)], home=args.home, timeout_seconds=180)
        workflow_id = created.get("workflow", {}).get("id")
        if not workflow_id:
            raise RuntimeError(f"Workflow create did not return an id: {created}")

        report: list[dict[str, object]] = []
        try:
            for index, capability in enumerate(selected):
                capability_id = capability["id"]
                step_id = step_id_for(capability_id, index)
                result = run_cli_json(
                    cli_path,
                    args.api_url,
                    ["workflows", "step-test", workflow_id, step_id, "--yes"],
                    home=args.home,
                    timeout_seconds=240,
                )
                node_runs = result.get("node_runs") if isinstance(result, dict) else []
                report.append(
                    {
                        "capability_id": capability_id,
                        "step_id": step_id,
                        "run_id": result.get("id"),
                        "status": result.get("status"),
                        "node_status": node_runs[0].get("status") if node_runs else None,
                        "error_code": node_runs[0].get("error_code") if node_runs else None,
                    }
                )
        finally:
            run_cli(cli_path, args.api_url, ["workflows", "delete", workflow_id, "--yes"], home=args.home, timeout_seconds=60)

    print(json.dumps({"tested": len(report), "results": report}, indent=2, sort_keys=True))
    return 0


def _workflow_yaml(capabilities: list[dict[str, object]]) -> str:
    lines = [
        "title: Expanded app-skill step tests",
        "description: Real step-test matrix for enabled workflow capabilities.",
        "start_when:",
        "  manual: {}",
        "steps:",
    ]
    for index, capability in enumerate(capabilities):
        capability_id = str(capability["id"])
        workflow = capability.get("metadata", {}).get("workflow", {})  # type: ignore[union-attr]
        example = workflow.get("test_example_input") if isinstance(workflow, dict) else {}
        lines.extend(
            [
                f"  - id: {step_id_for(capability_id, index)}",
                f"    use_app_skill: {capability_id}",
                "    input:",
                dump_yaml_value(example or {}, 6),
            ]
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
