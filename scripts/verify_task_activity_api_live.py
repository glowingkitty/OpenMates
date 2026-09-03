#!/usr/bin/env python3
"""Verify encrypted Task Activity routes against the real dev API.

This first-party-only smoke creates a personal opaque-encrypted Task and one
opaque-encrypted Activity comment through the audited test-account transport.
It verifies idempotency, safe ciphertext projections, and tombstoning, then
removes its synthetic Task. Reports intentionally exclude IDs, cookies,
ciphertext, raw keys, and response bodies, and production targets are refused.
"""

# test-file: backend/tests/test_user_task_activity_api.py

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any
import uuid

from verify_projects_api import (
    DEFAULT_API_URL,
    ApiResponse,
    RestClient,
    VerificationFailure,
    derive_web_origin,
    login_test_account,
    validate_api_url,
)


ACTIVITY_CIPHERTEXT_FIELDS = {
    "encrypted_entry_key",
    "encrypted_message",
    "encrypted_embed_key_material",
}
ACTIVITY_SAFE_FIELDS = {
    "entry_id",
    "task_id",
    "kind",
    "actor_type",
    "actor_hash",
    "author_hash",
    "event_type",
    "source_surface",
    "created_at",
    "deleted_at",
    "deleted_by_hash",
    "embed_refs",
    *ACTIVITY_CIPHERTEXT_FIELDS,
}
TOMBSTONE_FORBIDDEN_FIELDS = ACTIVITY_CIPHERTEXT_FIELDS | {"embed_refs", "encrypted_snapshot"}


def opaque_ciphertext() -> str:
    return base64.b64encode(b"OM\x01\x00\x00\x00" + os.urandom(40)).decode("ascii")


def timestamp() -> int:
    return int(time.time())


def require(response: ApiResponse, expected_status: int, scenario: str) -> None:
    if response.status != expected_status:
        raise VerificationFailure(scenario, f"expected_http_{expected_status}_got_{response.status}")


def record(response: ApiResponse, key: str, scenario: str) -> dict[str, Any]:
    value = response.payload.get(key)
    if not isinstance(value, dict):
        raise VerificationFailure(scenario, f"{key}_missing")
    return value


def task_payload(task_id: str) -> dict[str, Any]:
    now = timestamp()
    return {
        "task_id": task_id,
        "encrypted_task_key": opaque_ciphertext(),
        "encrypted_title": opaque_ciphertext(),
        "status": "todo",
        "assignee_type": "user",
        "version": 1,
        "created_at": now,
        "updated_at": now,
        "key_wrappers": [{"key_type": "master", "encrypted_task_key": opaque_ciphertext(), "created_at": now}],
    }


def activity_payload(entry_id: str) -> dict[str, Any]:
    return {
        "entry_id": entry_id,
        "encrypted_entry_key": opaque_ciphertext(),
        "encrypted_message": opaque_ciphertext(),
        "encrypted_embed_key_material": opaque_ciphertext(),
        "embed_refs": [str(uuid.uuid4())],
        "created_at": timestamp(),
    }


def assert_ciphertext_projection(entry: dict[str, Any], entry_id: str, scenario: str) -> None:
    if entry.get("entry_id") != entry_id:
        raise VerificationFailure(scenario, "entry_identity_mismatch")
    if not ACTIVITY_CIPHERTEXT_FIELDS <= set(entry):
        raise VerificationFailure(scenario, "ciphertext_fields_missing")
    if any(not isinstance(entry[field], str) or not entry[field] for field in ACTIVITY_CIPHERTEXT_FIELDS):
        raise VerificationFailure(scenario, "ciphertext_fields_invalid")
    if not isinstance(entry.get("embed_refs"), list):
        raise VerificationFailure(scenario, "embed_refs_missing")
    if set(entry) - ACTIVITY_SAFE_FIELDS:
        raise VerificationFailure(scenario, "unsafe_activity_projection")
    if any("plaintext" in field or field.startswith("raw_") for field in entry):
        raise VerificationFailure(scenario, "plaintext_or_raw_key_exposed")


def assert_tombstone(entry: dict[str, Any], entry_id: str, scenario: str) -> None:
    if entry.get("entry_id") != entry_id or entry.get("kind") != "tombstone":
        raise VerificationFailure(scenario, "tombstone_identity_or_kind_invalid")
    if not isinstance(entry.get("author_hash"), str) or not isinstance(entry.get("deleted_by_hash"), str):
        raise VerificationFailure(scenario, "tombstone_attribution_missing")
    if any(entry.get(field) not in (None, []) for field in TOMBSTONE_FORBIDDEN_FIELDS):
        raise VerificationFailure(scenario, "tombstone_private_material_retained")
    if any("plaintext" in field or field.startswith("raw_") for field in entry):
        raise VerificationFailure(scenario, "tombstone_plaintext_or_raw_key_exposed")


def cleanup_task(client: RestClient, task_id: str | None, task_version: int | None) -> dict[str, Any]:
    if not task_id:
        return {"status": "passed", "failed_resources": []}
    version = task_version
    if version is None:
        listed = client.request("GET", "/v1/user-tasks", scenario="cleanup_task_list")
        if listed.status == 200:
            tasks = listed.payload.get("tasks")
            matching = next((task for task in tasks if isinstance(task, dict) and task.get("task_id") == task_id), None) if isinstance(tasks, list) else None
            version = matching.get("version") if isinstance(matching, dict) else None
    if not isinstance(version, int):
        return {"status": "failed", "failed_resources": ["task"]}
    response = client.request(
        "DELETE",
        f"/v1/user-tasks/{task_id}",
        query={"version": version},
        scenario="cleanup_task",
    )
    return {
        "status": "passed" if response.status in {200, 404} else "failed",
        "failed_resources": [] if response.status in {200, 404} else ["task"],
    }


