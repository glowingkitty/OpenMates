# contract-test-file: tooling
"""Prevent partial or cloud-incompatible CI evidence from activating cutover.

Known core specs may run after a real isolated account preflight passes.
Cloud, provider and unknown requirements remain explicit incomplete coverage.
Workflow cleanup failure must not be promoted to an overall passing pilot.
See docs/architecture/isolated-github-tests.md.
"""

import pytest
from scripts.ci_coverage import partition, verify_pilot


def receipt():
    return {
        "state": "success", "run_id": 7, "source_commit": "a" * 40,
        "harness_commit": "b" * 40, "artifact_url": "synthetic",
        "report": {"success": True, "results": [{
            "spec": "test-account-preflight.spec.ts", "exit_code": 0,
            "stats": {"expected": 1, "skipped": 0},
        }]},
        "environment": {"runner_environment": "github-hosted", "shared_dev_https": "rejected",
                        "frontend": {"source_commit": "a" * 40},
                        "services": {name: {} for name in ("api", "core-worker", "cms", "cms-database", "cache", "vault")}},
    }


def test_cloud_and_unknown_coverage_never_fall_back_to_self_host():
    allowed, held = partition(["tasks-flow.spec.ts", "anonymous-production-repair.spec.ts", "new.spec.ts"])
    assert allowed == ["tasks-flow.spec.ts"]
    assert "official-cloud" in held["anonymous-production-repair.spec.ts"]
    assert "new.spec.ts" in held


def test_search_relevance_schema_parity_uses_core_without_provider_access():
    allowed, held = partition(["skill-search-relevance-parity.spec.ts"])
    assert allowed == ["skill-search-relevance-parity.spec.ts"]
    assert held == {}


def test_account_retirement_reader_probe_gets_isolated_api_markers():
    import json
    from pathlib import Path

    allowed, held = partition(["account-retirement-reads.spec.ts"])
    assert allowed == ["account-retirement-reads.spec.ts"]
    assert held == {}
    manifest = json.loads((Path(__file__).resolve().parents[1] / "ci_coverage_manifest.json").read_text())
    # This profile makes the API internal-network-only and supplies all three
    # CI isolation/capture markers required before the probe can write fixtures.
    assert "account-retirement-reads.spec.ts" in manifest["groups"]["local_email_signup"]["specs"]


def test_embed_preview_replay_uses_real_core_state_without_provider_access():
    allowed, held = partition(["embed-preview-backfill-replay.spec.ts"])
    assert allowed == ["embed-preview-backfill-replay.spec.ts"]
    assert held == {}


def test_cleanup_failure_and_skipped_preflight_cannot_activate():
    data = receipt()
    data["state"] = "failure"
    with pytest.raises(RuntimeError, match="successful GitHub job"):
        verify_pilot(data)
    data["state"] = "success"
    data["report"]["results"][0]["stats"]["skipped"] = 1
    with pytest.raises(RuntimeError, match="without skipped"):
        verify_pilot(data)


def test_verified_core_profile_does_not_claim_all_e2e_complete():
    verified = verify_pilot(receipt())
    assert verified["ready"] is True
    assert verified["all_e2e_migrated"] is False
    assert "anonymous-production-repair.spec.ts" in verified["held_coverage"]


def test_synthetic_artifacts_use_distinct_account_free_runtime():
    from scripts.ci_coverage import execution_mode
    allowed, held = partition(["security-reporting-email-proof.spec.ts"])
    assert not held
    assert execution_mode(allowed[0]) == "artifact"
    assert execution_mode("tasks-flow.spec.ts") == "e2e"


def test_component_marker_selects_lightweight_github_runtime():
    from scripts.ci_coverage import COMPONENT_MARKER, execution_mode

    assert execution_mode("components/example.spec.ts", COMPONENT_MARKER) == "component"
    assert execution_mode("components/example.spec.ts", "// no marker") == "e2e"
    allowed, held = partition(["components/read-only-message-parsed-doc.spec.ts"])
    assert allowed == ["components/read-only-message-parsed-doc.spec.ts"]
    assert held == {}
    assert execution_mode(allowed[0], COMPONENT_MARKER) == "component"


