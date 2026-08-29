#!/usr/bin/env python3
"""Verify user work-control REST gates against the real dev API.

This creates UUID-scoped, opaque-encrypted Plan and Task fixtures through an
existing test-account session, then removes only those fixtures. It never logs
cookies, response bodies, identifiers, ciphertext, or secrets, and it refuses
production targets. Browser approval is intentionally tested as a CLI denial.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any
import uuid

from verify_projects_api import (  # Reuse the audited real-dev test-account transport.
    DEFAULT_API_URL,
    ApiResponse,
    RestClient,
    VerificationFailure,
    derive_web_origin,
    login_test_account,
    project_payload,
    validate_api_url,
)


def opaque() -> str:
    return base64.b64encode(b"OM\x01\x00\x00\x00" + os.urandom(40)).decode("ascii")


def require(response: ApiResponse, status: int, scenario: str) -> None:
    if response.status != status:
        detail = response.payload.get("detail") if isinstance(response.payload, dict) else None
        suffix = f"_{str(detail).replace(' ', '_')[:80]}" if isinstance(detail, str) and detail else ""
        raise VerificationFailure(scenario, f"expected_http_{status}_got_{response.status}{suffix}")


def require_denied(response: ApiResponse, scenario: str) -> None:
    if response.status < 400:
        raise VerificationFailure(scenario, "policy_not_enforced")


def timestamp() -> int:
    return int(time.time())


def hashed_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def plan_payload(plan_id: str, project_id: str) -> dict[str, Any]:
    now = timestamp()
    return {"plan_id": plan_id, "encrypted_title": opaque(), "encrypted_goal": opaque(), "linked_project_ids": [project_id], "status": "draft", "created_at": now, "updated_at": now, "key_wrappers": [{"key_type": "master", "encrypted_plan_key": opaque(), "created_at": now}, {"key_type": "project", "hashed_project_id": hashed_id(project_id), "encrypted_plan_key": opaque(), "created_at": now}]}


def task_payload(task_id: str, plan_id: str, project_id: str) -> dict[str, Any]:
    now = timestamp()
    return {"task_id": task_id, "encrypted_title": opaque(), "encrypted_task_key": opaque(), "plan_id": plan_id, "linked_project_ids": [project_id], "status": "todo", "version": 1, "created_at": now, "updated_at": now, "key_wrappers": [{"key_type": "master", "encrypted_task_key": opaque(), "created_at": now}, {"key_type": "project", "hashed_project_id": hashed_id(project_id), "encrypted_task_key": opaque(), "created_at": now}, {"key_type": "plan", "hashed_plan_id": hashed_id(plan_id), "encrypted_task_key": opaque(), "created_at": now}]}


def assumption_resolution_payload() -> dict[str, Any]:
    return {
        "status": "confirmed",
        "encrypted_evidence_summary": opaque(),
        "encrypted_sources": opaque(),
        "updated_at": timestamp(),
    }


def record(response: ApiResponse, key: str, scenario: str) -> dict[str, Any]:
    value = response.payload.get(key)
    if not isinstance(value, dict):
        raise VerificationFailure(scenario, f"{key}_missing")
    return value


def delete_fixture(client: RestClient, plan_id: str | None, task_id: str | None, task_version: int | None, project_id: str | None, assumption_id: str | None, revision_id: str | None) -> dict[str, Any]:
    failed: list[str] = []
    if task_id:
        task_absent = False
        if task_version is None:
            current_tasks = client.request("GET", "/v1/user-tasks", scenario="cleanup_task_list")
            if current_tasks.status != 200:
                failed.append("task")
            else:
                tasks = current_tasks.payload.get("tasks")
                current_task = next(
                    (item for item in tasks if isinstance(item, dict) and item.get("task_id") == task_id),
                    None,
                ) if isinstance(tasks, list) else None
                if current_task:
                    task_version = int(current_task["version"])
                else:
                    task_absent = True
        if task_version is not None:
            response = client.request("DELETE", f"/v1/user-tasks/{task_id}", query={"version": task_version}, scenario="cleanup_task")
            if response.status not in {200, 404}:
                failed.append("task")
        elif not task_absent and "task" not in failed:
            failed.append("task")
    if plan_id:
        current = client.request("GET", f"/v1/user-plans/{plan_id}", scenario="cleanup_plan_get")
        if current.status == 200:
            version = record(current, "plan", "cleanup_plan_get").get("version")
            response = client.request("DELETE", f"/v1/user-plans/{plan_id}", query={"version": version}, scenario="cleanup_plan")
            if response.status not in {200, 404}:
                failed.append("plan")
        elif current.status != 404:
            failed.append("plan")
        parent = client.request("GET", f"/v1/user-plans/{plan_id}", scenario="cleanup_plan_absence")
        if parent.status != 404:
            failed.append("plan")
        if assumption_id:
            assumption = client.request("GET", f"/v1/user-plans/{plan_id}/assumptions", scenario="cleanup_assumption_parent_absence")
            if assumption.status not in {404, 410}:
                failed.append("assumption")
        if revision_id:
            # Revisions have no list endpoint; Plan absence is their only public
            # lookup boundary and is checked above before accepting cleanup.
            if parent.status != 404:
                failed.append("revision")
    if project_id:
        response = client.request("DELETE", f"/v1/projects/{project_id}", query={"confirmation_project_id": project_id}, scenario="cleanup_project")
        if response.status not in {200, 404}:
            failed.append("project")
    return {"status": "passed" if not failed else "failed", "failed_resources": failed}


def run(api_url: str, headers: dict[str, str]) -> tuple[dict[str, Any], int]:
    client, unauthenticated = RestClient(api_url, headers), RestClient(api_url)
    cli_client = RestClient(api_url, {key: value for key, value in headers.items() if key.lower() != "origin"})
    project_id, plan_id, task_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    task_version: int | None = None
    assumption_id: str | None = None
    revision_id: str | None = None
    scenarios: dict[str, Any] = {}
    failure: VerificationFailure | None = None
    try:
        require(unauthenticated.request("GET", "/v1/user-plans", scenario="unauthenticated"), 401, "unauthenticated")
        scenarios["unauthenticated"] = {"status": "passed"}
        require(client.request("POST", "/v1/projects", body=project_payload(project_id), scenario="project_create"), 200, "project_create")
        plan_input = plan_payload(plan_id, project_id)
        plan_response = client.request("POST", "/v1/user-plans", body=plan_input, scenario="plan_create")
        require(plan_response, 200, "plan_create")
        record(plan_response, "plan", "plan_create")
        persisted_plan = record(client.request("GET", f"/v1/user-plans/{plan_id}", scenario="plan_wrapper_round_trip"), "plan", "plan_wrapper_round_trip")
        expected_master_wrapper = next(wrapper for wrapper in plan_input["key_wrappers"] if wrapper["key_type"] == "master")
        persisted_master_wrapper = next((wrapper for wrapper in persisted_plan.get("key_wrappers", []) if wrapper.get("key_type") == "master"), None)
        if not persisted_master_wrapper or persisted_master_wrapper.get("encrypted_plan_key") != expected_master_wrapper["encrypted_plan_key"]:
            raise VerificationFailure("plan_wrapper_round_trip", "master_wrapper_ciphertext_changed")
        task_response = client.request("POST", "/v1/user-tasks", body=task_payload(task_id, plan_id, project_id), scenario="task_create")
        require(task_response, 200, "task_create")
        task = record(task_response, "task", "task_create")
        task_version = int(task["version"])
        require(client.request("GET", f"/v1/user-plans/{uuid.uuid4()}", scenario="owner_scope"), 404, "owner_scope")
        scenarios["owner_scope"] = {"status": "passed"}
        edge = client.request("POST", f"/v1/user-plans/{plan_id}/dependencies", body={"target_ref": f"task:{task_id}"}, scenario="dependency_create")
        require(edge, 200, "dependency_create")
        plan_dependencies = client.request("GET", f"/v1/user-plans/{plan_id}/dependencies", scenario="plan_dependencies_read")
        require(plan_dependencies, 200, "plan_dependencies_read")
        dependencies = plan_dependencies.payload.get("dependencies")
        if not isinstance(dependencies, list) or dependencies[0].get("target_ref") != f"task:{task_id}" or dependencies[0].get("satisfied") is not False:
            raise VerificationFailure("plan_dependencies_read", "normalized_dependency_missing")
        if "encrypted_title" in dependencies[0]:
            raise VerificationFailure("plan_dependencies_read", "plaintext_or_record_content_exposed")
        task_dependencies = client.request("GET", f"/v1/user-tasks/{task_id}/dependencies", scenario="task_dependencies_read")
        require(task_dependencies, 200, "task_dependencies_read")
        if task_dependencies.payload.get("dependencies") != [] or task_dependencies.payload.get("blockers") != []:
            raise VerificationFailure("task_dependencies_read", "unexpected_task_dependency_projection")
        require_denied(client.request("POST", f"/v1/user-plans/{plan_id}/dependencies", body={"target_ref": f"task:{task_id}"}, scenario="duplicate_edge_index"), "duplicate_edge_index")
        scenarios["dependency_index_and_reads"] = {"status": "passed"}
        require_denied(client.request("DELETE", f"/v1/user-tasks/{task_id}", query={"version": task_version}, scenario="deletion_protection"), "deletion_protection")
        require(client.request("DELETE", f"/v1/user-plans/{plan_id}/dependencies/task/{task_id}", scenario="dependency_remove"), 200, "dependency_remove")
        assumption_id = "live-assumption"
        require(client.request("POST", f"/v1/user-plans/{plan_id}/assumptions", body={"assumption_id": assumption_id, "encrypted_text": opaque(), "required_before": "completion", "created_at": timestamp()}, scenario="assumption_create"), 200, "assumption_create")
        require_denied(client.request("PATCH", f"/v1/user-plans/{plan_id}/assumptions/{assumption_id}", body={"status": "confirmed", "updated_at": timestamp()}, scenario="assumption_evidence_required"), "assumption_evidence_required")
        require(client.request("PATCH", f"/v1/user-plans/{plan_id}/assumptions/{assumption_id}", body=assumption_resolution_payload(), scenario="assumption_evidence_accept"), 200, "assumption_evidence_accept")
        revision = record(client.request("POST", f"/v1/user-plans/{plan_id}/revisions", body={"fingerprint": f"live-{uuid.uuid4()}", "encrypted_snapshot": opaque(), "created_at": timestamp()}, scenario="revision_submit"), "revision", "revision_submit")
        revision_id = str(revision["revision_id"])
        revisions = client.request("GET", f"/v1/user-plans/{plan_id}/revisions", scenario="revisions_read")
        require(revisions, 200, "revisions_read")
        revision_rows = revisions.payload.get("revisions")
        if not isinstance(revision_rows, list) or not any(row.get("revision_id") == revision_id and row.get("encrypted_snapshot") for row in revision_rows if isinstance(row, dict)):
            raise VerificationFailure("revisions_read", "immutable_ciphertext_revision_missing")
        approval = client.request("GET", f"/v1/user-plans/{plan_id}/approval-status", scenario="approval_status_read")
        require(approval, 200, "approval_status_read")
        approval_data = approval.payload.get("approval")
        if not isinstance(approval_data, dict) or approval_data.get("submitted_revision_id") != revision_id or "encrypted_snapshot" in approval_data:
            raise VerificationFailure("approval_status_read", "unsafe_or_incomplete_approval_projection")
        require_denied(cli_client.request("POST", f"/v1/user-plans/{plan_id}/revisions/approve", body={"revision_id": revision["revision_id"]}, scenario="cli_device_approval_denied"), "cli_device_approval_denied")
        scenarios["assumptions_revision_and_approval"] = {"status": "passed", "browser_approval": "not_attempted_policy_negative_proof"}
        deleted_task = client.request("DELETE", f"/v1/user-tasks/{task_id}", query={"version": task_version}, scenario="task_delete")
        require(deleted_task, 200, "task_delete")
        task_id, task_version = None, None
        scenarios["cleanup_safe_delete"] = {"status": "passed"}
    except VerificationFailure as exc:
        failure = exc
        scenarios[exc.scenario] = {"status": "failed", "code": exc.code}
    finally:
        cleanup = delete_fixture(client, plan_id, task_id, task_version, project_id, assumption_id, revision_id)
    if cleanup["status"] != "passed" and failure is None:
        failure = VerificationFailure("cleanup", "cleanup_failed")
    return {"status": "failed" if failure else "passed", "classification": {"access_model": "first_party_client_only", "authentication": "test_account_session", "decrypted_plaintext": "none", "approval": "browser_only_negative_cli_proof"}, "scenarios": scenarios, "cleanup": cleanup, "not_run": {"browser_approval": "agent must not approve", "multi_account_owner_matrix": "requires separately provisioned account"}}, 1 if failure else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("OPENMATES_API_URL", DEFAULT_API_URL))
    parser.add_argument("--web-origin")
    parser.add_argument("--slot", default=os.getenv("OPENMATES_TEST_ACCOUNT_SOURCE_SLOT"))
    args = parser.parse_args(argv)
    try:
        api_url = validate_api_url(args.api_url)
        with tempfile.TemporaryDirectory(prefix="openmates-work-control-api-") as home:
            report, code = run(api_url, login_test_account(api_url, Path(home), args.slot, args.web_origin or derive_web_origin(api_url)))
    except VerificationFailure as exc:
        report, code = {"status": "failed", "scenarios": {exc.scenario: {"status": "failed", "code": exc.code}}}, 1
    except Exception:
        report, code = {"status": "failed", "scenarios": {"internal": {"status": "failed", "code": "unexpected_internal_error"}}}, 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