def classification() -> dict[str, Any]:
    return {
        "access_model": "first_party_client_only",
        "auth": "approved_test_account_session_cookie",
        "rate_limits": {"read": "60/minute", "mutation": "30/minute", "classification": "standard_task_rate_limits"},
        "credit_budget": "none",
        "data_boundary": "ciphertext_only",
    }


def run(api_url: str, headers: dict[str, str]) -> tuple[dict[str, Any], int]:
    client = RestClient(api_url, {**headers, "X-OpenMates-Client": "web"})
    unauthenticated = RestClient(api_url)
    task_id, entry_id = str(uuid.uuid4()), str(uuid.uuid4())
    task_version: int | None = None
    task_created = False
    scenarios: dict[str, Any] = {}
    failure: VerificationFailure | None = None
    try:
        require(unauthenticated.request("GET", f"/v1/user-tasks/{task_id}/activity", scenario="unauthenticated"), 401, "unauthenticated")
        scenarios["unauthenticated"] = {"status": "passed"}

        created_task = client.request("POST", "/v1/user-tasks", body=task_payload(task_id), scenario="task_create")
        require(created_task, 200, "task_create")
        task_created = True
        task = record(created_task, "task", "task_create")
        task_version = task.get("version") if isinstance(task.get("version"), int) else None
        if task_version is None:
            raise VerificationFailure("task_create", "task_version_missing")

        payload = activity_payload(entry_id)
        created = client.request("POST", f"/v1/user-tasks/{task_id}/activity", body=payload, scenario="activity_create")
        require(created, 200, "activity_create")
        assert_ciphertext_projection(record(created, "entry", "activity_create"), entry_id, "activity_create")

        retried = client.request("POST", f"/v1/user-tasks/{task_id}/activity", body=payload, scenario="activity_idempotency")
        require(retried, 200, "activity_idempotency")
        assert_ciphertext_projection(record(retried, "entry", "activity_idempotency"), entry_id, "activity_idempotency")
        scenarios["activity_create_and_idempotency"] = {"status": "passed"}

        listed = client.request("GET", f"/v1/user-tasks/{task_id}/activity", scenario="activity_list")
        require(listed, 200, "activity_list")
        entries = listed.payload.get("entries")
        matching = [entry for entry in entries if isinstance(entry, dict) and entry.get("entry_id") == entry_id] if isinstance(entries, list) else []
        if len(matching) != 1:
            raise VerificationFailure("activity_list", "idempotent_entry_not_listed_once")
        assert_ciphertext_projection(matching[0], entry_id, "activity_list")
        scenarios["activity_list_ciphertext_only"] = {"status": "passed"}

        plaintext_rejected = client.request(
            "POST",
            f"/v1/user-tasks/{task_id}/activity",
            body={**activity_payload(str(uuid.uuid4())), "plaintext_message": "forbidden"},
            scenario="plaintext_extra_rejected",
        )
        require(plaintext_rejected, 422, "plaintext_extra_rejected")
        scenarios["plaintext_extra_rejected"] = {"status": "passed"}

        deleted = client.request("DELETE", f"/v1/user-tasks/{task_id}/activity/{entry_id}", scenario="activity_delete")
        require(deleted, 200, "activity_delete")
        assert_tombstone(record(deleted, "entry", "activity_delete"), entry_id, "activity_delete")

        after_delete = client.request("GET", f"/v1/user-tasks/{task_id}/activity", scenario="activity_tombstone_list")
        require(after_delete, 200, "activity_tombstone_list")
        tombstones = [
            entry
            for entry in after_delete.payload.get("entries", [])
            if isinstance(entry, dict) and entry.get("entry_id") == entry_id
        ]
        if len(tombstones) != 1:
            raise VerificationFailure("activity_tombstone_list", "tombstone_not_listed_once")
        assert_tombstone(tombstones[0], entry_id, "activity_tombstone_list")
        scenarios["activity_tombstone"] = {"status": "passed"}
    except VerificationFailure as exc:
        failure = exc
        scenarios.setdefault(exc.scenario, {"status": "failed", "code": exc.code})
    finally:
        cleanup = cleanup_task(client, task_id if task_created else None, task_version)
    if cleanup["status"] != "passed" and failure is None:
        failure = VerificationFailure("cleanup", "cleanup_failed")
        scenarios["cleanup"] = {"status": "failed", "code": "cleanup_failed"}
    return {
        "status": "failed" if failure else "passed",
        "classification": classification(),
        "scenarios": scenarios,
        "cleanup": cleanup,
    }, 1 if failure else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("OPENMATES_API_URL", DEFAULT_API_URL))
    parser.add_argument("--web-origin")
    parser.add_argument("--slot", default=os.getenv("OPENMATES_TEST_ACCOUNT_SOURCE_SLOT"))
    args = parser.parse_args(argv)
    try:
        api_url = validate_api_url(args.api_url)
        with tempfile.TemporaryDirectory(prefix="openmates-task-activity-api-") as home:
            headers = login_test_account(api_url, Path(home), args.slot, args.web_origin or derive_web_origin(api_url))
            report, exit_code = run(api_url, headers)
    except VerificationFailure as exc:
        report, exit_code = {
            "status": "failed",
            "classification": classification(),
            "scenarios": {exc.scenario: {"status": "failed", "code": exc.code}},
            "cleanup": {"status": "not_started", "failed_resources": []},
        }, 1
    except Exception:
        report, exit_code = {
            "status": "failed",
            "classification": classification(),
            "scenarios": {"internal": {"status": "failed", "code": "unexpected_internal_error"}},
            "cleanup": {"status": "unknown", "failed_resources": []},
        }, 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
