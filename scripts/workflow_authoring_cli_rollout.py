#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Post-rollout CLI proof using only disposable disabled workflows.

Run only after the coordinated dev rollout. Pair the intended engineering dev
account into an isolated OPENMATES_STATE_DIR first; this script never logs in,
enables a workflow, or executes a workflow. It deletes only IDs absent from the
initial account listing and reports any cleanup failure. The first case uses
the source SDK session for one SSE request to measure validated previews;
remaining cases exercise CLI input commands.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4


def cli_json(command: str, api_url: str, state_dir: Path, args: list[str], label: str) -> tuple[Any, float]:
    started = time.perf_counter()
    completed = subprocess.run(
        [command, *args, "--api-url", api_url, "--json"],
        env={**os.environ, "OPENMATES_STATE_DIR": str(state_dir), "OPENMATES_PROFILE": ""},
        capture_output=True, text=True, check=False, timeout=180,
    )
    wall = round(time.perf_counter() - started, 3)
    if completed.returncode:
        # CLI failures can contain user text; do not copy stdout/stderr into a report.
        raise RuntimeError(f"{label} failed (CLI exit {completed.returncode})")
    try:
        return json.loads(completed.stdout), wall
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} returned invalid JSON") from exc


def streamed_input(api_url: str, state_dir: Path, text: str, label: str) -> tuple[dict[str, Any], float, dict[str, Any]]:
    helper = Path(__file__).with_name("workflow_authoring_stream_timing.mjs")
    started = time.perf_counter()
    completed = subprocess.run(
        ["node", str(helper)],
        input=json.dumps({"api_url": api_url, "text": text, "timezone": "UTC"}),
        env={**os.environ, "OPENMATES_STATE_DIR": str(state_dir), "OPENMATES_PROFILE": ""},
        capture_output=True, text=True, check=False, timeout=330,
    )
    wall = round(time.perf_counter() - started, 3)
    if completed.returncode:
        raise RuntimeError(f"{label} stream failed (exit {completed.returncode})")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} stream returned invalid JSON") from exc
    if not isinstance(payload.get("session"), dict) or not isinstance(payload.get("stream_timing"), dict):
        raise RuntimeError(f"{label} stream returned no session or timing")
    return payload["session"], wall, payload["stream_timing"]


def workflow_list(call: Any) -> list[dict[str, Any]]:
    result, _ = call(["workflows", "list"], "list workflows")
    if not isinstance(result, list):
        raise AssertionError("Workflow list was not an array")
    return result


