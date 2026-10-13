#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in real-dev proof of natural-language scheduled Berlin–Hamburg train Workflows.

Requires an empty private /tmp state directory, a repository session, disposable
test-account credentials, and a built CLI. Never dispatch this in CI. The real
scheduler must create the runs; this script never invokes `workflows run`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from workflow_real_test_helpers import resolve_cli_path, run_cli_json

try:
    from scripts import sessions
except ModuleNotFoundError:
    import sessions


API_URL = "https://api.dev.openmates.org"
ZONE = ZoneInfo("Europe/Berlin")
TERMINAL = {"completed", "failed", "cancelled", "waiting"}


class ProofError(RuntimeError):
    """A bounded, content-free proof failure code."""


def cli(cli_path: Path, args: list[str], label: str, timeout: int = 120):
    try:
        return run_cli_json(cli_path, API_URL, args, timeout_seconds=timeout)
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        raise ProofError(f"{label}_cli_failed") from exc


def ident(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProofError(f"{label}_missing")
    return value


def author(cli_path: Path, project_id: str, prompt: str, label: str, created_ids: list[str]) -> dict:
    result = cli(cli_path, ["workflows", "input", prompt, "--project-id", project_id,
                            "--timezone", "Europe/Berlin", "--idempotency-key", str(uuid4())], label, 240)
    deadline = time.monotonic() + 180
    while isinstance(result, dict) and result.get("status") == "queued" and time.monotonic() < deadline:
        time.sleep(3)
        result = cli(cli_path, ["workflows", "input-show", ident(result.get("session_id"), "authoring_session")],
                     f"{label}_status")
    if not isinstance(result, dict) or result.get("status") != "executed":
        raise ProofError(f"{label}_not_executed")
    workflows = result.get("workflows")
    if not isinstance(workflows, list):
        workflows = [result["workflow"]] if isinstance(result.get("workflow"), dict) else []
    for item in workflows:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
            created_ids.append(item["id"])
    workflow = workflows[0] if len(workflows) == 1 else None
    if not isinstance(workflow, dict) or workflow.get("enabled") is not False:
        raise ProofError(f"{label}_not_one_disabled_workflow")
    return workflow


def check_graph(workflow: dict, kind: str, expected: datetime) -> str:
    nodes = (workflow.get("graph") or {}).get("nodes")
    if not isinstance(nodes, list):
        raise ProofError(f"{kind}_graph_missing")
    nodes = [node for node in nodes if isinstance(node, dict)]
    triggers = [node for node in nodes if node.get("type") == "schedule_trigger"]
    travels = [node for node in nodes if node.get("type") == "app_skill_action"
               and (node.get("config") or {}).get("app_id") == "travel"
               and (node.get("config") or {}).get("skill_id") == "search_connections"]
    deliveries = [node for node in nodes if node.get("type") == "send_chat_message"]
    if len(triggers) != 1 or len(travels) != 1 or len(deliveries) != 1:
        raise ProofError(f"{kind}_graph_shape")
    schedule = (triggers[0].get("config") or {}).get("schedule") or {}
    if schedule.get("type") != kind or schedule.get("timezone") != "Europe/Berlin":
        raise ProofError(f"{kind}_schedule_type_or_zone")
    if kind == "once":
        try:
            actual = datetime.fromisoformat(str(schedule.get("at"))).astimezone(UTC)
        except (ValueError, TypeError) as exc:
            raise ProofError("once_schedule_time_invalid") from exc
        if actual != expected.astimezone(UTC):
            raise ProofError("once_schedule_time_mismatch")
    else:
        if schedule.get("time") != expected.strftime("%H:%M"):
            raise ProofError("daily_schedule_time_mismatch")
        try:
            start = datetime.fromisoformat(str(schedule.get("starts_at"))).astimezone(UTC)
        except (ValueError, TypeError) as exc:
            raise ProofError("daily_start_time_invalid") from exc
        if start != expected.astimezone(UTC):
            raise ProofError("daily_start_time_mismatch")
    data = (travels[0].get("config") or {}).get("input") or {}
    requests = data.get("requests")
    if not isinstance(requests, list) or len(requests) != 1:
        raise ProofError(f"{kind}_train_request_shape")
    request = requests[0]
    if not isinstance(request, dict):
        raise ProofError(f"{kind}_train_request_shape")
    legs = request.get("legs") or [request]
    if not isinstance(legs, list) or len(legs) != 1 or not isinstance(legs[0], dict):
        raise ProofError(f"{kind}_train_leg_shape")
    leg = legs[0]
    if leg.get("origin") != "Berlin" or leg.get("destination") != "Hamburg" or request.get("transport_methods") != ["train"]:
        raise ProofError(f"{kind}_train_route_mismatch")
    if kind == "daily" and leg.get("date") != {"$date": "tomorrow", "format": "date"}:
        raise ProofError("daily_departure_not_dynamic_tomorrow")
    if kind == "once" and leg.get("date") != (expected.astimezone(ZONE).date() + timedelta(days=1)).isoformat():
        raise ProofError("once_departure_date_mismatch")
    delivery_config = deliveries[0].get("config") or {}
    blocks = delivery_config.get("blocks") or []
    if not any(isinstance(block, dict) and str(block.get("source", "")).endswith(".output.results")
               and str(block.get("source", "")).startswith(f"$nodes.{travels[0]['id']}.") for block in blocks):
        raise ProofError(f"{kind}_selected_results_not_delivered")
    return ident(travels[0].get("id"), "travel_node")


def scheduled_runs(cli_path: Path, workflow_id: str) -> list[dict]:
    result = cli(cli_path, ["workflows", "runs", workflow_id], "list_runs")
    if not isinstance(result, list):
        raise ProofError("run_list_invalid")
    return [item for item in result if isinstance(item, dict) and item.get("trigger_type") == "schedule"]


def result_count(node: dict) -> int:
    output = node.get("output_summary") or {}
    raw = output.get("raw") if isinstance(output, dict) else None
    candidates = [raw, output]
    for item in candidates:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("result_count"), int):
            return item["result_count"]
        groups = item.get("results")
        if isinstance(groups, list):
            return sum(group.get("result_count", 0) for group in groups
                       if isinstance(group, dict) and isinstance(group.get("result_count"), int))
    return 0


