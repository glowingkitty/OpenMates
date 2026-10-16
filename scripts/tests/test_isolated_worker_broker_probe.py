# contract-test-file: tooling
"""Provider-free CI backend diagnostic admission and result contracts."""

import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import ci_candidate, ci_coordinator as coordinator
from scripts import isolated_worker_broker_probe as probe
from scripts.ci_coordinator import Queue
from scripts.ci_results import valid_backend_probe_receipt


SOURCE = "a" * 40


def profile() -> dict:
    worker = {"environment": {"OPENMATES_CI_AI_FIXTURES": "1",
                              "CELERY_QUEUES": "app_ai,app_ai_routing"},
              "command": ["python", "-m", "celery", "--queues=app_ai,app_ai_routing"]}
    services = {name: {"environment": {}} for name in
                ("api", "core-worker", "runner-gateway", "cms", "cms-database", "cache", "vault")}
    services["ai-worker"] = worker
    services["cms-database"]["image"] = "openmates-ci-database:local"
    return {"networks": {"default": {"internal": True}}, "services": services}


def runtime() -> dict:
    return {"images": [{"kind": kind, "reused": True} for kind in sorted(probe.REQUIRED_IMAGES)]}


def setup_preflight(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("CI_SPECS_JSON", json.dumps([probe.SELECTOR]))
    schema = tmp_path / "backend/core/directus/schemas/chat_routing_proofs.yml"
    schema.parent.mkdir(parents=True)
    schema.write_text("collection: chat_routing_proofs\n")
    return profile(), runtime(), {"source_commit": SOURCE, "run_id": "123"}


def test_cache_preflight_requires_all_published_images_and_final_routing_command(tmp_path, monkeypatch):
    selected, images, environment = setup_preflight(tmp_path, monkeypatch)
    probe.validate_cache_evidence(tmp_path, SOURCE, selected, images, environment)
    images["images"][0]["reused"] = False
    with pytest.raises(ValueError, match="compatible_image_cache_miss"):
        probe.validate_cache_evidence(tmp_path, SOURCE, selected, images, environment)
    images = runtime()
    selected["services"]["cms-database"]["image"] = "postgres:15"
    with pytest.raises(ValueError, match="prepared_schema_not_selected"):
        probe.validate_cache_evidence(tmp_path, SOURCE, selected, images, environment)
    selected["services"]["cms-database"]["image"] = "openmates-ci-database:local"
    selected["services"]["ai-worker"]["command"][-1] = "--queues=app_ai"
    with pytest.raises(ValueError, match="routing_worker_profile"):
        probe.validate_cache_evidence(tmp_path, SOURCE, selected, images, environment)
    selected["services"]["ai-worker"]["command"][-1] = "--queues=app_ai,app_ai_routing"
    selected["services"]["ai-worker"]["environment"]["SECRET__GOOGLE_API_KEY"] = "test"
    with pytest.raises(ValueError, match="provider_credentials_present"):
        probe.validate_cache_evidence(tmp_path, SOURCE, selected, images, environment)


def test_backend_probe_is_dedicated_diagnostic_selector(tmp_path):
    queue = Queue(tmp_path / "queue.sqlite3")
    job = queue.enqueue("owner", SOURCE, [probe.SELECTOR], "backend-probe")
    assert job["mode"] == "backend-probe"
    for specs in ([], ["other.spec.ts"], [probe.SELECTOR, "other.spec.ts"]):
        with pytest.raises(ValueError, match="exact recovery fixture selector"):
            queue.enqueue("owner", SOURCE, specs, "backend-probe")


def test_cli_probe_default_bypasses_prepared_build_batching(tmp_path, monkeypatch):
    passed = {}
    monkeypatch.setattr(coordinator, "canonical_root", lambda _path: tmp_path)
    monkeypatch.setattr(coordinator, "Queue", lambda _path: object())
    monkeypatch.setattr(coordinator, "partition_source_specs",
                        lambda specs, _source, _root: (specs, []))
    monkeypatch.setattr(ci_candidate, "load", lambda *_args, **_kwargs: {})

    def capture(_queue, _session, _source, _specs, _mode, *_args, **kwargs):
        passed["prepared_builds"] = kwargs["prepared_builds"]
        return [{"id": "diagnostic"}]

    monkeypatch.setattr(coordinator, "enqueue_submission", capture)
    monkeypatch.setattr(coordinator, "print_receipt", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sys, "argv", ["ci_coordinator.py", "submit", "--session", "s",
                                      "--source", SOURCE, "--mode", "backend-probe",
                                      "--spec", probe.SELECTOR])
    coordinator.main()
    assert passed == {"prepared_builds": False}


def probe_result() -> dict:
    return {"registeredRoutingConsumers": 1, "routingConsumers": 1,
            "combinedConsumers": 1, "livePoolConsumers": 1,
            "registrationReplies": 1, "queueReplies": 1, "statsReplies": 1,
            "routeBinding": True, "queueDepths": {"appAi": 0, "appAiRouting": 2},
            "redis": True, "cmsTables": True}


def test_probe_captures_bounded_timeout_and_full_private_output(tmp_path):
    def timeout_runner(_command, *, stdout, stderr, timeout, **_kwargs):
        assert timeout == 35
        stdout.write(b"OPENMATES_PROBE_STAGE:bootstrap\n")
        stderr.write(b"private import failure details")
        raise subprocess.TimeoutExpired("docker", timeout)

    result, stage, category = probe.run_probe(tmp_path, runner=timeout_runner)
    assert result is None and stage == "bootstrap" and category == "timeout"
    private = tmp_path / "test-results/ci-backend-probe-private"
    assert (private / "probe.stderr.log").read_bytes() == b"private import failure details"
    assert (private / "probe.stdout.log").stat().st_mode & 0o777 == 0o600
    assert private.stat().st_mode & 0o777 == 0o700


def test_probe_accepts_only_content_free_healthy_marker(tmp_path):
    def healthy_runner(_command, *, stdout, stderr, **_kwargs):
        stdout.write(b"OPENMATES_PROBE_STAGE:cms_checked\n")
        stdout.write(b"OPENMATES_PROBE_JSON:" + json.dumps(probe_result()).encode() + b"\n")
        return SimpleNamespace(returncode=0)

    result, stage, category = probe.run_probe(tmp_path, runner=healthy_runner)
    assert result == probe_result() and stage == "cms_checked" and category == "ok"
    invalid = {**probe_result(), "registeredRoutingConsumers": 0}
    assert probe.parse_probe_output(
        b"OPENMATES_PROBE_JSON:" + json.dumps(invalid).encode() + b"\n"
    )[0] is None


def test_native_receipt_cannot_claim_recovery_or_latency_acceptance():
    job = {"source": SOURCE, "run_id": 123}
    report = {"runtime_profile": "backend-probe", "diagnostic_only": True,
              "recovery_e2e_verified": False, "latency_acceptance_verified": False,
              "results": [{"spec": "backend-worker-broker-probe", "exit_code": 0,
                           "status": "passed"}]}
    services = {name: {"running": True} for name in
                ("api", "ai-worker", "core-worker", "runner-gateway", "cms",
                 "cms-database", "cache", "vault")}
    environment = {"source_commit": SOURCE, "run_id": "123", "harness_commit": "h" * 40,
                   "runner_environment": "github-hosted", "shared_dev_dns": "rejected",
                   "shared_dev_https": "rejected", "provider_egress": "rejected-internal-network",
                   "services": services}
    assert valid_backend_probe_receipt(report, environment, job, expected_harness_commit="h" * 40)
    assert not valid_backend_probe_receipt({**report, "recovery_e2e_verified": True}, environment, job,
                                           expected_harness_commit="h" * 40)
    assert not valid_backend_probe_receipt(report, {**environment, "provider_egress": "unknown"}, job,
                                           expected_harness_commit="h" * 40)


def test_preflight_checks_resolved_worker_after_prepared_schema_selection(tmp_path, monkeypatch):
    selected, images, environment = setup_preflight(tmp_path, monkeypatch)
    private = tmp_path / "test-results/ci-private"
    private.mkdir(parents=True)
    compose = private / "compose.json"
    compose.write_text(json.dumps(selected))
    (tmp_path / "test-results/ci-runtime-images.json").write_text(json.dumps(images))
    (tmp_path / "test-results/ci-environment.json").write_text(json.dumps(environment))
    monkeypatch.setenv("CI_TEST_MODE", "backend-probe")
    monkeypatch.setenv("BUILD_COMMIT_SHA", SOURCE)
    monkeypatch.setenv("CI_HARNESS_COMMIT", "h" * 40)
    monkeypatch.setattr(probe, "SOURCE", str(tmp_path))
    monkeypatch.setattr(probe, "COMPOSE_PATH", compose)
    monkeypatch.setattr(probe, "require_runner", lambda: None)

    def select_schema():
        resolved = json.loads(compose.read_text())
        resolved["services"]["cms-database"]["image"] = "openmates-ci-database:local"
        resolved["services"]["ai-worker"]["command"][-1] = "--queues=app_ai"
        compose.write_text(json.dumps(resolved))
        return True

    monkeypatch.setattr(probe, "select_runtime_profile", select_schema)
    assert probe.main(["preflight"]) == 1
    report = json.loads((tmp_path / "test-results/ci-results.json").read_text())
    assert report["diagnostic_only"] is True
    assert report["success"] is False
    assert report["results"][0]["category"] == "routing_worker_profile"
