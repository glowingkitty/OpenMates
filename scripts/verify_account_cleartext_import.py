#!/usr/bin/env python3
"""Verify cleartext Account Import encryption fixtures.

Purpose: prove cleartext export content is re-encrypted before durable writes.
Architecture: deterministic synthetic fixture over the pip SDK crypto builders,
which mirror npm/CLI storage payload construction.
Security: imported payloads must not include old exported keys or plaintext
private fields in durable create requests.
Spec: docs/specs/sdk-cleartext-encryption-boundary/spec.yml.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/openmates-python"))

from openmates.sdk import _build_plan_create_input, _build_project_create_input, _build_task_create_input  # noqa: E402


PLAINTEXT_MARKERS = ("Imported task", "Imported plan", "Imported project", "Imported description")
FORBIDDEN_STORAGE_KEYS = {"title", "description", "name", "master_key", "task_key", "project_key", "key_wrappers"}


def assert_encrypted_payload(payload: dict[str, object], *, encrypted_key: str | None, encrypted_fields: tuple[str, ...], allow_key_wrappers: bool = False) -> list[str]:
    failures: list[str] = []
    if encrypted_key is not None and not isinstance(payload.get(encrypted_key), str):
        failures.append(f"missing {encrypted_key}")
    for field in encrypted_fields:
        if not isinstance(payload.get(field), str):
            failures.append(f"missing {field}")
    forbidden_keys = FORBIDDEN_STORAGE_KEYS - ({"key_wrappers"} if allow_key_wrappers else set())
    for key in forbidden_keys:
        if key in payload:
            failures.append(f"durable payload contains plaintext/import key {key}")
    serialized = json.dumps(payload, sort_keys=True)
    for marker in PLAINTEXT_MARKERS:
        if marker in serialized:
            failures.append(f"durable payload contains plaintext marker {marker}")
    return failures


def verify_synthetic() -> list[str]:
    master_key = bytes([17]) * 32
    fake_client = type("FakeClient", (), {"_get_master_key": lambda _self: master_key})()
    task_payload = _build_task_create_input(master_key, {
        "title": "Imported task",
        "description": "Imported description",
        "labels": ["imported"],
    })
    plan_payload = _build_plan_create_input(fake_client, {
        "title": "Imported plan",
        "goal": "Imported description",
    })
    project_payload = _build_project_create_input(master_key, {
        "name": "Imported project",
        "description": "Imported description",
    })
    failures = assert_encrypted_payload(task_payload, encrypted_key="encrypted_task_key", encrypted_fields=("encrypted_title", "encrypted_description"))
    failures.extend(assert_encrypted_payload(plan_payload, encrypted_key=None, encrypted_fields=("encrypted_title", "encrypted_goal"), allow_key_wrappers=True))
    wrappers = plan_payload.get("key_wrappers")
    if not isinstance(wrappers, list) or not any(isinstance(wrapper, dict) and wrapper.get("key_type") == "master" and isinstance(wrapper.get("encrypted_plan_key"), str) for wrapper in wrappers):
        failures.append("missing master plan key wrapper")
    failures.extend(assert_encrypted_payload(project_payload, encrypted_key="encrypted_project_key", encrypted_fields=("encrypted_name", "encrypted_description"), allow_key_wrappers=True))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify cleartext Account Import encryption fixtures.")
    parser.add_argument("--fixture", choices=["synthetic"], required=True)
    args = parser.parse_args()
    failures = verify_synthetic() if args.fixture == "synthetic" else []
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("PASS account cleartext import")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