def wait_for_run(cli_path: Path, workflow_id: str, travel_id: str, due_at: int,
                 deadline: float) -> tuple[str, int, int]:
    while time.monotonic() < deadline:
        runs = scheduled_runs(cli_path, workflow_id)
        if len(runs) > 1:
            raise ProofError("duplicate_scheduled_runs")
        if runs:
            run_id = ident(runs[0].get("id"), "run_id")
            detail = cli(cli_path, ["workflows", "run-show", workflow_id, run_id], "run_show")
            status = detail.get("status") if isinstance(detail, dict) else None
            if status in TERMINAL:
                if status != "completed":
                    raise ProofError(f"scheduled_run_{status}")
                started_at = detail.get("started_at")
                if not isinstance(started_at, int) or started_at < due_at:
                    raise ProofError("scheduled_run_started_before_due")
                nodes = detail.get("node_runs") or []
                travel = next((node for node in nodes if node.get("node_id") == travel_id), None)
                if not isinstance(travel, dict) or travel.get("status") != "completed":
                    raise ProofError("travel_step_not_completed")
                count = result_count(travel)
                if count <= 0:
                    raise ProofError("train_result_count_zero_or_missing")
                return run_id, count, started_at
        time.sleep(4)
    raise ProofError("scheduled_run_timeout")


