#!/usr/bin/env python3
"""
Regression tests for durable failed-test debug campaigns.

The tests use the Directus-shaped in-memory store and never dispatch real test
runs. They lock down campaign scope, group evidence, child failures, and resume
behavior before the production control-plane implementation changes.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from subprocess import CompletedProcess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_CONTROL_PATH = PROJECT_ROOT / "scripts" / "tests.py"


def load_tests_control(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("openmates_campaign_tests_control", TESTS_CONTROL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    results_dir = tmp_path / "test-results"
    monkeypatch.setattr(module, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(module, "TRIAGE_FILE", results_dir / "triage.json")
    monkeypatch.setattr(module, "TEST_FILE_INDEX_FILE", results_dir / "index.json")
    monkeypatch.setattr(module, "LEASE_LOCK_FILE", tmp_path / "leases.lock")
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module, "SPEC_DIR", tmp_path / "specs")
    monkeypatch.setattr(module, "TEST_STORE", module.InMemoryTestControlStore())
    return module


def failed_run(*names: str, run_id: str = "run-red") -> dict:
    tests = [
        {
            "name": name,
            "file": name,
            "status": "failed",
            "error": "Locator expected visible but the shared control was missing",
        }
        for name in names
    ]
    return {
        "run_id": run_id,
        "git_sha": "red123abc",
        "environment": "development",
        "summary": {"total": len(tests), "passed": 0, "failed": len(tests), "skipped": 0},
        "suites": {"playwright": {"status": "failed", "tests": tests}},
    }


def passed_run(names: list[str], run_id: str, commit: str, campaign_key: str, group_key: str, result_names: list[str] | None = None) -> dict:
    result_names = result_names or names
    return {
        "run_id": run_id,
        "git_sha": commit,
        "environment": "development",
        "requested_tests": [f"playwright::{name}" for name in names],
        "campaign_key": campaign_key,
        "debug_group_key": group_key,
        "summary": {"total": len(result_names), "passed": len(result_names), "failed": 0, "skipped": 0},
        "suites": {
            "playwright": {
                "status": "passed",
                "tests": [{"name": name, "file": name, "status": "passed"} for name in result_names],
            }
        },
    }


def test_campaign_start_freezes_scope_and_resumes_active_session(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("first.spec.ts", "second.spec.ts"))

    first = control.start_debug_campaign(session_id="session-1")
    resumed = control.start_debug_campaign(session_id="session-1")

    assert resumed["campaign_key"] == first["campaign_key"]
    assert first["selected_test_keys"] == [
        "playwright::first.spec.ts",
        "playwright::second.spec.ts",
    ]
    groups = control.debug_groups_for_campaign(first["campaign_key"])
    assert len(groups) == 1
    assert groups[0]["member_test_keys"] == first["selected_test_keys"]
    assert groups[0]["red_evidence"]["run_keys"] == ["run-red"]
    assert 1_000_000_000 <= groups[0]["selected_at_unix"] <= 2_147_483_647


def test_campaign_start_repairs_campaign_left_without_groups(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("first.spec.ts"))
    now = control.utc_now()
    campaign = control.get_store().create_debug_campaign({
        "campaign_key": "debug-campaign-interrupted",
        "title": "Interrupted campaign",
        "status": "active",
        "session_id": "session-1",
        "source_run_keys": ["run-red"],
        "selected_test_keys": ["playwright::first.spec.ts"],
        "selected_group_keys": [],
        "current_group_key": None,
        "completion_policy": {"group_members_must_pass": True, "combined_final_run_required": False},
        "blocker": None,
        "metadata": {"scope_amendments": []},
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
    })

    resumed = control.start_debug_campaign(session_id="session-1")

    assert resumed["campaign_key"] == campaign["campaign_key"]
    assert len(resumed["selected_group_keys"]) == 1
    assert control.debug_groups_for_campaign(campaign["campaign_key"])[0]["member_test_keys"] == [
        "playwright::first.spec.ts"
    ]


def test_campaign_start_resumes_matching_scope_from_new_session(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("first.spec.ts"))
    first = control.start_debug_campaign(session_id="session-1")

    resumed = control.start_debug_campaign(session_id="session-2")

    assert resumed["campaign_key"] == first["campaign_key"]
    assert resumed["session_id"] == "session-2"


def test_campaign_group_persists_acceptance_attempts_and_blocker(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("billing-settings.spec.ts"))
    campaign = control.start_debug_campaign(session_id="session-1")
    group = control.debug_groups_for_campaign(campaign["campaign_key"])[0]

    prepared = control.prepare_debug_group(
        group["group_key"],
        expected_behavior="Credit controls and the payment iframe are visible.",
        acceptance_criteria=["credit controls are visible", "payment iframe is visible"],
    )
    attempted = control.append_debug_group_attempt(
        group["group_key"],
        approach="Check payment capability registration.",
        outcome="failed",
        summary="Capability remained disabled.",
        run_keys=["run-check-1"],
    )
    blocked = control.block_debug_group(
        group["group_key"],
        reason="Dev payment capability requires a product decision.",
        question="Should payment capability be enabled on dev?",
        next_action="Confirm dev capability policy, then rerun billing-settings.spec.ts.",
    )

    assert prepared["expected_behavior"].startswith("Credit controls")
    assert prepared["acceptance_criteria"] == ["credit controls are visible", "payment iframe is visible"]
    assert attempted["attempts"][0]["outcome"] == "failed"
    assert blocked["status"] == "blocked"
    status = control.debug_campaign_status(campaign["campaign_key"])
    assert status["campaign"]["status"] == "blocked"
    assert status["next_action"].startswith("Confirm dev capability")


def test_complete_group_requires_green_evidence_for_every_member(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("first.spec.ts", "second.spec.ts"))
    campaign = control.start_debug_campaign(session_id="session-1")
    group = control.debug_groups_for_campaign(campaign["campaign_key"])[0]

    control.record_run_result(passed_run(
        ["first.spec.ts", "second.spec.ts"],
        "run-green-1",
        "fix111abc",
        campaign["campaign_key"],
        group["group_key"],
        result_names=["first.spec.ts"],
    ))
    with pytest.raises(RuntimeError, match="second.spec.ts"):
        control.complete_debug_group(group["group_key"], commit="fix111abc")

    control.record_run_result(passed_run(
        ["first.spec.ts", "second.spec.ts"],
        "run-green-2",
        "fix222abc",
        campaign["campaign_key"],
        group["group_key"],
    ))
    completed = control.complete_debug_group(group["group_key"], commit="fix222abc")

    assert completed["status"] == "green"
    assert {item["test_key"] for item in completed["green_evidence"]} == set(group["member_test_keys"])
    assert control.debug_campaign_status(campaign["campaign_key"])["campaign"]["status"] == "completed"


def test_campaign_bound_failure_is_added_as_child_group(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("account-preflight.spec.ts"))
    campaign = control.start_debug_campaign(session_id="session-1")
    parent = control.debug_groups_for_campaign(campaign["campaign_key"])[0]

    child_run = failed_run("example-chats-load.spec.ts", run_id="run-child-red")
    children = control.add_debug_child_groups(campaign["campaign_key"], parent["group_key"], child_run)

    assert len(children) == 1
    assert children[0]["parent_group_key"] == parent["group_key"]
    assert children[0]["member_test_keys"] == ["playwright::example-chats-load.spec.ts"]
    assert "run-child-red" in children[0]["red_evidence"]["run_keys"]
    status = control.debug_campaign_status(campaign["campaign_key"])
    assert status["campaign"]["status"] == "active"
    assert children[0]["group_key"] in status["campaign"]["selected_group_keys"]


def test_campaign_group_selection_ignores_local_failure_artifacts(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("first.spec.ts", "second.spec.ts"))
    campaign = control.start_debug_campaign(session_id="session-1")
    group = control.debug_groups_for_campaign(campaign["campaign_key"])[0]
    control.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (control.RESULTS_DIR / "last-run.json").write_text(
        '{"tests":[{"name":"unrelated.spec.ts","status":"failed"}]}',
        encoding="utf-8",
    )

    selection = control.debug_group_test_keys(campaign["campaign_key"], group["group_key"])

    assert selection == ["playwright::first.spec.ts", "playwright::second.spec.ts"]
    assert "unrelated.spec.ts" not in " ".join(selection)


def test_campaign_next_lease_links_complete_durable_group(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("first.spec.ts", "second.spec.ts"))
    campaign = control.start_debug_campaign(session_id="session-1")

    lease = control.claim_next_debug_group(campaign["campaign_key"], session_id="session-1")

    assert lease is not None
    assert lease["campaign_key"] == campaign["campaign_key"]
    assert lease["debug_group_key"] == campaign["selected_group_keys"][0]
    assert lease["entry"]["member_test_keys"] == campaign["selected_test_keys"]


def test_specific_campaign_group_lease_is_atomic(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("first.spec.ts", run_id="run-one"))
    campaign = control.start_debug_campaign(session_id="coordinator")
    group = control.debug_groups_for_campaign(campaign["campaign_key"])[0]

    first = control.claim_debug_group(
        campaign["campaign_key"],
        group["group_key"],
        session_id="worker-one",
        worker_id="chat-one",
    )
    second = control.claim_debug_group(
        campaign["campaign_key"],
        group["group_key"],
        session_id="worker-two",
        worker_id="chat-two",
    )

    assert first is not None
    assert first["debug_group_key"] == group["group_key"]
    assert second is None


def test_specific_group_lease_atomically_rejects_active_file_overlap(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("first.spec.ts", run_id="run-one"))
    campaign = control.start_debug_campaign(session_id="coordinator")
    first_group = control.debug_groups_for_campaign(campaign["campaign_key"])[0]
    second_group = control.get_store().create_debug_group({
        **first_group,
        "group_key": "second-group",
        "triage_group_id": "test_infra-second",
        "member_test_keys": ["vitest::second.test.ts"],
    })

    first = control.claim_debug_group(
        campaign["campaign_key"],
        first_group["group_key"],
        session_id="worker-one",
        worker_id="chat-one",
        linked_files=["frontend/shared.ts"],
    )
    second = control.claim_debug_group(
        campaign["campaign_key"],
        second_group["group_key"],
        session_id="worker-two",
        worker_id="chat-two",
        linked_files=["frontend/shared.ts"],
    )

    assert first is not None
    assert second is None


def test_parallel_group_selection_rejects_high_risk_and_file_overlap(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    groups = [
        {
            "group_key": "safe-one",
            "triage_group_id": "test_infra-one",
            "status": "selected",
            "member_test_keys": ["vitest::first.test.ts"],
            "metadata": {"category": "test_infra", "linked_files": ["frontend/first.test.ts"]},
        },
        {
            "group_key": "overlap",
            "triage_group_id": "unit_regression-overlap",
            "status": "selected",
            "member_test_keys": ["pytest_unit::second.py::test_second"],
            "metadata": {"category": "unit_regression", "linked_files": ["frontend/first.test.ts"]},
        },
        {
            "group_key": "high-risk",
            "triage_group_id": "chat_sync_encryption-risk",
            "status": "selected",
            "member_test_keys": ["playwright::sync.spec.ts"],
            "metadata": {"category": "chat_sync_encryption", "linked_files": ["frontend/sync.ts"]},
        },
        {
            "group_key": "safe-two",
            "triage_group_id": "unit_regression-two",
            "status": "selected",
            "member_test_keys": ["pytest_unit::third.py::test_third"],
            "metadata": {"category": "unit_regression", "linked_files": ["backend/third.py"]},
        },
    ]

    selection = control.select_parallel_debug_groups(groups, active_group_keys=set(), max_workers=3)

    assert [item["group_key"] for item in selection["selected"]] == ["safe-one", "safe-two"]
    assert selection["skipped"]["overlap"] == "linked files overlap another selected group"
    assert selection["skipped"]["high-risk"] == "high-risk category requires dedicated supervision"

    active_overlap = control.select_parallel_debug_groups(
        [groups[0]],
        active_group_keys=set(),
        max_workers=1,
        active_linked_files={"frontend/first.test.ts"},
    )
    assert active_overlap["selected"] == []
    assert active_overlap["skipped"]["safe-one"] == "linked files overlap another selected group"


def test_parallel_dispatch_leases_and_spawns_three_visible_workers(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    now = control.utc_now()
    campaign_key = "debug-campaign-parallel"
    groups = []
    control.get_store().create_debug_campaign({
        "campaign_key": campaign_key,
        "title": "Parallel test",
        "status": "active",
        "session_id": "coordinator",
        "source_run_keys": ["run-red"],
        "selected_test_keys": [],
        "selected_group_keys": [],
        "current_group_key": None,
        "completion_policy": {"group_members_must_pass": True, "combined_final_run_required": False},
        "blocker": None,
        "metadata": {"scope_amendments": []},
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
    })
    for index in range(1, 4):
        group = control.get_store().create_debug_group({
            "group_key": f"group-{index}",
            "campaign_key": campaign_key,
            "triage_group_id": f"test_infra-{index}",
            "parent_group_key": None,
            "status": "selected",
            "member_test_keys": [f"vitest::frontend/test-{index}.test.ts"],
            "observed_failure": "test infrastructure failed",
            "expected_behavior": "",
            "acceptance_criteria": [],
            "root_cause": {},
            "attempts": [],
            "red_evidence": {"run_keys": ["run-red"], "result_keys": []},
            "green_evidence": [],
            "blocker": None,
            "verification_command": f"python3 scripts/tests.py run --campaign {campaign_key} --group group-{index}",
            "selected_at": now,
            "selected_at_unix": 1_700_000_000,
            "updated_at": now,
            "metadata": {
                "category": "test_infra",
                "linked_files": [f"frontend/test-{index}.test.ts"],
            },
        })
        groups.append(group)
    control.get_store().update_debug_campaign(campaign_key, {
        "selected_group_keys": [group["group_key"] for group in groups],
        "selected_test_keys": [key for group in groups for key in group["member_test_keys"]],
    })
    launches = []

    def capture_run(command, **_kwargs):
        launches.append(command)
        return CompletedProcess(command, 0, stdout="Session spawned", stderr="")

    monkeypatch.setattr(control.subprocess, "run", capture_run)
    monkeypatch.setattr(control, "build_triage", lambda: {"groups": []})
    monkeypatch.setattr(control, "available_zellij_session_slots", lambda: 3)

    result = control.dispatch_parallel_debug_chats(campaign_key, "coordinator", max_workers=3)

    assert len(result["spawned"]) == 3
    assert len(launches) == 3
    assert all("spawn-chat" in command and "--mode" in command and "execute" in command for command in launches)
    assert all("claude" not in " ".join(command).lower() for command in launches)
    status = control.debug_campaign_status(campaign_key)
    assert len(status["workers"]) == 3
    assert {worker["worker_id"] for worker in status["workers"]} == {
        item["chat_name"] for item in result["spawned"]
    }


def test_campaign_run_options_are_control_plane_only(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)

    options = control.parse_control_run_options([
        "--campaign", "campaign-1", "--group", "group-1", "--gate-deploy",
    ])

    assert options.campaign_key == "campaign-1"
    assert options.debug_group_key == "group-1"
    assert options.forwarded_args == []
    assert options.gate_deploy is True


def test_group_completion_rejects_unrelated_passing_run(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("first.spec.ts"))
    campaign = control.start_debug_campaign(session_id="session-1")
    group = control.debug_groups_for_campaign(campaign["campaign_key"])[0]
    unrelated = passed_run(
        ["first.spec.ts"], "run-unrelated", "other111", "another-campaign", "another-group"
    )
    control.record_run_result(unrelated)

    with pytest.raises(RuntimeError, match="first.spec.ts"):
        control.complete_debug_group(group["group_key"], commit="other111")


def test_non_playwright_campaign_selection_fails_closed(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)

    with pytest.raises(RuntimeError, match="false group evidence"):
        control.campaign_runner_args(["cli::cli-integration/apps-web-search"], [])


def test_unit_campaign_selection_passes_exact_targets_to_runner(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)

    pytest_args, pytest_targets = control.campaign_runner_args(
        ["pytest_unit::backend/tests/test_x.py::test_x"], []
    )
    vitest_args, vitest_targets = control.campaign_runner_args(
        ["vitest::frontend/packages/ui/src/example.test.ts"], []
    )

    assert pytest_args == ["--suite", "pytest"]
    assert pytest_targets == ["backend/tests/test_x.py::test_x"]
    assert vitest_args == ["--suite", "vitest"]
    assert vitest_targets == ["frontend/packages/ui/src/example.test.ts"]
