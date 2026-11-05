"""Reject plaintext, wrong Plan wrappers and altered Workflow scope in the peer."""

# contract-test-file: tooling
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from recovery_server import encrypt
from session_plans_workflows_server import CAPABILITY, PlansWorkflowsPeer


def peer(family="plans", team=False):
    suite = json.loads(
        (
            Path(__file__).with_name("fixtures") / "session-plans-workflows.json"
        ).read_bytes()
    )["capabilities"][CAPABILITY]
    vector = next(
        v
        for v in suite["vectors"]
        if v.get("family") == family and v.get("team") is team
    )
    return PlansWorkflowsPeer(suite, vector, "rust")


def plan_payload(target):
    key = bytes(range(64, 96))
    payload = {
        "plan_id": "11111111-1111-4111-8111-111111111111",
        "key_wrappers": [
            {"key_type": "master", "encrypted_plan_key": encrypt(key, target.master)},
            {
                "key_type": "project",
                "hashed_project_id": hashlib.sha256(
                    target.suite["project_id"].encode()
                ).hexdigest(),
                "encrypted_plan_key": encrypt(key, target.project_key),
            },
        ],
        "linked_project_ids": [target.suite["project_id"]],
    }
    for name in ("title", "goal", "scope_in"):
        payload["encrypted_" + name] = encrypt(
            target.suite["input"]["plan"][name].encode(), key
        )
    for name, value in (
        ("user_flows", target.suite["input"]["plan"]["user_flows"]),
        ("linked_project_ids", [target.suite["project_id"]]),
    ):
        payload["encrypted_" + name] = encrypt(json.dumps(value).encode(), key)
    return payload


def test_plan_peer_requires_equal_master_project_keys_and_no_private_plaintext():
    target = peer()
    try:
        payload = plan_payload(target)
        altered = deepcopy(payload)
        altered["key_wrappers"][1]["encrypted_plan_key"] = encrypt(
            bytes(range(32, 64)), target.project_key
        )
        with pytest.raises(AssertionError):
            target.plan_create(altered, json.dumps(altered))
        altered = deepcopy(payload)
        altered["title"] = target.suite["input"]["plan"]["title"]
        with pytest.raises(AssertionError):
            target.plan_create(altered, json.dumps(altered))
        assert "encrypted-plan-private-fields" not in target.checks
        target.plan_create(payload, json.dumps(payload))
        assert {
            "encrypted-plan-private-fields",
            "plan-master-project-wrappers",
        } <= target.checks
    finally:
        target.server.server_close()


def test_workflow_peer_preserves_user_variable_names_and_authenticates_team_slug():
    target = peer("workflows", True)
    try:
        payload = {
            "title": target.suite["input"]["workflow"]["title"],
            "graph": deepcopy(target.suite["input"]["workflow"]["graph"]),
            "team_id": target.suite["team"]["team_id"],
            "encrypted_slug": encrypt(b"synthetic-workflow", target.team),
        }
        altered = deepcopy(payload)
        config = altered["graph"]["nodes"][0]["config"]
        config["project_id"] = config.pop("projectId")
        with pytest.raises(AssertionError):
            target.workflow_create(altered)
        altered = deepcopy(payload)
        altered["encrypted_slug"] = encrypt(b"synthetic-workflow", target.master)
        with pytest.raises(AssertionError, match="ciphertext fingerprint"):
            target.workflow_create(altered)
        assert "encrypted-workflow-slug" not in target.checks
        target.workflow_create(payload)
        assert "opaque-variable-names-preserved" in target.checks
    finally:
        target.server.server_close()