def assert_existing_workflows_unchanged(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> None:
    after_by_id = {item["id"]: item for item in after}
    for original in before:
        current = after_by_id.get(original["id"])
        if current is None or any(current.get(field) != original.get(field)
                                  for field in ("current_version_id", "enabled", "title")):
            raise AssertionError("Mixed invalid authoring changed an existing workflow")


def authored_workflows(result: dict[str, Any]) -> list[dict[str, Any]]:
    workflows = result.get("workflows") or ([result["workflow"]] if result.get("workflow") else [])
    if not isinstance(workflows, list):
        raise AssertionError("Authoring result had no workflow list")
    return workflows


def completed_input_result(
    call: Any, result: dict[str, Any], wall: float, label: str,
) -> tuple[dict[str, Any], float, float]:
    if not isinstance(result, dict):
        raise AssertionError(f"{label} returned no session object")
    initial_metrics = result.get("authoring_metrics") or {}
    queued = 0.0
    if result.get("status") == "queued" and isinstance(result.get("session_id"), str):
        began = time.perf_counter()
        while time.perf_counter() - began < 120:
            time.sleep(2)
            result, _ = call(["workflows", "input-show", result["session_id"]], f"{label} status")
            if result.get("status") != "queued":
                break
        queued = round(time.perf_counter() - began, 3)
    if isinstance(initial_metrics, dict) and isinstance(result.get("authoring_metrics"), dict):
        result["authoring_metrics"] = {**initial_metrics, **result["authoring_metrics"]}
    return result, wall, queued


def completed_input(call: Any, args: list[str], label: str) -> tuple[dict[str, Any], float, float]:
    result, wall = call(args, label)
    return completed_input_result(call, result, wall, label)


def report_case(
    label: str, result: dict[str, Any], wall: float, queue: float = 0.0,
    stream_timing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = result.get("authoring_metrics") or {}
    attempts = metrics.get("generation_attempts") or []

    def numbers(value: Any) -> dict[str, int | float]:
        if not isinstance(value, dict):
            return {}
        return {key: item for key, item in value.items()
                if isinstance(key, str) and len(key) <= 64
                and isinstance(item, (int, float)) and not isinstance(item, bool)}

    def reason(value: Any) -> str | None:
        return value if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", value) else None

    return {
        "case": label,
        "status": result.get("status"),
        "session_id": result.get("session_id") if re.fullmatch(
            r"[0-9a-fA-F-]{36}", str(result.get("session_id") or "")) else None,
        "error_code": result.get("error_code") if re.fullmatch(
            r"[A-Z][A-Z0-9_]{0,79}", str(result.get("error_code") or "")) else None,
        "partial_reason": result.get("partial_reason") if result.get("partial_reason") in {
            "stopped", "provider_error"} else None,
        "cli_wall_seconds": wall if stream_timing is None else None,
        "client_stream_wall_seconds": wall if stream_timing is not None else None,
        "queue_wait_seconds": queue,
        "planning_seconds": metrics.get("total_seconds"),
        "service_seconds": metrics.get("service_seconds"),
        "service_stages_seconds": numbers(metrics.get("service_stages_seconds")),
        "service_poll_counts": numbers(metrics.get("service_poll_counts")),
        "estimated_cost_usd": metrics.get("estimated_cost_usd"),
        "cost_estimate_complete": metrics.get("cost_estimate_complete") if isinstance(
            metrics.get("cost_estimate_complete"), bool) else None,
        "input_tokens": metrics.get("input_tokens"),
        "output_tokens": metrics.get("output_tokens"),
        "planner_stages": [{"stage": reason(stage.get("stage")), **{
            key: stage.get(key) for key in ("seconds", "estimated_cost_usd", "input_tokens",
                                        "output_tokens", "jev_calls")
            if isinstance(stage.get(key), (int, float))}}
            for stage in (metrics.get("stages") or []) if isinstance(stage, dict)],
        "last_failure_stage": reason(metrics.get("last_failure_stage")),
        "last_failure_reason_code": reason(metrics.get("last_failure_reason_code")),
        "generation_attempts": [{key: attempt.get(key) for key in (
            "seconds", "first_component_ms", "component_count", "input_tokens", "output_tokens",
            "thinking_tokens", "estimated_cost_usd") if isinstance(attempt.get(key), (int, float))}
            | {"failure_reason_code": reason(attempt.get("failure_reason_code"))}
            for attempt in attempts if isinstance(attempt, dict)],
        "workflow_count": len(authored_workflows(result)),
        **({"stream_timing": {key: value for key, value in stream_timing.items()
                              if key in {"first_started_seconds", "first_header_seconds",
                                         "first_validated_action_seconds", "first_preview_seconds",
                                         "final_event_seconds", "validated_preview_count"}
                              and (value is None or isinstance(value, (int, float)))}}
           if stream_timing is not None else {}),
    }


def write_private_report(path: Path, report: dict[str, Any]) -> None:
    """Persist bounded progress before assertions or process exit can discard it."""
    payload = json.dumps(report, indent=2, sort_keys=True).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def graph_without_schedule(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = [node for node in graph.get("nodes", []) if node.get("type") != "schedule_trigger"]
    return {"nodes": nodes, "edges": graph.get("edges"), "variables": graph.get("variables")}


def schedule(graph: dict[str, Any]) -> dict[str, Any]:
    triggers = [node for node in graph.get("nodes", []) if node.get("type") == "schedule_trigger"]
    if len(triggers) != 1:
        raise AssertionError("Expected exactly one schedule trigger")
    return triggers[0].get("config", {}).get("schedule", {})


def event_request(graph: dict[str, Any]) -> dict[str, Any]:
    events = [node for node in graph.get("nodes", []) if node.get("type") == "app_skill_action"
              and node.get("config", {}).get("app_id") == "events"
              and node.get("config", {}).get("skill_id") == "search"]
    if len(events) != 1:
        raise AssertionError("Expected exactly one events search action")
    requests = events[0].get("config", {}).get("input", {}).get("requests")
    if not isinstance(requests, list) or len(requests) != 1 or not isinstance(requests[0], dict):
        raise AssertionError("Expected exactly one events search request")
    return requests[0]


def graph_without_event_topic_and_city(graph: dict[str, Any]) -> dict[str, Any]:
    comparable = deepcopy(graph)
    request = event_request(comparable)
    request.pop("query", None)
    request.pop("location", None)
    return comparable


def run(args: argparse.Namespace) -> dict[str, Any]:
    if os.getenv("OPENMATES_WORKFLOW_LIVE_INFERENCE") != "1" or not args.confirm_live_inference:
        raise RuntimeError("Live inference proof requires the rollout opt-in flag and environment gate")
    parsed_url = urlparse(args.api_url)
    if parsed_url.scheme != "https" or parsed_url.netloc != "api.dev.openmates.org":
        raise ValueError("This proof targets only https://api.dev.openmates.org")
    state_dir = args.state_dir.resolve(strict=True)
    if not state_dir.is_dir():
        raise ValueError("--state-dir must be an existing isolated CLI state directory")

    def call(cli_args: list[str], label: str) -> tuple[Any, float]:
        return cli_json(args.cli, args.api_url, state_dir, cli_args, label)

    identity, _ = call(["whoami"], "check account")
    if identity.get("username") != args.expected_username:
        raise RuntimeError("Isolated CLI state is logged into a different account")
    initial_ids = {item["id"] for item in workflow_list(call)}
    nonce = uuid4().hex[:8]
    prefix = f"CLI rollout {nonce}"
    created_ids: set[str] = set()
    cases: list[dict[str, Any]] = []
    report_path = state_dir / f"workflow-rollout-{nonce}.json"
    report: dict[str, Any] = {"nonce": nonce, "selected_case": args.case,
                              "run_state": "running", "cases": cases,
                              "estimated_total_cost_usd": 0.0}

    def persist() -> None:
        report["estimated_total_cost_usd"] = round(sum(
            float(case.get("estimated_cost_usd") or 0) for case in cases), 8)
        write_private_report(report_path, report)

    def record(label: str, result: dict[str, Any], wall: float, queue: float = 0.0,
               stream_timing: dict[str, Any] | None = None) -> None:
        # Record only server-owned IDs and bounded numeric metrics. A failed
        # assertion must still leave enough evidence and cleanup IDs behind.
        for workflow in authored_workflows(result):
            workflow_id = workflow.get("id")
            if isinstance(workflow_id, str) and workflow_id not in initial_ids:
                created_ids.add(workflow_id)
        cases.append(report_case(label, result, wall, queue, stream_timing))
        persist()
        if cases[-1]["session_id"] is None:
            raise AssertionError(f"{label} returned no session ID")

    persist()

    def capture(result: dict[str, Any]) -> list[dict[str, Any]]:
        workflows = authored_workflows(result)
        for workflow in workflows:
            workflow_id = workflow.get("id")
            if not isinstance(workflow_id, str) or workflow_id in initial_ids:
                raise AssertionError("Authoring returned an existing or missing workflow ID")
            created_ids.add(workflow_id)
            detail, _ = call(["workflows", "show", workflow_id], "verify saved workflow")
            if detail.get("id") != workflow_id or detail.get("enabled") is not False:
                raise AssertionError("Authored workflow was not durably saved disabled")
        return workflows

    try:
        if args.case in {"all", "short_default"}:
            short, wall, stream_timing = streamed_input(
                args.api_url, state_dir, f"Weekly AI event search for Berlin. Name it {prefix} events.", "short default")
            short, wall, queue = completed_input_result(call, short, wall, "short default")
            record("short_default", short, wall, queue, stream_timing)
            short_workflows = capture(short)
            if short.get("status") != "executed":
                raise AssertionError(f"Short default status: {short.get('status')}")
            if len(short_workflows) != 1 or short_workflows[0].get("enabled") is not False:
                raise AssertionError("Short default did not save one disabled workflow")
            short_graph = short_workflows[0]["graph"]
            short_schedule = schedule(short_graph)
            if (short_schedule.get("type") != "weekly"
                    or short_schedule.get("time") != "09:00"
                    or "monday" not in short_schedule.get("weekdays", [])
                    or not any(
                node.get("type") == "app_skill_action"
                and node.get("config", {}).get("app_id") == "events"
                and node.get("config", {}).get("skill_id") == "search"
                for node in short_graph.get("nodes", [])
            )):
                raise AssertionError("Short default did not schedule a Monday 09:00 events search")

        if args.case in {"all", "remaining", "spoken_correction"}:
            spoken, wall, queue = completed_input(call, ["workflows", "input",
                f"Every Tuesday at 8 in Madrid—no, make that Thursday at 9 in Lisbon—find local tech meetups and send me a chat summary. Name it {prefix} spoken."], "spoken correction")
            record("spoken_correction", spoken, wall, queue)
            spoken_workflows = capture(spoken)
            if spoken.get("status") != "executed":
                raise AssertionError(f"Spoken correction status: {spoken.get('status')}")
            if len(spoken_workflows) != 1 or spoken_workflows[0].get("enabled") is not False:
                raise AssertionError("Spoken correction did not save one disabled workflow")
            spoken_schedule = schedule(spoken_workflows[0]["graph"])
            if (spoken_schedule.get("time") != "09:00"
                    or spoken_schedule.get("timezone") != "Europe/Lisbon"
                    or "thursday" not in spoken_schedule.get("weekdays", [])):
                raise AssertionError("Spoken correction did not use the final time and city")

        if args.case in {"all", "remaining", "structural"}:
            baseline_yaml = state_dir / f"workflow-rollout-{nonce}.yml"
            baseline_yaml.write_text(f"""title: {prefix} undo guard
start_when:
  schedule:
    type: weekly
    weekdays: [monday]
    time: '08:00'
    timezone: Europe/Berlin
steps:
  - id: events
    use_app_skill: events.search
    input:
      requests:
        - query: AI
          providers: [Luma, Eventbrite]
          location: Berlin
          event_type: PHYSICAL
          start_date:
            $date: next_week_start
          end_date:
            $date: next_week_end
          count: 10
  - id: report
    send_chat_message:
      title: {prefix} message
      message: "Synthetic events: {{{{steps.events.results}}}}"
      blocks:
        - id: events
          label: Synthetic event results
          source: $nodes.events.output.results
""", encoding="utf-8")
            baseline, _ = call(["workflows", "create", "--file", str(baseline_yaml)], "create undo guard baseline")
            guard_id = baseline["workflow"]["id"]
            if guard_id in initial_ids:
                raise AssertionError("Undo guard baseline reused an existing workflow")
            created_ids.add(guard_id)
            original = baseline["workflow"]
            edited, wall, queue = completed_input(call, ["workflows", "input",
                "Change only this workflow's schedule to Fridays at 10:15 Europe/Berlin. Preserve its message and all other actions.",
                "--workflow-id", guard_id], "schedule-only edit")
            record("schedule_only_edit", edited, wall, queue)
            if edited.get("status") != "executed":
                raise AssertionError(f"Schedule edit status: {edited.get('status')}")
            changed = authored_workflows(edited)
            if len(changed) != 1 or changed[0].get("id") != guard_id:
                raise AssertionError("Schedule edit touched the wrong workflow")
            if graph_without_schedule(changed[0]["graph"]) != graph_without_schedule(original["graph"]):
                raise AssertionError("Schedule edit changed a non-trigger field")
            changed_schedule = schedule(changed[0]["graph"])
            if changed_schedule.get("time") != "10:15" or "friday" not in changed_schedule.get("weekdays", []):
                raise AssertionError("Schedule edit did not apply Friday at 10:15")

            app_edited, wall, queue = completed_input(call, ["workflows", "input",
                "For this workflow, change the event search city from Berlin to Lisbon and the topic from AI to robotics. "
                "Keep the schedule, other app inputs, chat message, node IDs, and edges unchanged.",
                "--workflow-id", guard_id], "app-parameter edit")
            record("app_parameter_edit", app_edited, wall, queue)
            if app_edited.get("status") != "executed":
                raise AssertionError(f"App-parameter edit status: {app_edited.get('status')}")
            app_workflows = authored_workflows(app_edited)
            if len(app_workflows) != 1 or app_workflows[0].get("id") != guard_id:
                raise AssertionError("App-parameter edit touched the wrong workflow")
            app_graph = app_workflows[0]["graph"]
            request = event_request(app_graph)
            if request.get("location") != "Lisbon" or request.get("query") != "robotics":
                raise AssertionError("App-parameter edit did not change the requested city and topic")
            if graph_without_event_topic_and_city(app_graph) != graph_without_event_topic_and_city(changed[0]["graph"]):
                raise AssertionError("App-parameter edit changed unrelated inputs, nodes, or edges")

            batch, wall, queue = completed_input(call, ["workflows", "input",
                f"Create two separate disabled workflows: {prefix} Monday sends a chat reminder every Monday at 11 UTC to review notes; {prefix} Thursday sends a chat reminder every Thursday at 12 UTC to archive notes."], "two-create batch")
            record("two_create_atomic", batch, wall, queue)
            if batch.get("status") != "executed":
                raise AssertionError(f"Two-create batch status: {batch.get('status')}")
            batch_workflows = capture(batch)
            if (len(batch_workflows) != 2 or len({item["id"] for item in batch_workflows}) != 2
                    or any(item.get("enabled") is not False for item in batch_workflows)):
                raise AssertionError("Two-create batch did not save exactly two disabled workflows")

            before_invalid = workflow_list(call)
            before_invalid_ids = {item["id"] for item in before_invalid}
            invalid, wall, queue = completed_input(call, ["workflows", "input",
                f"Create two workflows: {prefix} valid sends a Monday chat reminder, and {prefix} invalid posts a Friday digest to Slack."], "mixed invalid batch")
            record("mixed_invalid_partial_or_failed", invalid, wall, queue)
            after_invalid = workflow_list(call)
            for item in after_invalid:
                if item["id"] not in before_invalid_ids:
                    created_ids.add(item["id"])
            assert_existing_workflows_unchanged(before_invalid, after_invalid)
            new_invalid_ids = {item["id"] for item in after_invalid} - before_invalid_ids
            if invalid.get("status") == "draft":
                partial_workflows = authored_workflows(invalid)
                if (invalid.get("partial_reason") != "provider_error" or not invalid.get("partial_warning")
                        or not partial_workflows or new_invalid_ids != {item["id"] for item in partial_workflows}):
                    raise AssertionError("Invalid batch did not report its saved valid prefix")
                if any(item.get("enabled") is not False for item in partial_workflows):
                    raise AssertionError("Invalid batch saved an enabled partial workflow")
            elif invalid.get("status") != "failed" or new_invalid_ids:
                raise AssertionError("Invalid batch had an unexpected terminal state")
            if any(node.get("config", {}).get("app_id") == "slack" for workflow in authored_workflows(invalid)
                   for node in workflow["graph"].get("nodes", [])):
                raise AssertionError("Invalid Slack delivery was retained")

            baseline_yaml.write_text(baseline_yaml.read_text(encoding="utf-8").replace(
                "query: AI", "query: Later manual synthetic topic"), encoding="utf-8")
            later, _ = call(["workflows", "update", guard_id, "--file", str(baseline_yaml)], "make later manual edit")
            if later["workflow"]["id"] != guard_id:
                raise AssertionError("Manual edit touched wrong workflow")
            undo, undo_wall = call(["workflows", "input-undo", app_edited["session_id"]], "guarded undo")
            cases.append({"case": "guarded_undo", "status": undo.get("status"), "error_code": undo.get("error_code"),
                          "cli_wall_seconds": undo_wall, "queue_wait_seconds": 0.0, "estimated_cost_usd": 0.0})
            persist()
            after_undo, _ = call(["workflows", "show", guard_id], "verify guarded undo")
            if undo.get("error_code") != "WORKFLOW_INPUT_UNDO_CONFLICT":
                raise AssertionError("Undo did not reject a newer manual edit")
            if after_undo.get("current_version_id") != later["workflow"].get("current_version_id"):
                raise AssertionError("Undo changed the newer workflow version")
        report["run_state"] = "complete"
        persist()
        return {**report, "report_path": str(report_path)}
    except Exception as exc:
        report["run_state"] = "failed"
        report["failure_type"] = type(exc).__name__
        persist()
        raise
    finally:
        cleanup_errors: list[str] = []
        try:
            for workflow in workflow_list(call):
                if workflow["id"] not in initial_ids and prefix in str(workflow.get("title") or ""):
                    created_ids.add(workflow["id"])
        except Exception:
            pass
        for workflow_id in sorted(created_ids, reverse=True):
            try:
                call(["workflows", "disable", workflow_id], "disable disposable workflow")
            except Exception:
                pass
            try:
                call(["workflows", "delete", workflow_id, "--yes"], "delete disposable workflow")
            except Exception:
                cleanup_errors.append(workflow_id)
        if "baseline_yaml" in locals():
            baseline_yaml.unlink(missing_ok=True)
        if cleanup_errors:
            report["run_state"] = "cleanup_failed"
            report["cleanup_required_workflow_ids"] = cleanup_errors
            persist()
            print(json.dumps({"cleanup_required_workflow_ids": cleanup_errors}), file=sys.stderr)
            raise RuntimeError("Disposable workflow cleanup failed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="https://api.dev.openmates.org")
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--expected-username", required=True)
    parser.add_argument("--cli", default=str(
        Path(__file__).resolve().parents[1] / "frontend/packages/openmates-cli/dist/cli.js"))
    parser.add_argument("--confirm-live-inference", action="store_true")
    parser.add_argument("--case", choices=("all", "short_default", "remaining",
                                           "spoken_correction", "structural"), default="all",
                        help="Run a bounded case; remaining combines spoken correction and structural checks")
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
