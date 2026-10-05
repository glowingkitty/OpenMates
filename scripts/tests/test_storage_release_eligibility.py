# contract-test-file: infrastructure
"""Unproven archive rollout releases never acquire a signing certificate."""
import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import sys
import zipfile

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts import storage_release_eligibility as issuer
from scripts.storage_rollout import PRUNE_CHECKS, _canonical_json, validate_release_certificate

SOURCE, APPROVED, HARNESS = "a" * 40, "b" * 40, "c" * 40
TREE, HARNESS_TREE = "d" * 64, "e" * 64


def reviewed(payload, key):
    return {"schema": issuer.REVIEW_SCHEMA, "payload": payload,
            "signature": base64.b64encode(key.sign(_canonical_json(payload))).decode()}


def documents(run_id, paced=False):
    workload = {"passed": True, "failures": [], "validation_level": "target",
                "workload_target_met": True, "profile": "accelerated",
                "counts": {"round": 500000, "embed": 200000, "version": 1000000},
                "server_task_peak_concurrency": 500, "uncached_page_samples": 200,
                "uncached_page_p95_ms": 1000,
                "provider": {"real_provider_calls": 0, "blocked_provider_calls": 0,
                             "cache_misses": 0, "cache_hits": 1510000}}
    if paced:
        workload.update(profile="sustained", validation_level="pilot", workload_target_met=False,
                        duration_seconds=900, measured_duration_seconds=900)
    report = {"source_commit": APPROVED, "harness_commit": HARNESS, "run_id": str(run_id),
              "success": True, "error": None, "runtime_profile": "e2e", "results": [
                  {"spec": "storage-capacity-target.spec.ts" if not paced else "storage-capacity-calibration.spec.ts",
                   "exit_code": 0, "stats": {"expected": 1, "unexpected": 0, "skipped": 0, "flaky": 0}},
                  {"suite": "storage-capacity-target" if not paced else "storage-capacity-pilot",
                   "exit_code": 0, "report": workload}]}
    environment = {"source_commit": APPROVED, "harness_commit": HARNESS, "run_id": str(run_id),
                   "storage_capacity": {"provider_credentials": "absent", "provider_network": "internal"}}
    return report, environment


def archive(report, environment):
    value = io.BytesIO()
    with zipfile.ZipFile(value, "w") as bundle:
        bundle.writestr("ci-results.json", json.dumps(report))
        bundle.writestr("ci-environment.json", json.dumps(environment))
    return value.getvalue()


