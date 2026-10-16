# contract-test-file: tooling
"""Verify bounded CI evidence retrieval without remote services.

Malicious or accidental archive paths must not escape the evidence directory.
Downloads must terminate even when a child stalls or floods its stderr pipe.
These tests use disposable files and processes, never shared runtime state.
See docs/plans/isolated-github-tests/plan.yml.
"""

import io
import stat
import sys
import zipfile

import pytest
from scripts import ci_results


@pytest.mark.parametrize("fault", ["", "source", "frontend", "egress", "extra_actor", "missing_mount", "stopped"])
def test_api_only_accountability_result_requires_exact_backend_runtime(fault):
    import json

    source = "a" * 40
    services = {name: {"running": True} for name in
                ("api", "core-worker", "cms", "cms-database", "cache", "vault")}
    for name in ("api", "core-worker"):
        services[name]["backend_source"] = "/home/runner/work/OpenMates/OpenMates/subject/backend"
    environment = {"source_commit": source, "shared_dev_dns": "rejected",
                   "shared_dev_https": "rejected", "services": services}
    if fault == "source":
        environment["source_commit"] = "b" * 40
    elif fault == "frontend":
        environment["frontend"] = {"source_commit": source}
    elif fault == "egress":
        environment["shared_dev_dns"] = "unverified"
    elif fault == "extra_actor":
        services["ai-worker"] = {"running": True}
    elif fault == "missing_mount":
        services["api"]["backend_source"] = "/other/backend"
    elif fault == "stopped":
        services["api"]["running"] = False
    job = {"source": source, "mode": "e2e",
           "specs": json.dumps(["storage-accountability-integration.spec.ts"])}
    assert ci_results.green_e2e_source_and_egress_verified(environment, job) is (fault == "")
    job["specs"] = json.dumps(["storage-message-embed-bundle.spec.ts"])
    assert ci_results.green_e2e_source_and_egress_verified(environment, job) is (fault == "frontend")


def test_browser_component_result_keeps_existing_frontend_identity_requirement():
    import json

    source = "a" * 40
    job = {"source": source, "mode": "component", "specs": json.dumps(["component.spec.ts"])}
    environment = {"source_commit": source, "shared_dev_https": "rejected",
                   "frontend": {"source_commit": source}}
    assert ci_results.green_e2e_source_and_egress_verified(environment, job) is True
    environment["frontend"] = {"source_commit": "b" * 40}
    assert ci_results.green_e2e_source_and_egress_verified(environment, job) is False


def test_timings_separate_preparation_admission_and_actual_github_work():
    from scripts.ci_results import timings
    result = timings(
        {"created": 0, "ready_at": 20, "sent": 30},
        [{"id": 1, "started_at": "1970-01-01T00:00:40Z", "completed_at": "1970-01-01T00:02:00Z", "steps": [{"name": "Run selected checks", "started_at": "1970-01-01T00:01:00Z", "completed_at": "1970-01-01T00:01:20Z", "conclusion": "success"}]}],
    )
    assert result["preparation_wait_seconds"] == 20
    assert result["coordinator_admission_seconds"] == 10
    assert result["dispatch_to_job_start_seconds"] == 10
    assert result["github_job_wall_seconds"] == 80
    assert result["request_to_github_completion_seconds"] == 120
    assert result["steps"][0]["seconds"] == 20
    assert timings({}, [{"id": 1}]) == {"steps": []}