def test_all_existing_holds_have_concrete_dependency_and_next_action():
    import json
    from pathlib import Path
    from scripts.ci_coverage import partition

    manifest = json.loads((Path(__file__).resolve().parents[1] / "ci_coverage_manifest.json").read_text())
    specs = [spec for group in manifest["groups"].values() for spec in group["specs"]]
    _, held = partition(specs)
    assert set(manifest["holds"]) == set(held)
    for spec in held:
        entry = manifest["holds"][spec]
        assert entry["dependency"]
        assert len(entry["next_action"]) > 50
        assert type(entry["user_input_required"]) is bool
        assert "requirements have not been ported" not in entry["next_action"].lower()


def test_live_weather_batches_cannot_relax_replay_network_isolation():
    import pytest
    from scripts.ci_coverage import runtime_batches, validate_runtime_batch

    specs = ["chat-settings-flow.spec.ts", "cli-workflows-schedule-real.spec.ts", "test-account-preflight.spec.ts"]
    assert runtime_batches(specs, 4) == [["chat-settings-flow.spec.ts", "test-account-preflight.spec.ts"], ["cli-workflows-schedule-real.spec.ts"]]
    with pytest.raises(ValueError, match="separate batch"):
        validate_runtime_batch(specs)
    validate_runtime_batch(["cli-workflows-rain-real.spec.ts", "workflows-ready-run-tasks.spec.ts"])


def test_rust_session_targets_have_exact_dependency_classification():
    import json
    from pathlib import Path

    manifest = json.loads((Path(__file__).resolve().parents[1] / "ci_coverage_manifest.json").read_text())
    component = "components/rust-core-session-harness.spec.ts"
    browser = "rust-core-browser-session.spec.ts"
    allowed, held = partition([component, browser], manifest)
    assert allowed == [component, browser]
    assert held == {}
    expected = {
        "rust_core_session_harness": [component],
        "rust_core_browser_session": [browser],
    }
    for name, specs in expected.items():
        assert manifest["groups"][name]["execution"] == "e2e"
        assert manifest["groups"][name]["specs"] == specs
        assert manifest["groups"][name]["enabling_work"]
    # Admission is exact, never a basename or prefix dependency exemption.
    unknown = [
        "rust-core-session-harness.spec.ts",
        "components/rust-core-session-harness-extra.spec.ts",
        "nested/components/rust-core-session-harness.spec.ts",
        "rust-core-browser-session-extra.spec.ts",
        "nested/rust-core-browser-session.spec.ts",
    ]
    allowed, held = partition(unknown, manifest)
    assert allowed == []
    assert set(held) == set(unknown)


def test_rust_session_component_stays_account_free_and_browser_stays_e2e():
    import json
    from pathlib import Path
    from scripts.ci_coverage import COMPONENT_MARKER, execution_mode

    manifest = json.loads((Path(__file__).resolve().parents[1] / "ci_coverage_manifest.json").read_text())
    component = "components/rust-core-session-harness.spec.ts"
    browser = "rust-core-browser-session.spec.ts"
    assert execution_mode(component, COMPONENT_MARKER) == "component"
    assert execution_mode(browser) == "e2e"
    component_dependency = manifest["groups"]["rust_core_session_harness"]["enabling_work"]
    assert "Vite-only" in component_dependency
    assert "No Rust or CLI build" in component_dependency
    assert "account, backend services" in component_dependency
    browser_dependency = manifest["groups"]["rust_core_browser_session"]["enabling_work"]
    assert "runner-private accounts" in browser_dependency
    assert "same job before Playwright" in browser_dependency
    # Browser foreground send now requires explicit committed replay; component
    # presentation and unrelated Workflow profiles remain independent.
    assert browser in manifest["groups"]["ai_committed_fixtures"]["specs"]
    assert component not in manifest["groups"]["ai_committed_fixtures"]["specs"]
    for name in ("workflow_core", "workflow_weather"):
        assert not {component, browser}.intersection(manifest["groups"].get(name, {}).get("specs", []))


def test_native_bounded_read_has_exact_no_inference_classification():
    import json
    from pathlib import Path
    from scripts.ci_coverage import execution_mode
    manifest = json.loads((Path(__file__).resolve().parents[1] / "ci_coverage_manifest.json").read_text())
    name = "cli-native-bounded-saved-read.spec.ts"
    assert partition([name], manifest) == ([name], {})
    assert execution_mode(name) == "e2e"
    assert manifest["groups"]["native_bounded_saved_read"]["specs"] == [name]
    for unknown in ("cli-native-bounded-saved-read-extra.spec.ts", "nested/" + name):
        allowed, held = partition([unknown], manifest)
        assert allowed == [] and unknown in held