def acquire_leases(session_id: str, slot: int | None) -> tuple[list[tuple[str, str, set[str], str]], int]:
    owner = f"repository-session-{session_id}"
    leases: list[tuple[str, str, set[str], str]] = []
    stack_id = f"workflow-schedule-dev-{uuid4().hex[:12]}"
    stack_resources = {sessions.DOCKER_RESOURCE_DEV_STACK}
    sessions.acquire_test_resource_lease(stack_id, owner, stack_resources, mode="shared", timeout=120)
    leases.append((stack_id, owner, stack_resources, "shared"))
    try:
        for candidate in ([slot] if slot else range(1, 14)):
            lease_id = f"workflow-schedule-account-{candidate}-{uuid4().hex[:10]}"
            resources = {f"playwright-account:{candidate}"}
            try:
                sessions.acquire_test_resource_lease(lease_id, owner, resources, mode="exclusive", timeout=0)
            except RuntimeError:
                continue
            leases.append((lease_id, owner, resources, "exclusive"))
            return leases, candidate
    except BaseException:
        for lease_id, *_ in reversed(leases):
            sessions.release_test_resource_lease(lease_id)
        raise
    sessions.release_test_resource_lease(stack_id)
    raise ProofError("no_free_test_account_slot")


def write_receipt(path: Path, receipt: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(receipt, stream, sort_keys=True, indent=2)
            stream.write("\n")
    finally:
        os.chmod(path, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--recording-dir", type=Path,
                        help="Private directory for actual CLI terminal recordings before cleanup")
    parser.add_argument("--cli-path", required=True)
    parser.add_argument("--revision", required=True, help="Exact deployed dev commit SHA")
    parser.add_argument("--slot", type=int, choices=range(1, 14))
    parser.add_argument("--api-url", default=API_URL)
    parser.add_argument("--lead-minutes", type=int, default=12)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--allow-paid-dev-inference", action="store_true")
    args = parser.parse_args()
    state_dir = args.state_dir.resolve()
    receipt_path = args.receipt.resolve()
    record_dir = args.recording_dir.resolve() if args.recording_dir else None
    if any(os.getenv(key) for key in ("CI", "GITHUB_ACTIONS", "BUILDKITE", "GITLAB_CI")):
        parser.error("real-dev proof cannot run in CI")
    if args.api_url != API_URL or args.lead_minutes < 4 or args.timeout_seconds < 300:
        parser.error("dev target, at least four minutes lead, and bounded timeout required")
    if not args.allow_paid_dev_inference:
        parser.error("explicit --allow-paid-dev-inference is required")
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("--revision must be a full deployed commit SHA")
    if not state_dir.is_relative_to(Path("/tmp")) or state_dir == Path("/tmp") or state_dir.exists():
        parser.error("--state-dir must be a fresh path below /tmp")
    if receipt_path.is_relative_to(state_dir) or (record_dir and record_dir.is_relative_to(state_dir)):
        parser.error("receipt and recordings must be outside the disposable CLI state")
    cli_path = Path(args.cli_path).resolve()
    receipt: dict = {"status": "started", "target": API_URL, "started_at": datetime.now(UTC).isoformat(),
                     "session": args.session, "deployed_revision": args.revision,
                     "workflows": {}, "cleanup": {}}
    leases: list[tuple[str, str, set[str], str]] = []
    workflows: list[str] = []
    project_id: str | None = None
    created_state = False
    stop = threading.Event()
    renewal_errors: list[str] = []
    heartbeat: threading.Thread | None = None
    try:
        resolve_cli_path(str(cli_path))
        state_dir.mkdir(mode=0o700)
        created_state = True
        os.environ["OPENMATES_STATE_DIR"] = str(state_dir)
        os.environ["OPENMATES_PROFILE"] = ""
        os.environ.pop("OPENMATES_API_KEY", None)
        leases, slot = acquire_leases(args.session, args.slot)
        receipt["account_slot"] = slot

        def renew() -> None:
            while not stop.wait(sessions.DOCKER_TEST_LEASE_RENEW_INTERVAL_SECONDS):
                for lease_id, owner, resources, mode in leases:
                    try:
                        sessions.renew_test_resource_lease(lease_id, owner, resources, mode=mode)
                    except RuntimeError:
                        renewal_errors.append("lease_renewal_failed")
                        return

        heartbeat = threading.Thread(target=renew, daemon=True)
        heartbeat.start()
        login = subprocess.run(["node", "scripts/openmates_cli_test_account.mjs", "login", "--slot", str(slot),
                                "--api-url", API_URL], cwd=Path(__file__).resolve().parents[1],
                               capture_output=True, text=True, check=False, timeout=180)
        if login.returncode:
            # Keep only transport/auth failure codes, never credentials or response bodies.
            status = re.search(r"(?:Lookup|Login) failed with HTTP (\d{3})", login.stderr)
            message = re.search(r"\blogin\.[a-z_]+\b", login.stderr)
            if status:
                receipt["login_http_status"] = int(status.group(1))
            if message:
                receipt["login_message_code"] = message.group(0)
            if "fetch failed" in login.stderr:
                receipt["login_transport_failure"] = True
            raise ProofError("disposable_login_failed")
        print("Disposable account paired; creating isolated Project.", flush=True)
        project = cli(cli_path, ["projects", "create", f"Scheduled train proof {uuid4().hex[:8]}",
                                 "--write-policy", "always_ask", "--personal"], "project_create")
        project_id = ident((project.get("project") or {}).get("project_id")
                           if isinstance(project, dict) else None, "project_id")
        receipt["project_id"] = project_id
        now = datetime.now(ZONE)
        run_at = (now + timedelta(minutes=args.lead_minutes)).replace(second=0, microsecond=0)
        if (run_at - now).total_seconds() < 4 * 60:
            run_at += timedelta(minutes=1)
        date = (run_at.date() + timedelta(days=1)).isoformat()
        clock = run_at.strftime("%H:%M")
        due_at = int(run_at.astimezone(UTC).timestamp())
        receipt["requested_run_at"] = run_at.isoformat()
        once_prompt = (f"Create one Workflow in this Project to run only once at {run_at.isoformat()} "
                       f"({clock} Europe/Berlin) and search real train connections from Berlin to Hamburg "
                       f"departing {date}, with transport_methods [train] and at least three results. "
                       "Use travel.search_connections, then send the selected connection results in a new chat message. "
                       "Save it disabled.")
        daily_prompt = (f"Create a separate Workflow in this Project to run every day at {clock} "
                        f"Europe/Berlin, starting only from {run_at.isoformat()} onward. "
                        "No checks may run before that future starting date and time. "
                        "Search real train connections from Berlin to Hamburg "
                        "departing tomorrow relative to each run, using a dynamic $date tomorrow value "
                        "with format date, transport_methods [train], and at least three results. "
                        "Use travel.search_connections, then send the selected connection results in a new chat message. "
                        "Save it disabled.")
        for label, prompt, expected in (("once", once_prompt, run_at), ("daily", daily_prompt, run_at)):
            authored = author(cli_path, project_id, prompt, label, workflows)
            workflow_id = ident(authored.get("id"), f"{label}_workflow_id")
            receipt["workflows"][label] = {"workflow_id": workflow_id, "authored": True}
            travel_id = check_graph(authored, label, expected)
            receipt["workflows"][label]["travel_node_id"] = travel_id
            print(f"{label} train schedule authored and validated.", flush=True)
        if (run_at - datetime.now(ZONE)).total_seconds() < 60:
            raise ProofError("insufficient_scheduler_lead_after_authoring")
        for label in ("once", "daily"):
            workflow_id = receipt["workflows"][label]["workflow_id"]
            if scheduled_runs(cli_path, workflow_id):
                raise ProofError(f"{label}_ran_before_enable")
            enabled = cli(cli_path, ["workflows", "enable", workflow_id], f"{label}_enable")
            if not isinstance(enabled, dict) or enabled.get("enabled") is not True:
                raise ProofError(f"{label}_enable_rejected")
            if enabled.get("next_run_at") != due_at:
                raise ProofError(f"{label}_initial_next_run_mismatch")
            if scheduled_runs(cli_path, workflow_id):
                raise ProofError(f"{label}_ran_early")
            print(f"{label} enabled; no early run.", flush=True)
        while datetime.now(UTC).timestamp() < due_at - 30:
            for label in ("once", "daily"):
                if scheduled_runs(cli_path, receipt["workflows"][label]["workflow_id"]):
                    raise ProofError(f"{label}_ran_before_due")
            time.sleep(min(20, max(1, due_at - 30 - time.time())))
        deadline = time.monotonic() + args.timeout_seconds
        for label in ("once", "daily"):
            item = receipt["workflows"][label]
            run_id, count, started_at = wait_for_run(cli_path, item["workflow_id"],
                                                      item["travel_node_id"], due_at, deadline)
            item.update({"run_id": run_id, "status": "completed", "result_count": count,
                         "actual_started_at": datetime.fromtimestamp(started_at, UTC).isoformat()})
            print(f"{label} scheduler run completed; train results: {count}.", flush=True)
        for label in ("once", "daily"):
            item = receipt["workflows"][label]
            shown = cli(cli_path, ["workflows", "show", item["workflow_id"]], f"{label}_show")
            next_at = shown.get("next_run_at") if isinstance(shown, dict) else None
            if label == "once":
                if next_at not in (None, 0):
                    raise ProofError("once_has_next_run")
            else:
                if not isinstance(next_at, int):
                    raise ProofError("daily_next_run_missing")
                next_local = datetime.fromtimestamp(next_at, UTC).astimezone(ZONE)
                if next_local.date() != run_at.date() + timedelta(days=1) or next_local.strftime("%H:%M") != clock:
                    raise ProofError("daily_next_run_not_following_day")
                item["next_run_at"] = next_at
        time.sleep(65)
        for item in receipt["workflows"].values():
            if len(scheduled_runs(cli_path, item["workflow_id"])) != 1:
                raise ProofError("duplicate_or_missing_scheduled_run")
        if renewal_errors:
            raise ProofError("lease_renewal_failed")
        capture_script = Path(__file__).with_name("cli_video_capture.py")
        for label in (("once", "daily") if record_dir else ()):
            item = receipt["workflows"][label]
            output_dir = record_dir / label
            recording = subprocess.run(
                [sys.executable, str(capture_script), "--output-dir", str(output_dir),
                 "--target-environment", API_URL, "--timeout-seconds", "90",
                 "--display-number", str(180 + slot),
                 "--no-response-media", "--", "node", str(cli_path),
                 "workflows", "run-show", item["workflow_id"], item["run_id"],
                 "--api-url", API_URL],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
                check=False, timeout=120,
            )
            if recording.returncode or not (output_dir / "raw-terminal.mp4").is_file():
                item["terminal_capture_status"] = "failed"
                raise ProofError(f"{label}_terminal_capture_failed")
            item["terminal_recording"] = str(output_dir / "raw-terminal.mp4")
            item["terminal_manifest"] = str(output_dir / "manifest.json")
            item["terminal_capture_status"] = "captured"
            print(f"{label} real CLI terminal recorded.", flush=True)
        receipt["status"] = "passed"
        print("Scheduled train proof passed: no duplicates; recurrence checked.", flush=True)
    except BaseException as exc:
        receipt["status"] = "failed"
        receipt["error_code"] = str(exc) if isinstance(exc, ProofError) else type(exc).__name__
        print(f"Scheduled train proof failed: {receipt['error_code']}", flush=True)
    finally:
        for workflow_id in reversed(list(dict.fromkeys(workflows))):
            try:
                cli(cli_path, ["workflows", "disable", workflow_id], "cleanup_disable")
                cli(cli_path, ["workflows", "delete", workflow_id, "--yes"], "cleanup_delete")
                receipt["cleanup"][workflow_id] = "deleted"
            except ProofError:
                receipt["cleanup"][workflow_id] = "failed"
                receipt["status"] = "failed"
        if project_id:
            try:
                cli(cli_path, ["projects", "delete", project_id, "--confirm", project_id, "--personal"], "cleanup_project")
                receipt["cleanup"]["project"] = "deleted"
            except ProofError:
                receipt["cleanup"]["project"] = "failed"
                receipt["status"] = "failed"
        stop.set()
        if heartbeat:
            heartbeat.join(timeout=2)
        for lease_id, *_ in reversed(leases):
            try:
                sessions.release_test_resource_lease(lease_id)
            except RuntimeError:
                receipt["status"] = "failed"
                receipt["cleanup"]["lease"] = "failed"
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        write_receipt(receipt_path, receipt)
        if created_state:
            shutil.rmtree(state_dir, ignore_errors=True)
        print(f"Private receipt: {receipt_path}", flush=True)
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