def fixture():
    key = Ed25519PrivateKey.generate()
    public = base64.b64encode(key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    main, env = documents(7)
    paced, paced_env = documents(8, True)
    def record(run_id, report, environment):
        return {"kind": "github-actions", "run_id": run_id, "harness_commit": HARNESS,
                "report_sha256": hashlib.sha256(json.dumps(report).encode()).hexdigest(),
                "environment_sha256": hashlib.sha256(json.dumps(environment).encode()).hexdigest(),
                "spec": report["results"][0]["spec"]}
    ci = record(7, main, env)
    checks = {name: dict(ci) for name in PRUNE_CHECKS}
    checks["p7_capacity_target"]["paced_evidence"] = record(8, paced, paced_env)
    checks["apple_reader"] = {"kind": "maintainer-reviewed", "source_commit": APPROVED,
                              "outcome": "passed", "synthetic": False,
                              "evidence_id": "native-proof-123", "evidence_sha256": "f" * 64}
    payload = {"approved_source_commit": APPROVED, "protected_tree_sha256": TREE,
               "protected_harness_sha256": HARNESS_TREE, "checks": checks,
               "review_id": "release-review-123", "reviewer": "maintainer",
               "approved_at": "2026-01-01T00:00:00+00:00"}
    class Remote:
        def run(self, run_id):
            return {"status": "completed", "conclusion": "success", "event": "workflow_dispatch",
                    "path": ".github/workflows/isolated-tests.yml", "head_sha": HARNESS,
                    "head_repository": {"full_name": issuer.REPOSITORY}}
        def artifact(self, run_id, name):
            assert name == "isolated-test-results"
            return archive(main, env) if run_id == 7 else archive(paced, paced_env)
    return key, public, payload, Remote(), main, env, paced


def prepare(key, public, payload, remote, **changes):
    return issuer.prepare_payload(reviewed(payload, key), source=SOURCE, tree_digest=TREE,
        harness_digest=HARNESS_TREE, harness_digest_for_source=lambda source: HARNESS_TREE,
        public_key=public, github=remote, **changes)


def test_complete_reviewed_candidate_proof_signs_exact_public_release():
    key, public, payload, remote, *_ = fixture()
    now = datetime.now(timezone.utc)
    result = prepare(key, public, payload, remote, now=now)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    certificate = issuer.sign_certificate(result, pem, public)
    validated = validate_release_certificate(certificate, environ={"BUILD_COMMIT_SHA": SOURCE},
                                             trusted_public_key=public, now=now)
    assert validated["payload"]["prune_ready"] is True
    assert result["approved_source_commit"] == APPROVED
    assert all(check["source_commit"] == SOURCE for check in result["checks"].values())
    assert result["checks"]["p7_capacity_target"]["simultaneous_executions"] == 500
    renewed = prepare(key, public, payload, remote)
    assert renewed["checks"] == result["checks"]
    changed = deepcopy(certificate)
    changed["payload"]["source_commit"] = "f" * 40
    with pytest.raises(ValueError, match="signature"):
        validate_release_certificate(changed, environ={"BUILD_COMMIT_SHA": "f" * 40}, trusted_public_key=public)


@pytest.mark.parametrize("name", ["apple_reader", "p7_zero_provider_calls", "p7_capacity_target"])
def test_missing_required_proof_cannot_become_eligibility(name):
    key, public, payload, remote, *_ = fixture()
    del payload["checks"][name]
    if name == "apple_reader":
        with pytest.raises(ValueError, match="pending"):
            prepare(key, public, payload, remote)
    else:
        result = prepare(key, public, payload, remote)
        assert result["reader_ready"] is True and result["prune_ready"] is False
        assert name in result["pending_checks"] and name not in result["checks"]


@pytest.mark.parametrize("fault", ["failed", "foreign-repo", "foreign-workflow", "harness"])
def test_ci_run_provenance_is_verified_independently(fault):
    key, public, payload, remote, *_ = fixture()
    original = remote.run
    def run(run_id):
        result = original(run_id)
        if fault == "failed":
            result["conclusion"] = "failure"
        if fault == "foreign-repo":
            result["head_repository"]["full_name"] = "other/repo"
        if fault == "foreign-workflow":
            result["path"] = ".github/workflows/unreviewed.yml"
        if fault == "harness":
            result["head_sha"] = "f" * 40
        return result
    remote.run = run
    with pytest.raises(ValueError, match="trusted repository"):
        prepare(key, public, payload, remote)


@pytest.mark.parametrize("fault", ["tree", "actual-harness", "signature", "source", "report-digest", "synthetic-native"])
def test_source_tree_review_signature_and_report_bytes_cannot_be_substituted(fault):
    key, public, payload, remote, main, env, _ = fixture()
    if fault == "tree":
        payload["protected_tree_sha256"] = "f" * 64
    if fault == "actual-harness":
        with pytest.raises(ValueError, match="Actual CI harness"):
            issuer.prepare_payload(reviewed(payload, key), source=SOURCE, tree_digest=TREE,
                harness_digest=HARNESS_TREE, harness_digest_for_source=lambda source: "f" * 64,
                public_key=public, github=remote)
        return
    if fault == "signature":
        public = base64.b64encode(Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    if fault == "source":
        main["source_commit"] = "f" * 40
    if fault == "report-digest":
        main["unreviewed"] = True
    if fault == "synthetic-native":
        payload["checks"]["apple_reader"]["synthetic"] = True
    with pytest.raises(ValueError):
        prepare(key, public, payload, remote)


@pytest.mark.parametrize("fault", ["pilot", "rounds", "concurrency", "latency", "provider", "credential", "paced", "calibration-spec"])
def test_p7_counts_latency_provider_and_paced_proof_are_measured(fault):
    key, public, payload, remote, main, env, paced = fixture()
    workload = main["results"][1]["report"]
    if fault == "pilot":
        workload["validation_level"] = "pilot"
    if fault == "rounds":
        workload["counts"]["round"] = 499999
    if fault == "concurrency":
        workload["server_task_peak_concurrency"] = 499
    if fault == "latency":
        workload["uncached_page_p95_ms"] = 1001
    if fault == "provider":
        workload["provider"]["real_provider_calls"] = 1
    if fault == "credential":
        env["storage_capacity"]["provider_credentials"] = "present"
    if fault == "paced":
        paced["results"][1]["report"]["measured_duration_seconds"] = 1
    if fault == "calibration-spec":
        main["results"][0]["spec"] = "storage-capacity-calibration.spec.ts"
        for record in payload["checks"].values():
            if record["kind"] == "github-actions":
                record["spec"] = main["results"][0]["spec"]
    # Preserve the maintainer's review of these exact bytes. Independent
    # measured gates must still reject an approved document with bad metrics.
    for record in payload["checks"].values():
        if record["kind"] == "github-actions":
            record["report_sha256"] = hashlib.sha256(json.dumps(main).encode()).hexdigest()
            record["environment_sha256"] = hashlib.sha256(json.dumps(env).encode()).hexdigest()
    payload["checks"]["p7_capacity_target"]["paced_evidence"]["report_sha256"] = hashlib.sha256(json.dumps(paced).encode()).hexdigest()
    result = prepare(key, public, payload, remote)
    assert result["reader_ready"] is True and result["prune_ready"] is False
    assert "p7_capacity_target" not in result["checks"]


def test_digest_includes_all_protected_paths_and_excludes_only_registry(monkeypatch, tmp_path):
    entries = [b"100644 blob " + b"a" * 40 + b"\tbackend/new/unlisted.py\0",
               b"100644 blob " + b"b" * 40 + b"\tscripts/ci_run_tests.py\0",
               b"100644 blob " + b"e" * 40 + b"\tdocs/release.md\0",
               b"100644 blob " + b"f" * 40 + b"\tREADME.md\0",
               b"100644 blob " + b"c" * 40 + b"\tconfig/storage-release-evidence.json\0"]
    monkeypatch.setattr(issuer.subprocess, "check_output", lambda command, **kwargs: b"".join(entries))
    digest = issuer.protected_tree_digest(tmp_path, SOURCE)
    entries[-1] = entries[-1].replace(b"c" * 40, b"d" * 40)
    entries[-2] = entries[-2].replace(b"f" * 40, b"d" * 40)
    entries[-3] = entries[-3].replace(b"e" * 40, b"d" * 40)
    assert issuer.protected_tree_digest(tmp_path, SOURCE) == digest
    entries[0] = entries[0].replace(b"a" * 40, b"f" * 40)
    assert issuer.protected_tree_digest(tmp_path, SOURCE) != digest


def test_swift_product_change_invalidates_reviewed_release_digest(monkeypatch, tmp_path):
    entries = [b"100644 blob " + b"a" * 40 + b"\tapple/OpenMates/StorageReader.swift\0",
               b"100644 blob " + b"b" * 40 + b"\tscripts/ci_run_tests.py\0"]
    monkeypatch.setattr(issuer.subprocess, "check_output", lambda command, **kwargs: b"".join(entries))
    runtime_digest = issuer.protected_tree_digest(tmp_path, SOURCE)
    harness_digest = issuer.protected_tree_digest(tmp_path, SOURCE, harness_only=True)
    entries[0] = entries[0].replace(b"a" * 40, b"c" * 40)
    assert issuer.protected_tree_digest(tmp_path, SOURCE) != runtime_digest
    assert issuer.protected_tree_digest(tmp_path, SOURCE, harness_only=True) == harness_digest


def test_missing_registry_skips_without_reading_or_printing_private_key(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(issuer, "__file__", str(tmp_path / "scripts/storage_release_eligibility.py"))
    monkeypatch.setattr(issuer.subprocess, "check_output", lambda *args, **kwargs: SOURCE)
    for name, value in {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": issuer.REPOSITORY,
                        "GITHUB_REF": "refs/heads/dev", "GITHUB_EVENT_NAME": "push",
                        "GITHUB_SHA": SOURCE, "STORAGE_MIGRATION_RELEASE_SIGNING_KEY": "never-print-private-key"}.items():
        monkeypatch.setenv(name, value)
    destination = tmp_path / "certificate.json"
    monkeypatch.setattr(sys, "argv", ["issuer", "--source", SOURCE, "--output", str(destination)])
    assert issuer.main() == 0
    assert not destination.exists()
    output = capsys.readouterr().out
    assert "pending" in output and "never-print-private-key" not in output


def test_sealed_review_retains_verified_reports_after_ci_artifact_expiry(monkeypatch, tmp_path):
    key, public, payload, remote, *_ = fixture()
    monkeypatch.setattr(issuer, "protected_tree_digest", lambda root, source, harness_only=False:
                        HARNESS_TREE if harness_only else TREE)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    registry = issuer.seal_review(root=tmp_path, source=APPROVED, checks=payload["checks"],
        reviewer="maintainer", review_id="release-review-123", private_pem=pem,
        public_key=public, github=remote)
    assert set(registry["payload"]["ci_reports"]) == {"7", "8"}
    remote.artifact = lambda *args: pytest.fail("Permanent reviewed proof must not require expired CI artifacts")
    result = issuer.prepare_payload(registry, source=SOURCE, tree_digest=TREE,
        harness_digest=HARNESS_TREE, harness_digest_for_source=lambda source: HARNESS_TREE,
        public_key=public, github=remote)
    assert result["prune_ready"] is True
    assert result["validity"] == "exact-source" and result["expires_at"] is None
    # Signed original reports remain hash-bound even after remote artifact expiry.
    registry["payload"]["ci_reports"]["7"]["report"] = base64.b64encode(b'{}').decode()
    changed = reviewed(registry["payload"], key)
    with pytest.raises(ValueError, match="digest differs"):
        issuer.prepare_payload(changed, source=SOURCE, tree_digest=TREE,
            harness_digest=HARNESS_TREE, harness_digest_for_source=lambda source: HARNESS_TREE,
            public_key=public, github=remote)


def test_partial_reader_certificate_preserves_reader_check_identity():
    key, public, payload, remote, *_ = fixture()
    complete = prepare(key, public, payload, remote)
    del payload["checks"]["p7_capacity_target"]
    partial = prepare(key, public, payload, remote)
    assert partial["reader_ready"] is True and partial["prune_ready"] is False
    from scripts.storage_rollout import READ_CHECKS
    assert {name: partial["checks"][name] for name in READ_CHECKS} == {
        name: complete["checks"][name] for name in READ_CHECKS}
