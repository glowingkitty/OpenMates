#!/usr/bin/env python3
"""Run real-dev workspace ask examples through the built OpenMates CLI.

Purpose: verify the finalized workspace ask contract against the public dev API.
Architecture: docs/specs/workspace-change-history/spec.yml.
Security: uses a temporary CLI HOME and existing test-account login helper; never
prints credentials, cookies, session files, or decrypted workspace contents.
Evidence: prints concise JSON with outcomes, change sets, and undo results.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
CLI_DIR = ROOT / "frontend" / "packages" / "openmates-cli"
CLI_PATH = CLI_DIR / "dist" / "cli.js"
LOGIN_SCRIPT = ROOT / "scripts" / "openmates_cli_test_account.mjs"
DEFAULT_API_URL = "https://api.dev.openmates.org"
DEFAULT_RESPONSE_TIMEOUT_SECONDS = "240"
EXPECTED_FALLBACK_CHAT_CASES = {
    "task_broad_status_fallback",
    "plan_broad_archive_fallback",
    "project_broad_archive_fallback",
    "workflow_broad_edit_fallback",
}


def run_command(args: list[str], *, env: dict[str, str], cwd: Path = ROOT, timeout: int = 240) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True, check=False, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(args[:4])} ...\n"
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    return result


def parse_json_output(output: str) -> Any:
    stripped = output.strip()
    if not stripped:
        raise RuntimeError("Command returned empty stdout")
    start_candidates = [index for index in (stripped.find("{"), stripped.find("[")) if index >= 0]
    if not start_candidates:
        raise RuntimeError(f"Command returned non-JSON stdout: {stripped[:200]}")
    return json.loads(stripped[min(start_candidates):])


def run_cli(args: list[str], *, api_url: str, env: dict[str, str], timeout: int = 300) -> dict[str, Any]:
    result = run_command(
        ["node", str(CLI_PATH), "--api-url", api_url.rstrip("/"), *args, "--response-timeout-seconds", DEFAULT_RESPONSE_TIMEOUT_SECONDS, "--json"],
        cwd=ROOT,
        env=env,
        timeout=timeout,
    )
    parsed = parse_json_output(result.stdout)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"CLI command returned non-object JSON: {parsed!r}")
    return parsed


def first_id(result: dict[str, Any], collection: str, key: str) -> str:
    items = result.get(collection)
    if not isinstance(items, list) or not items or not isinstance(items[0], dict) or not items[0].get(key):
        raise RuntimeError(f"Missing {collection}[0].{key} in result: {result}")
    return str(items[0][key])


def workflow_id(result: dict[str, Any]) -> str:
    if result.get("id"):
        return str(result["id"])
    workflow = result.get("workflow")
    if not isinstance(workflow, dict) or not workflow.get("id"):
        raise RuntimeError(f"Missing workflow.id in result: {result}")
    return str(workflow["id"])


def summarize_result(case_id: str, command: list[str], result: dict[str, Any]) -> dict[str, Any]:
    fallback = result.get("workspace_ask_fallback") if isinstance(result.get("workspace_ask_fallback"), dict) else None
    return {
        "case": case_id,
        "command": "openmates " + " ".join(command),
        "outcome": result.get("outcome") or (fallback or {}).get("outcome"),
        "applied": result.get("applied"),
        "fallback_to_chat": result.get("fallback_to_chat") or bool(fallback),
        "fallback_chat_started": bool(fallback) and result.get("status") in {"completed", "waiting_for_user"},
        "fallback_message": (fallback or {}).get("fallback_message") or result.get("fallback_message"),
        "chat_id": result.get("chatId") if fallback else None,
        "change_set_id": None if fallback else result.get("change_set_id"),
        "summary": result.get("summary") if not fallback else result.get("assistant"),
        "warnings": result.get("warnings") or [],
        "processing": compact_processing(result.get("processing")),
    }


def compact_processing(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    model_selection = value.get("model_selection") if isinstance(value.get("model_selection"), dict) else {}
    intent_frame = value.get("intent_frame") if isinstance(value.get("intent_frame"), dict) else {}
    return {
        "inference_used": value.get("inference_used"),
        "deterministic_short_create": value.get("deterministic_short_create"),
        "namespace": intent_frame.get("namespace"),
        "operation": intent_frame.get("operation"),
        "complexity": intent_frame.get("complexity"),
        "primary_model_id": model_selection.get("primary_model_id"),
    }


def run_case(
    case_id: str,
    command: list[str],
    *,
    api_url: str,
    env: dict[str, str],
    applied_change_sets: list[str],
    fallback_chat_ids: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    result = run_cli(command, api_url=api_url, env=env)
    summary = summarize_result(case_id, command, result)
    if case_id in EXPECTED_FALLBACK_CHAT_CASES and not summary["fallback_chat_started"]:
        raise RuntimeError(f"Expected {case_id} to start fallback chat, got: {summary}")
    change_set_id = result.get("change_set_id")
    if result.get("outcome") == "applied" and isinstance(change_set_id, str) and change_set_id:
        applied_change_sets.append(change_set_id)
    fallback = result.get("workspace_ask_fallback")
    chat_id = result.get("chatId")
    if isinstance(fallback, dict) and isinstance(chat_id, str) and chat_id:
        fallback_chat_ids.append(chat_id)
    return summary, result


def undo_change_sets(change_set_ids: list[str], *, api_url: str, env: dict[str, str]) -> list[dict[str, Any]]:
    undo_results: list[dict[str, Any]] = []
    for change_set_id in reversed(change_set_ids):
        try:
            result = run_cli(["history", "undo", change_set_id], api_url=api_url, env=env, timeout=180)
            undo_results.append({
                "change_set_id": change_set_id,
                "undo_change_set_id": result.get("change_set_id") or result.get("undone_change_set_id"),
                "undone": result.get("undone", True),
            })
        except Exception as exc:  # noqa: BLE001 - verification must report all cleanup failures.
            undo_results.append({"change_set_id": change_set_id, "error": str(exc)})
    return undo_results


def cleanup_chats(chat_ids: list[str], *, api_url: str, env: dict[str, str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for chat_id in chat_ids:
        try:
            run_command(
                ["node", str(CLI_PATH), "--api-url", api_url.rstrip("/"), "chats", "delete", chat_id, "--yes"],
                cwd=ROOT,
                env=env,
                timeout=120,
            )
            results.append({"chat_id": chat_id, "deleted": True})
        except Exception as exc:  # noqa: BLE001 - cleanup failures are evidence.
            results.append({"chat_id": chat_id, "error": str(exc)})
    return results


def manual_workflow_graph() -> str:
    return json.dumps({
        "version": 1,
        "trigger_node_id": "manual-trigger",
        "nodes": [
            {"id": "manual-trigger", "type": "manual_trigger", "title": "Manual trigger"},
            {"id": "end", "type": "end", "title": "End"},
        ],
        "edges": [{"from": "manual-trigger", "to": "end"}],
    })


def cleanup_workflows(workflow_ids: list[str], *, api_url: str, env: dict[str, str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for workflow_id_value in workflow_ids:
        try:
            result = run_cli(["workflows", "delete", workflow_id_value, "--yes"], api_url=api_url, env=env, timeout=120)
            results.append({"workflow_id": workflow_id_value, "deleted": result.get("deleted", True)})
        except Exception as exc:  # noqa: BLE001 - cleanup failures are evidence.
            results.append({"workflow_id": workflow_id_value, "error": str(exc)})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.environ.get("OPENMATES_API_URL", DEFAULT_API_URL))
    parser.add_argument("--slot", default=os.environ.get("OPENMATES_TEST_ACCOUNT_SOURCE_SLOT", "auto"))
    args = parser.parse_args()

    if not CLI_PATH.exists():
        raise RuntimeError(f"Missing built CLI at {CLI_PATH}. Run npm --prefix frontend/packages/openmates-cli run build first.")

    suffix = f"wch-{int(time.time())}"
    with tempfile.TemporaryDirectory(prefix="openmates-wch-ask-") as home:
        env = dict(os.environ)
        env["HOME"] = home
        env["OPENMATES_API_URL"] = args.api_url.rstrip("/")
        run_command(
            ["node", str(LOGIN_SCRIPT), "login", "--slot", args.slot, "--api-url", args.api_url.rstrip("/")],
            env=env,
            timeout=180,
        )

        applied_change_sets: list[str] = []
        fallback_chat_ids: list[str] = []
        cleanup_workflow_ids: list[str] = []
        evidence: list[dict[str, Any]] = []
        run_error: Exception | None = None

        try:
            task_create_summary, task_create = run_case("task_short_create", ["tasks", "ask", f"WCH quick task {suffix}"], api_url=args.api_url, env=env, applied_change_sets=applied_change_sets, fallback_chat_ids=fallback_chat_ids)
            evidence.append(task_create_summary)
            task_id = first_id(task_create, "tasks", "task_id")

            task_delete_summary, task_delete = run_case("task_delete_seed", ["tasks", "ask", f"WCH temporary task {suffix}"], api_url=args.api_url, env=env, applied_change_sets=applied_change_sets, fallback_chat_ids=fallback_chat_ids)
            _ = task_delete_summary
            task_delete_id = first_id(task_delete, "tasks", "task_id")

            plan_create_summary, plan_create = run_case("plan_short_create", ["plans", "ask", f"WCH quick plan {suffix}"], api_url=args.api_url, env=env, applied_change_sets=applied_change_sets, fallback_chat_ids=fallback_chat_ids)
            evidence.append(plan_create_summary)
            plan_id = first_id(plan_create, "plans", "plan_id")

            project_create_summary, project_create = run_case("project_short_create", ["projects", "ask", f"WCH quick project {suffix}"], api_url=args.api_url, env=env, applied_change_sets=applied_change_sets, fallback_chat_ids=fallback_chat_ids)
            evidence.append(project_create_summary)
            project_id = first_id(project_create, "projects", "project_id")

            project_delete_summary, project_delete = run_case("project_delete_seed", ["projects", "ask", f"WCH temporary project {suffix}"], api_url=args.api_url, env=env, applied_change_sets=applied_change_sets, fallback_chat_ids=fallback_chat_ids)
            _ = project_delete_summary
            project_delete_id = first_id(project_delete, "projects", "project_id")

            workflow_create_summary, workflow_create = run_case("workflow_short_create", ["workflows", "ask", f"WCH quick workflow {suffix}"], api_url=args.api_url, env=env, applied_change_sets=applied_change_sets, fallback_chat_ids=fallback_chat_ids)
            evidence.append(workflow_create_summary)
            workflow_disable_seed = run_cli(["workflows", "create", "--title", f"WCH enabled workflow {suffix}", "--graph", manual_workflow_graph(), "--enabled"], api_url=args.api_url, env=env, timeout=180)
            workflow = workflow_id(workflow_disable_seed)
            cleanup_workflow_ids.append(workflow)

            cases = [
                ("task_medium_ai_create", ["tasks", "ask", f"Prepare {suffix} launch checklist: draft copy, test signup tracking, publish update Monday."]),
                ("task_broad_status_fallback", ["tasks", "ask", "mark my 3d printing tasks done"]),
                ("task_exact_status", ["tasks", "ask", f"mark @task:{task_id} done"]),
                ("task_exact_rename", ["tasks", "ask", f"rename @task:{task_id} to WCH renamed task {suffix}"]),
                ("task_exact_delete", ["tasks", "ask", f"delete @task:{task_delete_id}"]),
                ("plan_medium_ai_create", ["plans", "ask", f"Make a {suffix} release validation plan with rollout, monitoring, rollback, and stakeholder updates."]),
                ("plan_broad_archive_fallback", ["plans", "ask", "archive the launch plan"]),
                ("plan_exact_archive", ["plans", "ask", f"archive @plan:{plan_id}"]),
                ("plan_exact_rename", ["plans", "ask", f"rename @plan:{plan_id} to WCH renamed plan {suffix}"]),
                ("project_broad_archive_fallback", ["projects", "ask", "archive the launch project"]),
                ("project_exact_archive", ["projects", "ask", f"archive @project:{project_id}"]),
                ("project_exact_rename", ["projects", "ask", f"rename @project:{project_id} to WCH renamed project {suffix}"]),
                ("project_exact_delete", ["projects", "ask", f"delete @project:{project_delete_id}"]),
                ("workflow_complex_ai_create", ["workflows", "ask", f"When I manually trigger {suffix}, summarize release risk, check whether workspace history or encryption files were touched, and notify me if risk is high."]),
                ("workflow_exact_disable", ["workflows", "ask", f"disable @workflow:{workflow}"]),
                ("workflow_broad_edit_fallback", ["workflows", "ask", "add a Discord notification to all my workflows once they are done"]),
            ]

            for case_id, command in cases:
                summary, _result = run_case(case_id, command, api_url=args.api_url, env=env, applied_change_sets=applied_change_sets, fallback_chat_ids=fallback_chat_ids)
                evidence.append(summary)

            if len(evidence) != 20:
                raise RuntimeError(f"Expected 20 examples, got {len(evidence)}")
        except Exception as exc:  # noqa: BLE001 - preserve partial evidence, then cleanup.
            run_error = exc

        undo_results = undo_change_sets(applied_change_sets, api_url=args.api_url, env=env)
        chat_cleanup_results = cleanup_chats(fallback_chat_ids, api_url=args.api_url, env=env)
        cleanup_results = cleanup_workflows(cleanup_workflow_ids, api_url=args.api_url, env=env)
        print(json.dumps({"api_url": args.api_url.rstrip("/"), "example_count": len(evidence), "examples": evidence, "undo_results": undo_results, "chat_cleanup_results": chat_cleanup_results, "cleanup_results": cleanup_results}, indent=2))
        if run_error is not None:
            raise run_error
        failed_undo = [item for item in undo_results if item.get("error")]
        if failed_undo:
            return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001 - command-line verifier should print one concise failure.
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
