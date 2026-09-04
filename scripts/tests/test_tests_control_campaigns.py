#!/usr/bin/env python3
"""
Regression tests for durable failed-test debug campaigns.

The tests use the Directus-shaped in-memory store and never dispatch real test
runs. They lock down campaign scope, group evidence, child failures, and resume
behavior before the production control-plane implementation changes.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from subprocess import CompletedProcess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_CONTROL_PATH = PROJECT_ROOT / "scripts" / "tests.py"


def load_tests_control(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)
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
    monkeypatch.setattr(module, "current_git_sha", lambda: "base111")
    monkeypatch.setattr(module, "_known_worker_modified_files", lambda _session_id: [])
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


def create_parallel_campaign(
    control,
    group_count: int = 2,
    campaign_key: str = "debug-campaign-parallel",
    group_prefix: str = "group",
    triage_prefix: str = "test_infra",
) -> tuple[str, list[dict]]:
    now = control.utc_now()
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
    for index in range(1, group_count + 1):
        group_key = f"{group_prefix}-{index}"
        group = control.get_store().create_debug_group({
            "group_key": group_key,
            "campaign_key": campaign_key,
            "triage_group_id": f"{triage_prefix}-{index}",
            "parent_group_key": None,
            "status": "selected",
            "member_test_keys": [f"vitest::frontend/test-{index}.test.ts"],
            "observed_failure": "test infrastructure failed",
            "expected_behavior": "The test passes after the shared control is present.",
            "acceptance_criteria": ["the selected test passes"],
            "root_cause": {},
            "attempts": [],
            "red_evidence": {"run_keys": ["run-red"], "result_keys": []},
            "green_evidence": [],
            "blocker": None,
            "verification_command": f"python3 scripts/tests.py run --campaign {campaign_key} --group {group_key}",
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
    return campaign_key, groups


def test_campaign_start_freezes_scope_and_resumes_active_session(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("first.spec.ts", "second.spec.ts"))

    monkeypatch.setenv("OPENCODE_SESSION_ID", "session-1")
    first = control.start_debug_campaign(session_id="session-1")
    resumed = control.start_debug_campaign(session_id="session-1")
    monkeypatch.setenv("OPENCODE_SESSION_ID", "unrelated-chat")
    with pytest.raises(RuntimeError, match="mismatch"):
        control.start_debug_campaign(session_id="session-1")

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

    monkeypatch.setenv("OPENCODE_SESSION_ID", "session-1")
    resumed = control.start_debug_campaign(session_id="session-1")

    assert resumed["campaign_key"] == campaign["campaign_key"]
    assert len(resumed["selected_group_keys"]) == 1
    assert control.debug_groups_for_campaign(campaign["campaign_key"])[0]["member_test_keys"] == [
        "playwright::first.spec.ts"
    ]


def test_command_registry_exposes_campaign_attempt_choices(tmp_path, monkeypatch, capsys):
    tests_control = load_tests_control(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_registry_should_not_leak")

    assert tests_control.main(["commands", "--json"]) == 0
    raw_output = capsys.readouterr().out
    registry = json.loads(raw_output)

    assert "campaign.attempt" in registry
    attempt_options = {option["name"]: option for option in registry["campaign.attempt"]["options"]}
    assert attempt_options["--outcome"]["required"] is True
    assert attempt_options["--outcome"]["choices"] == ["failed", "blocked", "green", "rejected"]
    assert "pending" not in attempt_options["--outcome"]["choices"]
    assert "campaign.history" not in registry
    assert "ses_registry_should_not_leak" not in raw_output


def test_campaign_start_rejects_matching_scope_takeover_from_new_session(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("first.spec.ts"))
    monkeypatch.setenv("OPENCODE_SESSION_ID", "session-1")
    first = control.start_debug_campaign(session_id="session-1")

    monkeypatch.setenv("OPENCODE_SESSION_ID", "session-2")
    with pytest.raises(RuntimeError, match="campaign coordinator") as excinfo:
        control.start_debug_campaign(session_id="session-2")

    message = str(excinfo.value)
    assert f"campaign status --campaign {first['campaign_key']}" in message
    assert f"campaign start --campaign {first['campaign_key']} --session session-1" in message
    assert control._debug_campaign(first["campaign_key"])["session_id"] == "session-1"


def test_campaign_list_surfaces_resumable_active_campaigns(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("first.spec.ts"))
    monkeypatch.setenv("OPENCODE_SESSION_ID", "session-1")
    campaign = control.start_debug_campaign(session_id="session-1")

    listing = control.list_debug_campaigns(overlap_current_failures=True)

    assert listing["count"] == 1
    summary = listing["campaigns"][0]
    assert summary["campaign_key"] == campaign["campaign_key"]
    assert summary["status"] == "active"
    assert summary["session_id"] == "session-1"
    assert summary["overlap_count"] == 1
    assert summary["overlapping_test_keys"] == ["playwright::first.spec.ts"]
    assert summary["status_command"] == f"python3 scripts/tests.py campaign status --campaign {campaign['campaign_key']} --json"
    assert summary["resume_command"] == (
        f"python3 scripts/tests.py campaign start --campaign {campaign['campaign_key']} --session session-1 --json"
    )


def test_ambiguous_campaign_overlap_returns_structured_selection_without_mutation(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    first_key, _ = create_parallel_campaign(control, group_count=1, campaign_key="campaign-first")
    second_key, _ = create_parallel_campaign(
        control,
        group_count=1,
        campaign_key="campaign-second",
        group_prefix="second-group",
    )
    monkeypatch.setattr(control, "build_triage", lambda: {"entries": [{
        "key": "vitest::frontend/test-1.test.ts",
        "group_id": "test_infra-shared",
    }]})
    before = (
        control.get_store().test_debug_campaigns.copy(),
        control.get_store().test_debug_groups.copy(),
        control.get_store().test_claims.copy(),
    )

    result = control.start_debug_campaign(session_id="session-new")

    assert result == {
        "status": "selection_required",
        "candidate_campaign_keys": [first_key, second_key],
        "selected_test_keys": ["vitest::frontend/test-1.test.ts"],
    }
    assert before == (
        control.get_store().test_debug_campaigns,
        control.get_store().test_debug_groups,
        control.get_store().test_claims,
    )


def test_daily_recovery_links_legacy_campaigns_and_owns_only_unclaimed_failures(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    first_key, _ = create_parallel_campaign(control, group_count=1, campaign_key="campaign-first")
    second_key, second_groups = create_parallel_campaign(
        control,
        group_count=1,
        campaign_key="campaign-second",
        group_prefix="second-group",
    )
    second_test_key = "vitest::frontend/test-2.test.ts"
    control.get_store().update_debug_group(
        second_groups[0]["group_key"],
        {"member_test_keys": [second_test_key]},
    )
    control.get_store().update_debug_campaign(
        second_key,
        {"selected_test_keys": [second_test_key]},
    )
    control.record_run_result(failed_run("first.spec.ts", run_id="run-daily"))
    selected_test_keys = [
        "vitest::frontend/test-1.test.ts",
        second_test_key,
        "vitest::frontend/test-3.test.ts",
    ]
    monkeypatch.setattr(control, "build_triage", lambda: {"entries": [
        {"key": key, "group_id": f"daily-{index}"}
        for index, key in enumerate(selected_test_keys, start=1)
    ]})
    monkeypatch.setenv("OPENCODE_SESSION_ID", "daily-coordinator")
    legacy_state = (
        control._debug_campaign(first_key).copy(),
        control._debug_campaign(second_key).copy(),
        [group.copy() for group in control.debug_groups_for_campaign(first_key)],
        [group.copy() for group in control.debug_groups_for_campaign(second_key)],
    )

    campaign = control.start_debug_campaign(
        session_id="daily-coordinator",
        daily_recovery=True,
    )

    assert campaign["completion_policy"]["daily_recovery_milestone"] is True
    assert campaign["metadata"]["ownership_campaign_keys"] == [first_key, second_key]
    assert campaign["metadata"]["linked_owned_test_keys"] == selected_test_keys[:2]
    assert campaign["selected_test_keys"] == selected_test_keys
    groups = control.debug_groups_for_campaign(campaign["campaign_key"])
    assert [group["member_test_keys"] for group in groups] == [["vitest::frontend/test-3.test.ts"]]
    assert legacy_state == (
        control._debug_campaign(first_key),
        control._debug_campaign(second_key),
        control.debug_groups_for_campaign(first_key),
        control.debug_groups_for_campaign(second_key),
    )
    legacy_metadata = dict(campaign["metadata"])
    legacy_metadata.pop("linked_owned_test_keys")
    control.get_store().update_debug_campaign(campaign["campaign_key"], {"metadata": legacy_metadata})
    resumed = control.start_debug_campaign(session_id="daily-coordinator", daily_recovery=True)
    assert resumed["metadata"]["linked_owned_test_keys"] == selected_test_keys[:2]

    daily_run = {
        "run_id": "run-daily-milestone",
        "flags": {
            "daily": True,
            "suite": "all",
            "only_failed": False,
            "critical_phase": {"status": "passed"},
            "notification_channels": {
                "email": {"configured": True, "status": "provider_accepted"},
                "discord": {"configured": True, "status": "provider_accepted"},
            },
        },
        "summary": {
            "executed_product_failed": 3,
            "infrastructure_incident": 0,
            "dispatch_error": 0,
            "blocked_by_parent": 0,
        },
        "suites": {"vitest": {"tests": [
            {"file": key.removeprefix("vitest::"), "status": "failed"}
            for key in selected_test_keys
        ]}},
    }
    control.record_run_result(daily_run)

    milestone = control.record_daily_recovery_milestone(
        campaign["campaign_key"],
        "run-daily-milestone",
    )

    assert milestone["campaign"]["metadata"]["daily_recovery_milestone"]["checks"][
        "remaining_failures_owned"
    ] is True


def test_daily_recovery_requires_direct_group_for_regression_from_green_linked_group(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    legacy_key, legacy_groups = create_parallel_campaign(control, group_count=2)
    control.get_store().update_debug_group(legacy_groups[0]["group_key"], {"status": "green"})
    regressed_test_key = "vitest::frontend/test-1.test.ts"
    pending_test_key = "vitest::frontend/test-2.test.ts"
    current_entries = [{"key": pending_test_key, "group_id": "daily-pending"}]
    monkeypatch.setattr(control, "build_triage", lambda: {"entries": current_entries})
    monkeypatch.setenv("OPENCODE_SESSION_ID", "daily-coordinator")

    campaign = control.start_debug_campaign(session_id="daily-coordinator", daily_recovery=True)

    assert campaign["metadata"]["ownership_campaign_keys"] == [legacy_key]
    assert campaign["metadata"]["linked_owned_test_keys"] == [pending_test_key]
    assert control.debug_groups_for_campaign(campaign["campaign_key"]) == []
    milestone_run = {
        "run_id": "run-regression",
        "flags": {
            "daily": True,
            "suite": "all",
            "only_failed": False,
            "critical_phase": {"status": "passed"},
            "notification_channels": {
                "email": {"configured": True, "status": "provider_accepted"},
                "discord": {"configured": True, "status": "provider_accepted"},
            },
        },
        "summary": {"executed_product_failed": 1},
        "suites": {"vitest": {"tests": [
            {"file": regressed_test_key.removeprefix("vitest::"), "status": "failed"},
        ]}},
    }
    control.record_run_result(milestone_run)

    unowned = control.record_daily_recovery_milestone(campaign["campaign_key"], "run-regression")

    assert unowned["campaign"]["metadata"]["daily_recovery_milestone"]["unowned_failure_keys"] == [
        regressed_test_key
    ]
    current_entries.append({"key": regressed_test_key, "group_id": "daily-regression"})
    refreshed = control.start_debug_campaign(session_id="daily-coordinator", daily_recovery=True)
    assert [group["member_test_keys"] for group in control.debug_groups_for_campaign(
        refreshed["campaign_key"]
    )] == [[regressed_test_key]]
    owned = control.record_daily_recovery_milestone(campaign["campaign_key"], "run-regression")
    assert owned["campaign"]["metadata"]["daily_recovery_milestone"]["unowned_failure_keys"] == []


def test_daily_result_retains_failed_file_key_when_later_case_passes(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    shared_file = "frontend/shared-file.test.ts"
    run = {
        "run_id": "run-daily",
        "suites": {"vitest": {"tests": [
            {"name": "failed case", "file": shared_file, "status": "failed", "error": "failure"},
            {"name": "passing case", "file": shared_file, "status": "passed"},
        ]}},
    }

    state = control.record_run_result(run, source="daily_runner", workflow="daily")

    assert state["tests"][f"vitest::{shared_file}"]["status"] == "failed"


def test_campaign_start_with_campaign_key_requires_existing_coordinator(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, _groups = create_parallel_campaign(control, group_count=1)

    monkeypatch.setenv("OPENCODE_SESSION_ID", "unrelated-chat")
    with pytest.raises(RuntimeError, match="session mismatch"):
        control.start_debug_campaign(session_id="coordinator", campaign_key=campaign_key)
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    resumed = control.start_debug_campaign(session_id="coordinator", campaign_key=campaign_key)

    assert resumed["campaign_key"] == campaign_key


def test_campaign_handoff_rebinds_coordinator_without_taking_worker_leases(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=2)
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    coordinator_lease = control.claim_next_debug_group(campaign_key, session_id="coordinator")
    worker_lease = control.claim_debug_group(
        campaign_key,
        groups[1]["group_key"],
        session_id="ses-worker",
        worker_id="worker-chat",
        linked_files=["frontend/test-2.test.ts"],
    )

    monkeypatch.setenv("OPENCODE_SESSION_ID", "new-coordinator")
    handed_off = control.handoff_debug_campaign(
        campaign_key,
        from_session="coordinator",
        to_session="new-coordinator",
        reason="Resume from the current visible coordinator chat.",
    )

    assert handed_off["campaign"]["session_id"] == "new-coordinator"
    assert handed_off["from_session"] == "coordinator"
    assert handed_off["to_session"] == "new-coordinator"
    assert handed_off["updated_coordinator_leases"] == [coordinator_lease["lease_id"]]
    campaign = control._debug_campaign(campaign_key)
    assert campaign["metadata"]["coordinator_handoffs"][-1]["to_session"] == "new-coordinator"
    assert control._lease_for_id(coordinator_lease["lease_id"])["session_id"] == "new-coordinator"
    assert control._lease_for_id(worker_lease["lease_id"])["session_id"] == "ses-worker"


def test_campaign_handoff_rejects_active_worker_as_new_coordinator(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=1)
    control.claim_debug_group(
        campaign_key,
        groups[0]["group_key"],
        session_id="ses-worker",
        worker_id="worker-chat",
        linked_files=["frontend/test-1.test.ts"],
    )

    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker")
    with pytest.raises(RuntimeError, match="Active debug workers"):
        control.handoff_debug_campaign(
            campaign_key,
            from_session="coordinator",
            to_session="ses-worker",
            reason="Worker should not become coordinator.",
        )

    assert control._debug_campaign(campaign_key)["session_id"] == "coordinator"


def test_campaign_start_rejects_spoofed_initial_owner(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("first.spec.ts"))

    monkeypatch.setenv("OPENCODE_SESSION_ID", "unrelated-chat")
    with pytest.raises(RuntimeError, match="session mismatch"):
        control.start_debug_campaign(session_id="coordinator")


def test_campaign_group_persists_acceptance_attempts_and_blocker(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("billing-settings.spec.ts"))
    monkeypatch.setenv("OPENCODE_SESSION_ID", "session-1")
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
    monkeypatch.setenv("OPENCODE_SESSION_ID", "unrelated-chat")
    with pytest.raises(RuntimeError, match="campaign coordinator"):
        control.block_debug_group(
            group["group_key"],
            reason="Dev payment capability requires a product decision.",
            question="Should payment capability be enabled on dev?",
            next_action="Confirm dev capability policy, then rerun billing-settings.spec.ts.",
        )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "session-1")
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


def test_campaign_unblock_clears_structural_blocker_and_restores_next_lease(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("audio-recording.spec.ts"))
    monkeypatch.setenv("OPENCODE_SESSION_ID", "session-1")
    campaign = control.start_debug_campaign(session_id="session-1")
    group = control.debug_groups_for_campaign(campaign["campaign_key"])[0]
    control.block_debug_group(
        group["group_key"],
        reason="The fix requires the shared recording layout files.",
        question="Expand the boundary to MessageInput and RecordAudio?",
        next_action="Approve the boundary, then rerun audio-recording.spec.ts.",
    )

    assert control.claim_next_debug_group(campaign["campaign_key"], session_id="session-1") is None
    unblocked = control.unblock_debug_group(
        group["group_key"],
        coordinator_session="session-1",
        reason="User approved the expanded recording layout boundary.",
        approved_files=[
            "frontend/packages/ui/src/components/enter_message/MessageInput.svelte",
            "frontend/packages/ui/src/components/enter_message/RecordAudio.svelte",
        ],
    )
    lease = control.claim_next_debug_group(campaign["campaign_key"], session_id="session-1")

    assert unblocked["group"]["status"] == "ready"
    assert unblocked["campaign"]["status"] == "active"
    assert unblocked["campaign"].get("blocker") is None
    assert lease is not None
    assert lease["debug_group_key"] == group["group_key"]
    linked_files = unblocked["group"]["metadata"]["linked_files"]
    assert "frontend/packages/ui/src/components/enter_message/MessageInput.svelte" in linked_files
    assert "frontend/packages/ui/src/components/enter_message/RecordAudio.svelte" in linked_files


def test_campaign_next_can_lease_explicit_unblocked_group(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=2)
    target = groups[1]
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    control.block_debug_group(
        target["group_key"],
        reason="The second group needs an approved shared helper boundary.",
        question="Approve shared helper edits?",
        next_action="Approve the helper and lease this exact group.",
    )
    control.unblock_debug_group(
        target["group_key"],
        coordinator_session="coordinator",
        reason="User approved the shared helper boundary.",
        approved_files=["frontend/shared-helper.ts"],
    )

    lease = control.claim_next_debug_group(
        campaign_key,
        session_id="coordinator",
        group_key=target["group_key"],
    )

    assert lease is not None
    assert lease["debug_group_key"] == target["group_key"]


def test_complete_group_requires_green_evidence_for_every_member(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("first.spec.ts", "second.spec.ts"))
    monkeypatch.setenv("OPENCODE_SESSION_ID", "session-1")
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
    monkeypatch.setenv("OPENCODE_SESSION_ID", "session-1")
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
    assert control.debug_campaign_status(campaign["campaign_key"])["campaign"]["status"] == "verification_pending"


def test_campaign_completes_only_after_full_zero_failure_run(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("first.spec.ts"))
    monkeypatch.setenv("OPENCODE_SESSION_ID", "session-1")
    campaign = control.start_debug_campaign(session_id="session-1")
    group = control.debug_groups_for_campaign(campaign["campaign_key"])[0]
    control.record_run_result(passed_run(
        ["first.spec.ts"], "run-group-green", "fix111abc", campaign["campaign_key"], group["group_key"]
    ))
    control.complete_debug_group(group["group_key"], commit="fix111abc")
    full_run = {
        "run_id": "run-full-green",
        "campaign_key": campaign["campaign_key"],
        "flags": {"daily": True, "suite": "all", "only_failed": False},
        "suites": {
            "playwright": {"status": "passed", "lane": "deterministic", "tests": [
                {"name": "first.spec.ts", "file": "first.spec.ts", "status": "passed"},
            ]},
            "api_live": {"status": "passed", "lane": "live_probe", "tests": [
                {"name": "gmail_delivery", "status": "passed"},
            ]},
        },
    }
    control.record_run_result(full_run)

    result = control.finalize_debug_campaign(campaign["campaign_key"], "run-full-green")

    assert result["campaign"]["status"] == "completed"
    assert result["campaign"]["metadata"]["final_full_run"]["run_key"] == "run-full-green"


def test_failed_full_run_adds_new_child_group_to_same_campaign(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("first.spec.ts"))
    monkeypatch.setenv("OPENCODE_SESSION_ID", "session-1")
    campaign = control.start_debug_campaign(session_id="session-1")
    parent = control.debug_groups_for_campaign(campaign["campaign_key"])[0]
    control.record_run_result(passed_run(
        ["first.spec.ts"], "run-group-green", "fix111abc", campaign["campaign_key"], parent["group_key"]
    ))
    control.complete_debug_group(parent["group_key"], commit="fix111abc")
    full_run = {
        "run_id": "run-full-red",
        "campaign_key": campaign["campaign_key"],
        "flags": {"daily": True, "suite": "all", "only_failed": False},
        "suites": {
            "playwright": {"status": "failed", "lane": "deterministic", "tests": [
                {"name": "first.spec.ts", "file": "first.spec.ts", "status": "passed"},
                {"name": "new.spec.ts", "file": "new.spec.ts", "status": "failed", "error": "new regression"},
            ]},
            "api_live": {"status": "passed", "lane": "live_probe", "tests": [
                {"name": "gmail_delivery", "status": "passed"},
            ]},
        },
    }
    control.record_run_result(full_run)

    result = control.finalize_debug_campaign(campaign["campaign_key"], "run-full-red")

    assert result["campaign"]["status"] == "active"
    children = [group for group in result["groups"] if group.get("parent_group_key") == parent["group_key"]]
    assert len(children) == 1
    assert children[0]["member_test_keys"] == ["playwright::new.spec.ts"]


def test_complete_vercel_gate_child_from_later_successful_parent_dispatch(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    parent_specs = ["ai-response-language.spec.ts", "message-sync.spec.ts"]
    control.record_run_result(failed_run("ai-response-language.spec.ts"))
    monkeypatch.setenv("OPENCODE_SESSION_ID", "session-1")
    campaign = control.start_debug_campaign(session_id="session-1")
    parent = control.debug_groups_for_campaign(campaign["campaign_key"])[0]
    parent = control.get_store().update_debug_group(
        parent["group_key"],
        {"member_test_keys": [f"playwright::{spec}" for spec in parent_specs]},
    )

    children = control.add_debug_child_groups(
        campaign["campaign_key"],
        parent["group_key"],
        failed_run("vercel-deployment-gate", run_id="run-vercel-gate-red"),
    )
    assert len(children) == 1
    child = children[0]
    assert child["member_test_keys"] == ["playwright::vercel-deployment-gate"]

    incomplete_gate_cases = [
        ("no-gate-fields", {}),
        ("missing-deployment-verified", {"gate_deploy": True}),
        ("missing-gate-deploy", {"deployment_verified": True}),
        ("false-deployment-verified", {"gate_deploy": True, "deployment_verified": False}),
        ("false-gate-deploy", {"gate_deploy": False, "deployment_verified": True}),
    ]
    for suffix, gate_fields in incomplete_gate_cases:
        incomplete_run = passed_run(
            parent_specs,
            f"run-parent-green-{suffix}",
            "fix222abc",
            campaign["campaign_key"],
            parent["group_key"],
        )
        incomplete_run.update(gate_fields)
        control.record_run_result(incomplete_run)
        control.complete_debug_group(parent["group_key"], commit="fix222abc")
        with pytest.raises(RuntimeError, match="vercel-deployment-gate"):
            control.complete_debug_group(child["group_key"], commit="fix222abc")

    partial_gated_run = passed_run(
        ["ai-response-language.spec.ts"],
        "run-parent-green-partial",
        "fix222abc",
        campaign["campaign_key"],
        parent["group_key"],
    )
    partial_gated_run["gate_deploy"] = True
    partial_gated_run["deployment_verified"] = True
    control.record_run_result(partial_gated_run)
    control.complete_debug_group(parent["group_key"], commit="fix222abc")
    with pytest.raises(RuntimeError, match="vercel-deployment-gate"):
        control.complete_debug_group(child["group_key"], commit="fix222abc")

    duplicate_request_run = passed_run(
        parent_specs,
        "run-parent-green-duplicate-request",
        "fix222abc",
        campaign["campaign_key"],
        parent["group_key"],
    )
    duplicate_request_run["gate_deploy"] = True
    duplicate_request_run["deployment_verified"] = True
    duplicate_request_run["requested_tests"] = [
        "playwright::ai-response-language.spec.ts",
        "playwright::message-sync.spec.ts",
        "playwright::message-sync.spec.ts",
    ]
    control.record_run_result(duplicate_request_run)
    control.complete_debug_group(parent["group_key"], commit="fix222abc")
    with pytest.raises(RuntimeError, match="vercel-deployment-gate"):
        control.complete_debug_group(child["group_key"], commit="fix222abc")

    invalid_time_run = passed_run(
        parent_specs,
        "run-parent-green-invalid-time",
        "fix222abc",
        campaign["campaign_key"],
        parent["group_key"],
    )
    invalid_time_run["gate_deploy"] = True
    invalid_time_run["deployment_verified"] = True
    control.record_run_result(invalid_time_run)
    for result in control.get_store().test_results.values():
        if result.get("run_key") == "run-parent-green-invalid-time":
            result["created_at"] = "not-a-timestamp"
    control.complete_debug_group(parent["group_key"], commit="fix222abc")
    with pytest.raises(RuntimeError, match="vercel-deployment-gate"):
        control.complete_debug_group(child["group_key"], commit="fix222abc")

    naive_time_run = passed_run(
        parent_specs,
        "run-parent-green-naive-time",
        "fix222abc",
        campaign["campaign_key"],
        parent["group_key"],
    )
    naive_time_run["gate_deploy"] = True
    naive_time_run["deployment_verified"] = True
    control.record_run_result(naive_time_run)
    for result in control.get_store().test_results.values():
        if result.get("run_key") == "run-parent-green-naive-time":
            result["created_at"] = "2999-01-01T00:00:00"
    control.complete_debug_group(parent["group_key"], commit="fix222abc")
    with pytest.raises(RuntimeError, match="vercel-deployment-gate"):
        control.complete_debug_group(child["group_key"], commit="fix222abc")

    preselection_run = passed_run(
        parent_specs,
        "run-parent-green-preselection",
        "fix222abc",
        campaign["campaign_key"],
        parent["group_key"],
    )
    preselection_run["gate_deploy"] = True
    preselection_run["deployment_verified"] = True
    control.record_run_result(preselection_run)
    for result in control.get_store().test_results.values():
        if result.get("run_key") == "run-parent-green-preselection":
            result["created_at"] = "2000-01-01T00:00:00Z"
    control.complete_debug_group(parent["group_key"], commit="fix222abc")
    with pytest.raises(RuntimeError, match="vercel-deployment-gate"):
        control.complete_debug_group(child["group_key"], commit="fix222abc")

    bad_summary_cases = [
        ("missing-summary", {}),
        ("skipped-summary", {"total": 2, "passed": 1, "failed": 0, "skipped": 1}),
        ("running-summary", {"total": 2, "passed": 2, "failed": 0, "running": 1}),
    ]
    for suffix, summary in bad_summary_cases:
        bad_summary_run = passed_run(
            parent_specs,
            f"run-parent-green-{suffix}",
            "fix222abc",
            campaign["campaign_key"],
            parent["group_key"],
        )
        bad_summary_run["gate_deploy"] = True
        bad_summary_run["deployment_verified"] = True
        bad_summary_run["summary"] = summary
        control.record_run_result(bad_summary_run)
        control.complete_debug_group(parent["group_key"], commit="fix222abc")
        with pytest.raises(RuntimeError, match="vercel-deployment-gate"):
            control.complete_debug_group(child["group_key"], commit="fix222abc")

    for run_id in ("run-parent-green-a", "run-parent-green-z"):
        gated_run = passed_run(
            parent_specs,
            run_id,
            "fix222abc",
            campaign["campaign_key"],
            parent["group_key"],
        )
        gated_run["gate_deploy"] = True
        gated_run["deployment_verified"] = True
        control.record_run_result(gated_run)
    for result in control.get_store().test_results.values():
        if result.get("run_key") == "run-parent-green-a":
            result["created_at"] = "2999-01-01T01:00:00+01:00"
            result["created_at_unix"] = 32_503_680_000
        if result.get("run_key") == "run-parent-green-z":
            result["created_at"] = "2999-01-01T00:00:00Z"
            result["created_at_unix"] = 32_503_680_000
    control.complete_debug_group(parent["group_key"], commit="fix222abc")
    completed_child = control.complete_debug_group(child["group_key"], commit="fix222abc")

    assert completed_child["status"] == "green"
    assert completed_child["green_evidence"] == [{
        "test_key": "playwright::vercel-deployment-gate",
        "run_key": "run-parent-green-z",
        "result_key": "run-parent-green-z:playwright::vercel-deployment-gate:synthetic-passed",
        "subject_commit": "fix222abc",
        "timestamp": completed_child["green_evidence"][0]["timestamp"],
    }]
    assert control.debug_campaign_status(campaign["campaign_key"])["campaign"]["status"] == "verification_pending"


def test_campaign_bound_failure_is_added_as_child_group(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("account-preflight.spec.ts"))
    monkeypatch.setenv("OPENCODE_SESSION_ID", "session-1")
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
    monkeypatch.setenv("OPENCODE_SESSION_ID", "session-1")
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
    monkeypatch.setenv("OPENCODE_SESSION_ID", "session-1")
    campaign = control.start_debug_campaign(session_id="session-1")

    monkeypatch.setenv("OPENCODE_SESSION_ID", "unrelated-chat")
    with pytest.raises(RuntimeError, match="mismatch"):
        control.claim_next_debug_group(campaign["campaign_key"], session_id="session-1")
    monkeypatch.setenv("OPENCODE_SESSION_ID", "session-1")
    lease = control.claim_next_debug_group(campaign["campaign_key"], session_id="session-1")

    assert lease is not None
    assert lease["campaign_key"] == campaign["campaign_key"]
    assert lease["debug_group_key"] == campaign["selected_group_keys"][0]
    assert lease["entry"]["member_test_keys"] == campaign["selected_test_keys"]


def test_campaign_bound_run_requires_coordinator_identity(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=1)

    monkeypatch.setenv("OPENCODE_SESSION_ID", "unrelated-chat")
    result = control.command_run(["--campaign", campaign_key, "--group", groups[0]["group_key"]])

    assert result == 2


def test_specific_campaign_group_lease_is_atomic(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("first.spec.ts", run_id="run-one"))
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
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
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
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


def test_campaign_next_worker_rejects_active_file_overlap(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("first.spec.ts", run_id="run-one"))
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    campaign = control.start_debug_campaign(session_id="coordinator")
    first_group = control.debug_groups_for_campaign(campaign["campaign_key"])[0]
    control.get_store().create_debug_group({
        **first_group,
        "group_key": "second-group",
        "triage_group_id": "test_infra-second",
        "member_test_keys": ["vitest::second.test.ts"],
        "metadata": {"category": "test_infra", "linked_files": ["frontend/shared.ts"]},
    })
    first = control.claim_debug_group(
        campaign["campaign_key"],
        first_group["group_key"],
        session_id="worker-one",
        worker_id="chat-one",
        linked_files=["frontend/shared.ts"],
    )

    second = control.claim_next_debug_group(
        campaign["campaign_key"],
        session_id="worker-two",
        worker_id="chat-two",
    )

    assert first is not None
    assert second is None


def test_campaign_next_worker_lease_uses_worker_placeholder_session(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, _groups = create_parallel_campaign(control, group_count=1)
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")

    lease = control.claim_next_debug_group(campaign_key, session_id="coordinator", worker_id="worker-chat")

    assert lease is not None
    assert lease["session_id"] == "worker-chat"
    assert lease["worker_id"] == "worker-chat"


def test_specific_group_lease_ignores_released_legacy_worker_claims(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("first.spec.ts", run_id="run-one"))
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    campaign = control.start_debug_campaign(session_id="coordinator")
    group = control.debug_groups_for_campaign(campaign["campaign_key"])[0]
    for index in range(control.MAX_PARALLEL_DEBUG_WORKERS):
        control.get_store().create_claim({
            "lease_id": f"legacy-{index}",
            "claim_key": f"legacy-{index}",
            "group_id": f"legacy-group-{index}",
            "status": "released",
            "session_id": f"legacy-session-{index}",
            "worker_id": f"legacy-worker-{index}",
            "expires_at": control.lease_deadline(),
            "entry": {},
        })

    lease = control.claim_debug_group(
        campaign["campaign_key"],
        group["group_key"],
        session_id="worker-one",
        worker_id="chat-one",
        linked_files=["frontend/first.test.ts"],
    )

    assert lease is not None


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


def test_commit_prefix_matching_requires_unambiguous_length(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)

    assert control._matches_commit_prefix("abcdef1234567890", "abcdef1") is True
    assert control._matches_commit_prefix("abcdef1234567890", "a") is False
    assert control._matches_commit_prefix("abc", "abcdef1234567890") is False


def test_parallel_dispatch_leases_and_spawns_three_visible_workers(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, _groups = create_parallel_campaign(control, group_count=3)
    launches = []

    def capture_run(command, **_kwargs):
        launches.append(command)
        index = len(launches)
        return CompletedProcess(
            command,
            0,
            stdout=(
                f"OpenCode chat spawned: worker-{index}\n"
                f"OpenCode session: ses_worker_{index}\n"
                f"Web chat: https://code.dev.openmates.org/root/session/ses_worker_{index}\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(control.subprocess, "run", capture_run)
    monkeypatch.setattr(control, "current_git_sha", lambda: "base111")
    monkeypatch.setattr(control, "build_triage", lambda: {"groups": []})
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")

    result = control.dispatch_parallel_debug_chats(campaign_key, "coordinator", max_workers=3)

    assert len(result["spawned"]) == 3
    assert len(launches) == 3
    assert all("spawn-chat" in command and "--mode" in command and "execute" in command for command in launches)
    assert all("--no-deploy-instructions" in command for command in launches)
    assert all("claude" not in " ".join(command).lower() for command in launches)
    assert all(item["opencode_session_id"].startswith("ses_worker_") for item in result["spawned"])
    assert all(item["inspect_command"].startswith("python3 scripts/sessions.py chat read ses_worker_") for item in result["spawned"])
    assert all("attach_command" not in item for item in result["spawned"])
    status = control.debug_campaign_status(campaign_key)
    assert len(status["workers"]) == 3
    assert {worker["worker_id"] for worker in status["workers"]} == {
        item["chat_name"] for item in result["spawned"]
    }
    assert {worker["session_id"] for worker in status["workers"]} == {
        item["opencode_session_id"] for item in result["spawned"]
    }
    for claim in control.load_leases()["leases"]:
        assert "launch_status" not in claim
        assert "web_chat" not in claim
        assert (claim["entry"].get("launch") or {}).get("status") == "spawned"


def test_parallel_dispatch_records_pending_launch_metadata(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, _groups = create_parallel_campaign(control, group_count=1)

    def pending_run(command, **_kwargs):
        return CompletedProcess(
            command,
            0,
            stdout=(
                "OpenCode chat spawned: worker-1\n"
                "OpenCode session: pending\n"
                "Web chat: https://code.dev.openmates.org/root/session/pending\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(control.subprocess, "run", pending_run)
    monkeypatch.setattr(control, "current_git_sha", lambda: "base111")
    monkeypatch.setattr(control, "build_triage", lambda: {"groups": []})
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")

    result = control.dispatch_parallel_debug_chats(campaign_key, "coordinator", max_workers=1)

    assert result["spawned"][0]["opencode_session_id"] is None
    claim = control.load_leases()["leases"][0]
    assert (claim["entry"].get("launch") or {}).get("status") == "pending"
    assert "launch_status" not in claim


def test_parallel_dispatch_records_failed_launch_metadata_before_release(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, _groups = create_parallel_campaign(control, group_count=1)

    def failed_run(_command, **_kwargs):
        raise OSError("opencode unavailable")

    monkeypatch.setattr(control.subprocess, "run", failed_run)
    monkeypatch.setattr(control, "current_git_sha", lambda: "base111")
    monkeypatch.setattr(control, "build_triage", lambda: {"groups": []})
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")

    result = control.dispatch_parallel_debug_chats(campaign_key, "coordinator", max_workers=1)

    assert result["spawned"] == []
    claim = control.load_leases()["leases"][0]
    assert claim["status"] == "released"
    assert (claim["entry"].get("launch") or {}).get("status") == "failed"
    assert "launch_status" not in claim


def test_parallel_dispatch_skips_blocked_group_and_spawns_unblocked_workers(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=3)
    launches = []

    def capture_run(command, **_kwargs):
        launches.append(command)
        index = len(launches)
        return CompletedProcess(
            command,
            0,
            stdout=(
                f"OpenCode chat spawned: worker-{index}\n"
                f"OpenCode session: ses_worker_{index}\n"
                f"Web chat: https://code.dev.openmates.org/root/session/ses_worker_{index}\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(control.subprocess, "run", capture_run)
    monkeypatch.setattr(control, "build_triage", lambda: {"groups": []})
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    control.block_debug_group(
        groups[0]["group_key"],
        reason="This group needs user input.",
        question="Which product behavior should this group assert?",
        next_action="Resolve the blocked group, then verify it separately.",
    )

    result = control.dispatch_parallel_debug_chats(campaign_key, "coordinator", max_workers=2)

    assert len(result["spawned"]) == 2
    assert [item["group_key"] for item in result["selected"]] == [groups[1]["group_key"], groups[2]["group_key"]]
    assert result["skipped"][groups[0]["group_key"]] == "group is completed, blocked, or already leased"
    assert len(launches) == 2


def test_lease_required_binds_pending_worker_session(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=1)
    lease = control.claim_debug_group(
        campaign_key,
        groups[0]["group_key"],
        session_id="test-debug-1",
        worker_id="test-debug-1",
        linked_files=["frontend/test-1.test.ts"],
    )

    monkeypatch.setattr(control, "resolve_opencode_session_id_for_name", lambda _name: "ses-real-worker")
    with pytest.raises(RuntimeError, match="does not match"):
        control.require_active_lease(session_id="ses-attacker", lease_id=lease["lease_id"])
    bound = control.require_active_lease(session_id="ses-real-worker", lease_id=lease["lease_id"])

    assert bound["session_id"] == "ses-real-worker"
    assert control._lease_for_id(lease["lease_id"])["session_id"] == "ses-real-worker"


def test_pending_worker_lease_is_gated_before_binding(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=1)
    control.claim_debug_group(
        campaign_key,
        groups[0]["group_key"],
        session_id="test-debug-1",
        worker_id="test-debug-1",
        linked_files=["frontend/test-1.test.ts"],
    )
    monkeypatch.setattr(control, "resolve_opencode_session_id_for_name", lambda _name: "ses-real-worker")

    assert control.worker_session_state("ses-real-worker")["active_worker"] is True
    assert control.worker_session_state("ses-attacker")["active_worker"] is False
    with pytest.raises(RuntimeError, match="approved worker fix intent"):
        control.worker_edit_gate("ses-real-worker", ["frontend/test-1.test.ts"])


def test_debug_worker_lease_release_and_complete_require_owner_or_coordinator(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=2)
    first = control.claim_debug_group(
        campaign_key,
        groups[0]["group_key"],
        session_id="ses-worker-1",
        worker_id="worker-one",
        linked_files=["frontend/test-1.test.ts"],
    )
    second = control.claim_debug_group(
        campaign_key,
        groups[1]["group_key"],
        session_id="ses-worker-2",
        worker_id="worker-two",
        linked_files=["frontend/test-2.test.ts"],
    )

    monkeypatch.setenv("OPENCODE_SESSION_ID", "unrelated-chat")
    with pytest.raises(RuntimeError, match="campaign coordinator"):
        control.release_lease(first["lease_id"], reason="tamper")
    with pytest.raises(RuntimeError, match="campaign coordinator"):
        control.complete_lease(second["lease_id"], commit="base111")
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker-1")
    assert control.release_lease(first["lease_id"], reason="done")["status"] == "released"
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    assert control.complete_lease(second["lease_id"], commit="base111")["status"] == "completed"


def test_parallel_worker_prompt_uses_bash_gate_safe_intent_command(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=1)
    group = {**groups[0], "parallel_linked_files": ["frontend/test-1.test.ts"]}
    lease = {"lease_id": "lease-1"}

    prompt = control._parallel_debug_prompt(campaign_key, group, lease, "worker-one")

    assert "$(git rev-parse HEAD)" not in prompt
    assert "--write-file <path>" not in prompt
    assert "python3 scripts/tests.py campaign intent" in prompt
    assert "--base-commit base111" in prompt
    assert "--write-file frontend/test-1.test.ts" in prompt


def test_worker_intent_records_write_set_before_edit_and_rejects_unlisted_files(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=1)
    group = groups[0]
    lease = control.claim_debug_group(
        campaign_key,
        group["group_key"],
        session_id="ses-worker",
        worker_id="worker-chat",
        linked_files=["frontend/test-1.test.ts"],
    )

    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker")
    intent = control.submit_worker_fix_intent(
        group["group_key"],
        lease["lease_id"],
        worker_id="worker-chat",
        base_commit="base111",
        hypothesis="The assertion helper is stale.",
        write_files=["frontend/test-1.test.ts"],
        verification_command="python3 scripts/tests.py run --campaign debug-campaign-parallel --group group-1",
    )

    worker_intent = intent["metadata"]["worker_intent"]
    assert worker_intent["status"] == "pending"
    assert worker_intent["lease_id"] == lease["lease_id"]
    assert worker_intent["worker_id"] == "worker-chat"
    assert worker_intent["base_commit"] == "base111"
    assert worker_intent["write_files"] == ["frontend/test-1.test.ts"]

    with pytest.raises(RuntimeError, match="outside the approved boundary"):
        control.submit_worker_fix_intent(
            group["group_key"],
            lease["lease_id"],
            worker_id="worker-chat",
            base_commit="base111",
            hypothesis="Needs a shared helper.",
            write_files=["frontend/shared-helper.ts"],
        )


def test_worker_intent_approval_rejects_stale_commit_and_overlapping_write_sets(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=2)
    first_lease = control.claim_debug_group(
        campaign_key,
        groups[0]["group_key"],
        session_id="ses-worker-1",
        worker_id="worker-one",
        linked_files=["frontend/test-1.test.ts"],
    )
    second_lease = control.claim_debug_group(
        campaign_key,
        groups[1]["group_key"],
        session_id="ses-worker-2",
        worker_id="worker-two",
        linked_files=["frontend/test-2.test.ts"],
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker-1")
    control.submit_worker_fix_intent(
        groups[0]["group_key"],
        first_lease["lease_id"],
        worker_id="worker-one",
        base_commit="base111",
        hypothesis="Patch first test helper.",
        write_files=["frontend/test-1.test.ts"],
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker-2")
    stale = control.submit_worker_fix_intent(
        groups[1]["group_key"],
        second_lease["lease_id"],
        worker_id="worker-two",
        base_commit="old999",
        hypothesis="Patch second test helper.",
        write_files=["frontend/test-2.test.ts"],
    )

    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    approved = control.approve_worker_fix_intent(
        groups[0]["group_key"],
        first_lease["lease_id"],
        coordinator_session="coordinator",
        current_commit="base111",
    )
    assert approved["metadata"]["worker_intent"]["status"] == "approved"

    with pytest.raises(RuntimeError, match="stale"):
        control.approve_worker_fix_intent(
            groups[1]["group_key"],
            stale["metadata"]["worker_intent"]["lease_id"],
            coordinator_session="coordinator",
            current_commit="base111",
        )

    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker-2")
    control.submit_worker_fix_intent(
        groups[1]["group_key"],
        second_lease["lease_id"],
        worker_id="worker-two",
        base_commit="base111",
        hypothesis="Patch overlapping helper.",
        write_files=["frontend/test-1.test.ts"],
        boundary_expansion=True,
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    with pytest.raises(RuntimeError, match="overlap"):
        control.approve_worker_fix_intent(
            groups[1]["group_key"],
            second_lease["lease_id"],
            coordinator_session="coordinator",
            current_commit="base111",
        )


def test_worker_intent_approval_uses_checkout_commit_over_cli_override(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=1)
    lease = control.claim_debug_group(
        campaign_key,
        groups[0]["group_key"],
        session_id="ses-worker",
        worker_id="worker-chat",
        linked_files=["frontend/test-1.test.ts"],
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker")
    control.submit_worker_fix_intent(
        groups[0]["group_key"],
        lease["lease_id"],
        worker_id="worker-chat",
        base_commit="base111",
        hypothesis="Patch first helper.",
        write_files=["frontend/test-1.test.ts"],
    )
    monkeypatch.setattr(control, "current_git_sha", lambda: "other999")
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")

    with pytest.raises(RuntimeError, match="stale"):
        control.approve_worker_fix_intent(
            groups[0]["group_key"],
            lease["lease_id"],
            coordinator_session="coordinator",
            current_commit="base111",
        )


def test_worker_intent_approval_fails_closed_when_checkout_commit_unavailable(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=1)
    lease = control.claim_debug_group(
        campaign_key,
        groups[0]["group_key"],
        session_id="ses-worker",
        worker_id="worker-chat",
        linked_files=["frontend/test-1.test.ts"],
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker")
    control.submit_worker_fix_intent(
        groups[0]["group_key"],
        lease["lease_id"],
        worker_id="worker-chat",
        base_commit="base111",
        hypothesis="Patch first helper.",
        write_files=["frontend/test-1.test.ts"],
    )
    monkeypatch.setattr(control, "current_git_sha", lambda: (_ for _ in ()).throw(RuntimeError("git unavailable")))
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")

    with pytest.raises(RuntimeError, match="git unavailable"):
        control.approve_worker_fix_intent(
            groups[0]["group_key"],
            lease["lease_id"],
            coordinator_session="coordinator",
            current_commit="base111",
        )


def test_worker_cannot_self_approve_intent_or_boundary(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=1)
    group = groups[0]
    lease = control.claim_debug_group(
        campaign_key,
        group["group_key"],
        session_id="ses-worker",
        worker_id="worker-chat",
        linked_files=["frontend/test-1.test.ts"],
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker")
    control.submit_worker_fix_intent(
        group["group_key"],
        lease["lease_id"],
        worker_id="ses-worker",
        base_commit="base111",
        hypothesis="Patch first test helper.",
        write_files=["frontend/test-1.test.ts"],
    )
    control.request_debug_group_boundary(
        group["group_key"],
        lease["lease_id"],
        worker_id="ses-worker",
        requested_files=["frontend/shared-helper.ts"],
        reason="The helper is the shared root cause.",
    )

    with pytest.raises(RuntimeError, match="coordinator"):
        control.approve_worker_fix_intent(
            group["group_key"],
            lease["lease_id"],
            coordinator_session="coordinator",
            current_commit="base111",
        )
    with pytest.raises(RuntimeError, match="coordinator"):
        control.approve_debug_group_boundary(
            group["group_key"],
            lease["lease_id"],
            coordinator_session="coordinator",
        )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "unrelated-chat")
    with pytest.raises(RuntimeError, match="mismatch"):
        control.approve_worker_fix_intent(
            group["group_key"],
            lease["lease_id"],
            coordinator_session="coordinator",
            current_commit="base111",
        )


def test_worker_lifecycle_commands_reject_another_workers_lease(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=2)
    first_lease = control.claim_debug_group(
        campaign_key,
        groups[0]["group_key"],
        session_id="ses-worker-1",
        worker_id="worker-one",
        linked_files=["frontend/test-1.test.ts"],
    )
    second_lease = control.claim_debug_group(
        campaign_key,
        groups[1]["group_key"],
        session_id="ses-worker-2",
        worker_id="worker-two",
        linked_files=["frontend/test-2.test.ts"],
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker-2")
    control.submit_worker_fix_intent(
        groups[1]["group_key"],
        second_lease["lease_id"],
        worker_id="worker-two",
        base_commit="base111",
        hypothesis="Patch second test helper.",
        write_files=["frontend/test-2.test.ts"],
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    control.approve_worker_fix_intent(
        groups[1]["group_key"],
        second_lease["lease_id"],
        coordinator_session="coordinator",
        current_commit="base111",
    )

    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)
    with pytest.raises(RuntimeError, match="require OPENCODE_SESSION_ID"):
        control.submit_worker_fix_intent(
            groups[1]["group_key"],
            second_lease["lease_id"],
            worker_id="worker-two",
            base_commit="base111",
            hypothesis="Overwrite without an OpenCode session.",
            write_files=["frontend/test-2.test.ts"],
        )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "worker-two")
    with pytest.raises(RuntimeError, match="does not own"):
        control.submit_worker_fix_intent(
            groups[1]["group_key"],
            second_lease["lease_id"],
            worker_id="worker-two",
            base_commit="base111",
            hypothesis="Use the worker label as identity.",
            write_files=["frontend/test-2.test.ts"],
        )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker-1")

    with pytest.raises(RuntimeError, match="does not own"):
        control.submit_worker_fix_intent(
            groups[1]["group_key"],
            second_lease["lease_id"],
            worker_id="worker-two",
            base_commit="base111",
            hypothesis="Overwrite another worker intent.",
            write_files=["frontend/test-2.test.ts"],
        )
    with pytest.raises(RuntimeError, match="does not own"):
        control.request_debug_group_boundary(
            groups[1]["group_key"],
            second_lease["lease_id"],
            worker_id="worker-two",
            requested_files=["frontend/shared-helper.ts"],
            reason="Try to change another worker boundary.",
        )
    with pytest.raises(RuntimeError, match="does not own"):
        control.finish_debug_worker(
            groups[1]["group_key"],
            second_lease["lease_id"],
            worker_id="worker-two",
            base_commit="base111",
            changed_files=["frontend/test-2.test.ts"],
            summary="Try to finish another worker.",
            current_commit="base111",
        )
    assert first_lease["lease_id"] != second_lease["lease_id"]


def test_active_worker_in_same_campaign_cannot_approve_another_worker(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=2)
    first_lease = control.claim_debug_group(
        campaign_key,
        groups[0]["group_key"],
        session_id="ses-worker-1",
        worker_id="worker-one",
        linked_files=["frontend/test-1.test.ts"],
    )
    control.claim_debug_group(
        campaign_key,
        groups[1]["group_key"],
        session_id="ses-worker-2",
        worker_id="worker-two",
        linked_files=["frontend/test-2.test.ts"],
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker-1")
    control.submit_worker_fix_intent(
        groups[0]["group_key"],
        first_lease["lease_id"],
        worker_id="worker-one",
        base_commit="base111",
        hypothesis="Patch first worker file.",
        write_files=["frontend/test-1.test.ts"],
    )

    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker-2")
    with pytest.raises(RuntimeError, match="worker"):
        control.approve_worker_fix_intent(
            groups[0]["group_key"],
            first_lease["lease_id"],
            coordinator_session="ses-worker-2",
            current_commit="base111",
        )


def test_active_worker_in_different_campaign_cannot_act_as_coordinator(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    target_campaign, target_groups = create_parallel_campaign(
        control,
        group_count=1,
        campaign_key="debug-campaign-target",
        group_prefix="target-group",
        triage_prefix="target-infra",
    )
    worker_campaign, worker_groups = create_parallel_campaign(
        control,
        group_count=1,
        campaign_key="debug-campaign-worker",
        group_prefix="worker-group",
        triage_prefix="worker-infra",
    )
    control.get_store().update_debug_campaign(target_campaign, {"session_id": "ses-cross-worker"})
    target_lease = control.claim_debug_group(
        target_campaign,
        target_groups[0]["group_key"],
        session_id="ses-target-worker",
        worker_id="target-worker",
        linked_files=["frontend/target.test.ts"],
    )
    control.claim_debug_group(
        worker_campaign,
        worker_groups[0]["group_key"],
        session_id="ses-cross-worker",
        worker_id="cross-worker",
        linked_files=["frontend/cross.test.ts"],
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-target-worker")
    control.submit_worker_fix_intent(
        target_groups[0]["group_key"],
        target_lease["lease_id"],
        worker_id="target-worker",
        base_commit="base111",
        hypothesis="Patch target worker file.",
        write_files=["frontend/target.test.ts"],
    )

    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-cross-worker")
    with pytest.raises(RuntimeError, match="Active debug workers"):
        control.approve_worker_fix_intent(
            target_groups[0]["group_key"],
            target_lease["lease_id"],
            coordinator_session="ses-cross-worker",
            current_commit="base111",
        )


def test_active_worker_prepare_and_attempt_cannot_mutate_other_group(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=2)
    control.claim_debug_group(
        campaign_key,
        groups[0]["group_key"],
        session_id="ses-worker-1",
        worker_id="worker-one",
        linked_files=["frontend/test-1.test.ts"],
    )
    control.claim_debug_group(
        campaign_key,
        groups[1]["group_key"],
        session_id="ses-worker-2",
        worker_id="worker-two",
        linked_files=["frontend/test-2.test.ts"],
    )

    with pytest.raises(RuntimeError, match="session is required"):
        control.prepare_debug_group(
            groups[0]["group_key"],
            expected_behavior="The first helper works.",
            acceptance_criteria=["first helper passes"],
        )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    with pytest.raises(RuntimeError, match="does not own"):
        control.append_debug_group_attempt(
            groups[0]["group_key"],
            approach="Record from coordinator.",
            outcome="failed",
            summary="This should not be recorded.",
        )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker-1")

    control.prepare_debug_group(
        groups[0]["group_key"],
        expected_behavior="The first helper works.",
        acceptance_criteria=["first helper passes"],
    )
    control.append_debug_group_attempt(
        groups[0]["group_key"],
        approach="Inspect first helper.",
        outcome="failed",
        summary="Still red.",
    )
    with pytest.raises(RuntimeError, match="does not own"):
        control.prepare_debug_group(
            groups[1]["group_key"],
            expected_behavior="The second helper works.",
            acceptance_criteria=["second helper passes"],
        )
    with pytest.raises(RuntimeError, match="does not own"):
        control.append_debug_group_attempt(
            groups[1]["group_key"],
            approach="Tamper with second helper.",
            outcome="failed",
            summary="This should not be recorded.",
        )


def test_active_worker_prepare_and_attempt_cannot_mutate_unleased_group(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=2)
    control.claim_debug_group(
        campaign_key,
        groups[0]["group_key"],
        session_id="ses-worker-1",
        worker_id="worker-one",
        linked_files=["frontend/test-1.test.ts"],
    )

    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker-1")
    with pytest.raises(RuntimeError, match="does not own"):
        control.prepare_debug_group(
            groups[1]["group_key"],
            expected_behavior="The second helper works.",
            acceptance_criteria=["second helper passes"],
        )
    with pytest.raises(RuntimeError, match="does not own"):
        control.append_debug_group_attempt(
            groups[1]["group_key"],
            approach="Tamper with unleased group.",
            outcome="failed",
            summary="This should not be recorded.",
        )


def test_boundary_expansion_request_is_durable_but_not_authorized(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=1)
    group = groups[0]
    lease = control.claim_debug_group(
        campaign_key,
        group["group_key"],
        session_id="ses-worker",
        worker_id="worker-chat",
        linked_files=["frontend/test-1.test.ts"],
    )

    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker")
    updated = control.request_debug_group_boundary(
        group["group_key"],
        lease["lease_id"],
        worker_id="worker-chat",
        requested_files=["frontend/shared-helper.ts"],
        reason="The helper is the shared root cause.",
        hypothesis="Shared helper returns the wrong selector.",
    )

    request = updated["metadata"]["boundary_request"]
    assert request["status"] == "pending"
    assert request["requested_files"] == ["frontend/shared-helper.ts"]
    assert updated["metadata"].get("worker_intent", {}).get("status") != "approved"


def test_boundary_expansion_approval_allows_out_of_boundary_intent(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=1)
    group = groups[0]
    lease = control.claim_debug_group(
        campaign_key,
        group["group_key"],
        session_id="ses-worker",
        worker_id="worker-chat",
        linked_files=["frontend/test-1.test.ts"],
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker")
    control.request_debug_group_boundary(
        group["group_key"],
        lease["lease_id"],
        worker_id="worker-chat",
        requested_files=["frontend/shared-helper.ts"],
        reason="The helper is the shared root cause.",
        hypothesis="Shared helper returns the wrong selector.",
    )
    control.submit_worker_fix_intent(
        group["group_key"],
        lease["lease_id"],
        worker_id="worker-chat",
        base_commit="base111",
        hypothesis="Patch the shared helper.",
        write_files=["frontend/shared-helper.ts"],
        boundary_expansion=True,
    )

    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    approved_boundary = control.approve_debug_group_boundary(
        group["group_key"],
        lease["lease_id"],
        coordinator_session="coordinator",
    )
    approved_intent = control.approve_worker_fix_intent(
        group["group_key"],
        lease["lease_id"],
        coordinator_session="coordinator",
        current_commit="base111",
    )

    assert approved_boundary["metadata"]["boundary_request"]["status"] == "approved"
    assert approved_intent["metadata"]["worker_intent"]["status"] == "approved"


def test_boundary_expansion_approval_is_limited_to_requested_files(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=1)
    group = groups[0]
    lease = control.claim_debug_group(
        campaign_key,
        group["group_key"],
        session_id="ses-worker",
        worker_id="worker-chat",
        linked_files=["frontend/test-1.test.ts"],
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker")
    control.request_debug_group_boundary(
        group["group_key"],
        lease["lease_id"],
        worker_id="worker-chat",
        requested_files=["frontend/shared-helper-a.ts"],
        reason="Helper A is the suspected root cause.",
        hypothesis="Helper A returns the wrong selector.",
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    control.approve_debug_group_boundary(
        group["group_key"],
        lease["lease_id"],
        coordinator_session="coordinator",
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker")
    control.submit_worker_fix_intent(
        group["group_key"],
        lease["lease_id"],
        worker_id="worker-chat",
        base_commit="base111",
        hypothesis="Patch a different helper.",
        write_files=["frontend/shared-helper-b.ts"],
        boundary_expansion=True,
    )

    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    with pytest.raises(RuntimeError, match="outside the approved boundary"):
        control.approve_worker_fix_intent(
            group["group_key"],
            lease["lease_id"],
            coordinator_session="coordinator",
            current_commit="base111",
        )


def test_boundary_expansion_updates_lease_and_blocks_cross_campaign_overlap(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    first_campaign, first_groups = create_parallel_campaign(
        control,
        group_count=1,
        campaign_key="debug-campaign-first",
        group_prefix="first-group",
        triage_prefix="first-infra",
    )
    second_campaign, second_groups = create_parallel_campaign(
        control,
        group_count=2,
        campaign_key="debug-campaign-second",
        group_prefix="second-group",
        triage_prefix="second-infra",
    )
    first_lease = control.claim_debug_group(
        first_campaign,
        first_groups[0]["group_key"],
        session_id="ses-worker-1",
        worker_id="worker-one",
        linked_files=["frontend/test-1.test.ts"],
    )
    second_lease = control.claim_debug_group(
        second_campaign,
        second_groups[0]["group_key"],
        session_id="ses-worker-2",
        worker_id="worker-two",
        linked_files=["frontend/test-2.test.ts"],
    )

    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker-1")
    control.request_debug_group_boundary(
        first_groups[0]["group_key"],
        first_lease["lease_id"],
        worker_id="worker-one",
        requested_files=["frontend/shared-helper.ts"],
        reason="Shared helper is the root cause.",
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    control.approve_debug_group_boundary(
        first_groups[0]["group_key"],
        first_lease["lease_id"],
        coordinator_session="coordinator",
    )
    assert "frontend/shared-helper.ts" in control._claim_linked_files(control._lease_for_id(first_lease["lease_id"]))
    assert control.claim_debug_group(
        second_campaign,
        second_groups[1]["group_key"],
        session_id="ses-worker-3",
        worker_id="worker-three",
        linked_files=["frontend/shared-helper.ts"],
    ) is None

    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker-1")
    control.submit_worker_fix_intent(
        first_groups[0]["group_key"],
        first_lease["lease_id"],
        worker_id="worker-one",
        base_commit="base111",
        hypothesis="Patch the shared helper.",
        write_files=["frontend/shared-helper.ts"],
        boundary_expansion=True,
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    control.approve_worker_fix_intent(
        first_groups[0]["group_key"],
        first_lease["lease_id"],
        coordinator_session="coordinator",
        current_commit="base111",
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker-2")
    control.request_debug_group_boundary(
        second_groups[0]["group_key"],
        second_lease["lease_id"],
        worker_id="worker-two",
        requested_files=["frontend/shared-helper.ts"],
        reason="Try the same shared helper.",
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    control.approve_debug_group_boundary(
        second_groups[0]["group_key"],
        second_lease["lease_id"],
        coordinator_session="coordinator",
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker-2")
    control.submit_worker_fix_intent(
        second_groups[0]["group_key"],
        second_lease["lease_id"],
        worker_id="worker-two",
        base_commit="base111",
        hypothesis="Patch the same shared helper.",
        write_files=["frontend/shared-helper.ts"],
        boundary_expansion=True,
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    with pytest.raises(RuntimeError, match="overlap"):
        control.approve_worker_fix_intent(
            second_groups[0]["group_key"],
            second_lease["lease_id"],
            coordinator_session="coordinator",
            current_commit="base111",
        )


def test_worker_intent_edit_gate_blocks_until_approved_write_set(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=1)
    group = groups[0]
    lease = control.claim_debug_group(
        campaign_key,
        group["group_key"],
        session_id="ses-worker",
        worker_id="worker-chat",
        linked_files=["frontend/test-1.test.ts"],
    )

    with pytest.raises(RuntimeError, match="approved worker fix intent"):
        control.worker_edit_gate("ses-worker", ["frontend/test-1.test.ts"])

    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker")
    control.submit_worker_fix_intent(
        group["group_key"],
        lease["lease_id"],
        worker_id="ses-worker",
        base_commit="base111",
        hypothesis="Patch first test helper.",
        write_files=["frontend/test-1.test.ts"],
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    control.approve_worker_fix_intent(
        group["group_key"],
        lease["lease_id"],
        coordinator_session="coordinator",
        current_commit="base111",
    )

    assert control.worker_edit_gate("ses-worker", ["frontend/test-1.test.ts"])["ok"] is True
    with pytest.raises(RuntimeError, match="outside approved worker write set"):
        control.worker_edit_gate("ses-worker", ["frontend/other.ts"])


def test_finish_worker_records_checkpoint_without_completing_group_or_lease(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=1)
    group = groups[0]
    lease = control.claim_debug_group(
        campaign_key,
        group["group_key"],
        session_id="ses-worker",
        worker_id="worker-chat",
        linked_files=["frontend/test-1.test.ts"],
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker")
    control.submit_worker_fix_intent(
        group["group_key"],
        lease["lease_id"],
        worker_id="worker-chat",
        base_commit="base111",
        hypothesis="Patch first test helper.",
        write_files=["frontend/test-1.test.ts"],
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    control.approve_worker_fix_intent(
        group["group_key"],
        lease["lease_id"],
        coordinator_session="coordinator",
        current_commit="base111",
    )

    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker")
    finished = control.finish_debug_worker(
        group["group_key"],
        lease["lease_id"],
        worker_id="worker-chat",
        base_commit="base111",
        changed_files=["frontend/test-1.test.ts"],
        summary="Updated the stale helper.",
        verification_command="python3 scripts/tests.py run --campaign debug-campaign-parallel --group group-1",
        current_commit="base111",
    )

    finish = finished["metadata"]["worker_finish"]
    assert finish["status"] == "ready_for_harvest"
    assert finish["changed_files"] == ["frontend/test-1.test.ts"]
    harvest = finish["harvest"]
    assert harvest["kind"] == "sessions_worktree_checkpoint"
    assert harvest["worker_session_id"] == "ses-worker"
    assert harvest["checkpoint_command"] == "python3 scripts/sessions.py worktree checkpoint --opencode-session ses-worker --event idle"
    assert harvest["inspect_command"] == "python3 scripts/sessions.py chat read ses-worker"
    assert harvest["patch_diff_command_template"] == "git diff --binary base111 '<checkpoint-commit>' -- frontend/test-1.test.ts"
    assert finished["status"] == "worker_finished"
    assert control._lease_for_id(lease["lease_id"])["status"] == "active"
    status = control.debug_campaign_status(campaign_key)
    assert status["campaign"]["status"] == "active"
    assert status["workers"][0]["harvest_command"] == harvest["checkpoint_command"]


def test_finish_worker_rejects_omitted_known_session_modified_files(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=1)
    group = groups[0]
    lease = control.claim_debug_group(
        campaign_key,
        group["group_key"],
        session_id="ses-worker",
        worker_id="worker-chat",
        linked_files=["frontend/test-1.test.ts", "frontend/test-1-helper.ts"],
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker")
    control.submit_worker_fix_intent(
        group["group_key"],
        lease["lease_id"],
        worker_id="worker-chat",
        base_commit="base111",
        hypothesis="Patch first test helper.",
        write_files=["frontend/test-1.test.ts", "frontend/test-1-helper.ts"],
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    control.approve_worker_fix_intent(
        group["group_key"],
        lease["lease_id"],
        coordinator_session="coordinator",
        current_commit="base111",
    )
    monkeypatch.setattr(control, "_known_worker_modified_files", lambda _session_id: ["frontend/test-1.test.ts", "frontend/test-1-helper.ts"])

    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker")
    with pytest.raises(RuntimeError, match="omit session modified files"):
        control.finish_debug_worker(
            group["group_key"],
            lease["lease_id"],
            worker_id="worker-chat",
            base_commit="base111",
            changed_files=["frontend/test-1.test.ts"],
            summary="Updated only one declared file.",
            current_commit="base111",
        )


def test_finish_worker_persists_canonical_worker_identity_and_intent_base(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=1)
    group = groups[0]
    lease = control.claim_debug_group(
        campaign_key,
        group["group_key"],
        session_id="ses-worker",
        worker_id="worker-chat",
        linked_files=["frontend/test-1.test.ts"],
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker")
    control.submit_worker_fix_intent(
        group["group_key"],
        lease["lease_id"],
        worker_id="worker-chat",
        base_commit="base111222",
        hypothesis="Patch first test helper.",
        write_files=["frontend/test-1.test.ts"],
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    control.approve_worker_fix_intent(
        group["group_key"],
        lease["lease_id"],
        coordinator_session="coordinator",
        current_commit="base111",
    )

    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker")
    finished = control.finish_debug_worker(
        group["group_key"],
        lease["lease_id"],
        worker_id="ses-worker",
        base_commit="base111",
        changed_files=["frontend/test-1.test.ts"],
        summary="Updated the stale helper.",
        current_commit="base111",
    )

    finish = finished["metadata"]["worker_finish"]
    assert finish["worker_id"] == "worker-chat"
    assert finish["base_commit"] == "base111222"
    assert finish["harvest"]["worker_chat"] == "worker-chat"
    assert finish["harvest"]["base_commit"] == "base111222"


def test_finish_worker_fails_closed_when_checkout_commit_unavailable(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, groups = create_parallel_campaign(control, group_count=1)
    group = groups[0]
    lease = control.claim_debug_group(
        campaign_key,
        group["group_key"],
        session_id="ses-worker",
        worker_id="worker-chat",
        linked_files=["frontend/test-1.test.ts"],
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker")
    control.submit_worker_fix_intent(
        group["group_key"],
        lease["lease_id"],
        worker_id="worker-chat",
        base_commit="base111",
        hypothesis="Patch first test helper.",
        write_files=["frontend/test-1.test.ts"],
    )
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")
    control.approve_worker_fix_intent(
        group["group_key"],
        lease["lease_id"],
        coordinator_session="coordinator",
        current_commit="base111",
    )
    monkeypatch.setattr(control, "current_git_sha", lambda: (_ for _ in ()).throw(RuntimeError("git unavailable")))

    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses-worker")
    with pytest.raises(RuntimeError, match="git unavailable"):
        control.finish_debug_worker(
            group["group_key"],
            lease["lease_id"],
            worker_id="worker-chat",
            base_commit="base111",
            changed_files=["frontend/test-1.test.ts"],
            summary="Updated the stale helper.",
            current_commit="base111",
        )


def test_dispatch_dry_run_explains_without_leasing_or_spawning(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    campaign_key, _groups = create_parallel_campaign(control, group_count=2)
    launches = []
    monkeypatch.setattr(control.subprocess, "run", lambda command, **_kwargs: launches.append(command))
    monkeypatch.setattr(control, "build_triage", lambda: {"groups": []})
    monkeypatch.setenv("OPENCODE_SESSION_ID", "unrelated-chat")

    with pytest.raises(RuntimeError, match="mismatch"):
        control.dispatch_parallel_debug_chats(campaign_key, "coordinator", max_workers=1, dry_run=True)
    monkeypatch.setenv("OPENCODE_SESSION_ID", "coordinator")

    result = control.dispatch_parallel_debug_chats(campaign_key, "coordinator", max_workers=1, dry_run=True)

    assert launches == []
    assert len(result["selected"]) == 1
    assert result["spawned"] == []
    assert result["dry_run"] is True
    assert control.debug_campaign_status(campaign_key)["workers"] == []


def test_campaign_run_options_are_control_plane_only(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)

    options = control.parse_control_run_options([
        "--campaign", "campaign-1", "--group", "group-1", "--gate-deploy",
    ])

    assert options.campaign_key == "campaign-1"
    assert options.debug_group_key == "group-1"
    assert options.forwarded_args == []
    assert options.gate_deploy is True


def test_scoped_verification_ignores_historical_unrelated_failures(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    state = {
        "tests": {
            "playwright::historical-reminder.spec.ts": {"status": "failed"},
            "pytest_unit::feature-test": {"status": "passed"},
        }
    }

    result = control.evaluate_scoped_verification(
        state,
        required_test_keys=["pytest_unit::feature-test"],
        attributable_failure_keys=[],
    )

    assert result["status"] == "passed"
    assert result["blocking_test_keys"] == []
    assert result["visible_unrelated_failure_keys"] == ["playwright::historical-reminder.spec.ts"]


def test_scoped_verification_blocks_new_attributable_failure(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    state = {
        "tests": {
            "pytest_unit::feature-test": {"status": "passed"},
            "playwright::feature-regression.spec.ts": {"status": "failed"},
        }
    }

    result = control.evaluate_scoped_verification(
        state,
        required_test_keys=["pytest_unit::feature-test"],
        attributable_failure_keys=["playwright::feature-regression.spec.ts"],
    )

    assert result["status"] == "blocked"
    assert result["blocking_test_keys"] == ["playwright::feature-regression.spec.ts"]


def test_group_completion_rejects_unrelated_passing_run(tmp_path, monkeypatch):
    control = load_tests_control(tmp_path, monkeypatch)
    control.record_run_result(failed_run("first.spec.ts"))
    monkeypatch.setenv("OPENCODE_SESSION_ID", "session-1")
    campaign = control.start_debug_campaign(session_id="session-1")
    group = control.debug_groups_for_campaign(campaign["campaign_key"])[0]
    unrelated = passed_run(
        ["first.spec.ts"], "run-unrelated", "other111", "another-campaign", "another-group"
    )
    control.record_run_result(unrelated)

    monkeypatch.setenv("OPENCODE_SESSION_ID", "session-1")
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