@pytest.mark.parametrize(
    "name",
    ["../escape", "/absolute", "ci-private/account.env", ".auth/session.json", ".env"],
)
def test_private_or_escaping_archive_rejected(tmp_path, name):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(name, "private")
    with pytest.raises(RuntimeError):
        ci_results.extract(archive, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_symlink_archive_rejected(tmp_path):
    archive = tmp_path / "bad.zip"
    entry = zipfile.ZipInfo("link")
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(entry, "/tmp/outside")
    with pytest.raises(RuntimeError, match="Unsafe"):
        ci_results.extract(archive, tmp_path / "out")


def test_download_drains_stderr_and_bounds_stdout(tmp_path, monkeypatch):
    output = io.BytesIO()
    ci_results.download(
        [
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('x'*200000); sys.stdout.write('ok')",
        ],
        tmp_path,
        output,
    )
    assert output.getvalue() == b"ok"
    monkeypatch.setattr(ci_results, "MAX_ARCHIVE", 10)
    with pytest.raises(RuntimeError, match="exceeded"):
        ci_results.download(
            [sys.executable, "-c", "print('x'*100)"], tmp_path, io.BytesIO()
        )


def test_download_stall_has_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(ci_results, "DOWNLOAD_SECONDS", 0.1)
    with pytest.raises(RuntimeError, match="timed out"):
        ci_results.download(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            tmp_path,
            io.BytesIO(),
        )


@pytest.mark.parametrize("fault", ["", "source", "harness", "empty", "runner", "profile", "egress", "inventory"])
@pytest.mark.parametrize("pinned_harness", [False, True])
def test_result_binds_subject_harness_runner_and_execution(
    tmp_path, monkeypatch, fault, pinned_harness
):
    import json

    source = "a" * 40
    harness = "b" * 40
    report = {
        "source_commit": "c" * 40 if fault == "source" else source,
        "run_id": "7",
        "success": True,
        "results": [] if fault == "empty" else [{"exit_code": 0, "spec": "wrong.spec.ts" if fault == "inventory" else "security-reporting-email-proof.spec.ts"}],
        "runtime_profile": "e2e" if fault == "profile" else "artifact",
        "artifact_shared_dev_rejected": fault != "egress",
        "harness_commit": "c" * 40 if fault == "harness" else harness,
    }
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("ci-results.json", json.dumps(report))
    monkeypatch.setattr(
        ci_results,
        "download",
        lambda command, root, output: output.write(archive.getvalue()),
    )
    monkeypatch.setattr(ci_results, "RESERVE", 0)
    monkeypatch.setattr(ci_results.shutil, "disk_usage",
                        lambda _path: type("Usage", (), {"total": 100 * 1024**3,
                                                         "used": 10 * 1024**3,
                                                         "free": 90 * 1024**3})())

    class Remote:
        repo = "example/repo"

        def request(self, endpoint):
            if "/artifacts?" in endpoint:
                return {
                    "artifacts": [
                        {
                            "name": "isolated-test-results",
                            "expired": False,
                            "id": 8,
                            "size_in_bytes": len(archive.getvalue()),
                        }
                    ]
                }
            if "/jobs?" in endpoint:
                return {
                    "jobs": [
                        {
                            "id": 9,
                            "labels": ["self-hosted"]
                            if fault == "runner"
                            else ["ubuntu-latest"],
                            "runner_name": "GitHub Actions 9",
                        }
                    ]
                }
            return {"head_sha": "d" * 40 if pinned_harness else harness}

    job = {
        "id": "request",
        "mode": "artifact",
        "specs": json.dumps(["security-reporting-email-proof.spec.ts"]),
        "source": source,
        "run_id": 7,
        "state": "success",
        "url": "https://example.test/7",
    }
    if pinned_harness:
        job["preparation_harness_commit"] = harness
    if fault:
        with pytest.raises(RuntimeError):
            ci_results.fetch(Remote(), job, tmp_path)
        assert not (tmp_path / "test-results/ci-runs/request/receipt.json").exists()
    else:
        result = ci_results.fetch(Remote(), job, tmp_path)
        assert result["source_commit"] == source
        assert result["harness_commit"] == harness
        assert result["artifact_url"].endswith("/artifacts/8")


@pytest.mark.parametrize("mode", ["e2e", "selfhost"])
@pytest.mark.parametrize("fault", ["", "missing", "run", "harness", "containers", "volumes", "accounts", "reported_error"])
def test_green_e2e_requires_run_bound_cleanup(tmp_path, fault, mode):
    import json
    data = {"run_id": "7", "harness_commit": "harness", "containers_remaining": 0,
            "volumes_remaining": 0, "private_account_files_removed": True}
    if fault == "run":
        data["run_id"] = "8"
    if fault == "harness":
        data["harness_commit"] = "other"
    if fault == "containers":
        data["containers_remaining"] = 1
    if fault == "volumes":
        data["volumes_remaining"] = 1
    if fault == "reported_error":
        data["errors"] = ["installer path cleanup failed"]
    if fault == "accounts":
        data["private_account_files_removed"] = False
    if fault != "missing":
        (tmp_path / "ci-cleanup.json").write_text(json.dumps(data))
    job = {"mode": mode, "state": "success", "run_id": 7}
    result = {"harness_commit": "harness", "report": {"results": ["original assertion"]}}
    if fault:
        with pytest.raises(RuntimeError, match="cleanup"):
            ci_results.attach_cleanup(result, job, tmp_path)
        job["state"] = "failure"
        retained = ci_results.attach_cleanup(result, job, tmp_path)
        assert retained["cleanup_verified"] is False
        assert retained["report"]["results"] == ["original assertion"]
    else:
        assert ci_results.attach_cleanup(result, job, tmp_path)["cleanup_verified"] is True


def _team_node_environment():
    source, harness = "a" * 40, "b" * 40
    services = {name: {"running": True} for name in (
        "api", "core-worker", "cms", "cms-database", "cache", "vault",
        "ai-worker", "runner-gateway", "object-storage",
    )}
    for name in ("api", "core-worker", "ai-worker"):
        services[name]["backend_source"] = "/home/runner/work/OpenMates/OpenMates/subject/backend"
    return {
        "source_commit": source, "harness_commit": harness, "run_id": "7",
        "shared_dev_dns": "rejected", "shared_dev_https": "rejected", "runner_environment": "github-hosted",
        "services": services, "provider_egress": "rejected-internal-network",
        "storage_capacity": {"provider_credentials": "absent", "provider_network": "internal",
                             "fixture_mode": "replay-only", "worker_slots": 2, "worker_replicas": 1},
        "storage_isolation_proof": {"source_bound": True, "read_only_bind": True,
                                    "vault_provider_namespace": "disposable_only"},
        "object_storage": {"endpoint": "http://storage.ci.test:9000", "provider": "SeaweedFS",
                           "protocol_probe": "authenticated-roundtrip-cors-presigned-and-private-access-passed"},
    }


@pytest.mark.parametrize("selector", ["storage-team-portability.spec.ts", "storage-archive-lifecycle.spec.ts"])
@pytest.mark.parametrize("fault", [
    "", "source", "harness", "run", "frontend", "dns", "https", "runner", "missing_actor", "extra_actor",
    "stopped", "malformed_service", "missing_mount", "different_mount", "relative_mount", "provider_egress",
    "provider_credentials", "provider_network", "fixture_mode", "slots_zero", "slots_excess", "slots_bool",
    "replicas", "isolation_source", "isolation_readonly", "isolation_namespace", "storage_endpoint",
    "storage_provider", "storage_protocol", "missing_proof",
])
def test_team_node_result_requires_strict_disposable_storage_runtime(fault, selector):
    import json

    environment = _team_node_environment()
    job = {"source": "a" * 40, "mode": "e2e", "run_id": 7,
           "specs": json.dumps([selector])}
    if fault in {"source", "harness"}:
        environment[f"{fault}_commit"] = "c" * 40
    elif fault == "run":
        environment["run_id"] = "8"
    elif fault == "frontend":
        environment["frontend"] = {"source_commit": job["source"]}
    elif fault in {"dns", "https"}:
        environment[f"shared_dev_{fault}"] = "unverified"
    elif fault == "runner":
        environment["runner_environment"] = "self-hosted"
    elif fault == "missing_actor":
        del environment["services"]["object-storage"]
    elif fault == "extra_actor":
        environment["services"]["uploads"] = {"running": True}
    elif fault == "stopped":
        environment["services"]["runner-gateway"]["running"] = False
    elif fault == "malformed_service":
        environment["services"]["api"] = []
    elif fault == "missing_mount":
        del environment["services"]["core-worker"]["backend_source"]
    elif fault == "different_mount":
        environment["services"]["ai-worker"]["backend_source"] = "/other/subject/backend"
    elif fault == "relative_mount":
        for actor in ("api", "core-worker", "ai-worker"):
            environment["services"][actor]["backend_source"] = "subject/backend"
    elif fault == "provider_egress":
        environment["provider_egress"] = "unverified"
    elif fault in {"provider_credentials", "provider_network", "fixture_mode"}:
        environment["storage_capacity"][fault] = "unverified"
    elif fault.startswith("slots_"):
        environment["storage_capacity"]["worker_slots"] = {"slots_zero": 0, "slots_excess": 5, "slots_bool": True}[fault]
    elif fault == "replicas":
        environment["storage_capacity"]["worker_replicas"] = 2
    elif fault.startswith("isolation_"):
        field = {"isolation_source": "source_bound", "isolation_readonly": "read_only_bind",
                 "isolation_namespace": "vault_provider_namespace"}[fault]
        environment["storage_isolation_proof"][field] = False
    elif fault.startswith("storage_"):
        field = {"storage_endpoint": "endpoint", "storage_provider": "provider", "storage_protocol": "protocol_probe"}[fault]
        environment["object_storage"][field] = "unverified"
    elif fault == "missing_proof":
        del environment["storage_isolation_proof"]
    assert ci_results.green_e2e_source_and_egress_verified(
        environment, job, expected_harness_commit="b" * 40,
    ) is (fault == "")
    if not fault:
        # Another API/browser selector does not inherit this frontend-free rule.
        job["specs"] = json.dumps(["storage-message-embed-bundle.spec.ts"])
        assert ci_results.green_e2e_source_and_egress_verified(environment, job) is False


@pytest.mark.parametrize("selector", ["storage-team-portability.spec.ts", "storage-archive-lifecycle.spec.ts"])
@pytest.mark.parametrize("cleanup_present", [False, True])
def test_team_node_fetch_preserves_cleanup_gate_after_strict_runtime_validation(tmp_path, monkeypatch, cleanup_present, selector):
    import json

    environment = _team_node_environment()
    source, harness = environment["source_commit"], environment["harness_commit"]
    report = {"source_commit": source, "run_id": "7", "success": True, "harness_commit": harness,
              "results": [{"exit_code": 0, "spec": selector}]}
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("ci-results.json", json.dumps(report))
        bundle.writestr("ci-environment.json", json.dumps(environment))
        if cleanup_present:
            bundle.writestr("ci-cleanup.json", json.dumps({
                "run_id": "7", "harness_commit": harness, "containers_remaining": 0,
                "volumes_remaining": 0, "private_account_files_removed": True,
            }))
    monkeypatch.setattr(ci_results, "download", lambda command, root, output: output.write(archive.getvalue()))
    monkeypatch.setattr(ci_results, "RESERVE", 0)
    monkeypatch.setattr(ci_results.shutil, "disk_usage",
                        lambda _path: type("Usage", (), {"total": 100 * 1024**3,
                                                         "used": 10 * 1024**3,
                                                         "free": 90 * 1024**3})())
    monkeypatch.setattr(ci_results, "attach_visual_evidence", lambda result, directory: result)

    class Remote:
        repo = "example/repo"

        def request(self, endpoint):
            if "/artifacts?" in endpoint:
                return {"artifacts": [{"name": "isolated-test-results", "expired": False, "id": 8,
                                       "size_in_bytes": len(archive.getvalue())}]}
            if "/jobs?" in endpoint:
                return {"jobs": [{"id": 9, "labels": ["ubuntu-latest"], "runner_name": "GitHub Actions 9"}]}
            return {"head_sha": harness}

    job = {"id": "team", "source": source, "mode": "e2e", "run_id": 7, "state": "success",
           "url": "https://example.test/7", "specs": json.dumps([selector])}
    if cleanup_present:
        result = ci_results.fetch(Remote(), job, tmp_path)
        assert result["cleanup_verified"] is True
        assert result["source_commit"] == source and result["harness_commit"] == harness
    else:
        with pytest.raises(RuntimeError, match="run-bound account/container/volume cleanup"):
            ci_results.fetch(Remote(), job, tmp_path)
        assert not (tmp_path / "test-results/ci-runs/team/receipt.json").exists()
