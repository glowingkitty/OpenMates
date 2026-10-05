# contract-test-file: infrastructure
"""The storage billing probe stays inside one signed disposable CI identity."""

import importlib.util
import base64
import hashlib
import json
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import ci_environment


def _runner(monkeypatch):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    path = Path(__file__).resolve().parents[1] / "ci_run_tests.py"
    spec = importlib.util.spec_from_file_location("_billing_ci_runner", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_billing_selectors_are_exact_and_classified(monkeypatch):
    runner = _runner(monkeypatch)
    expected = {
        "billing-storage-legacy.spec.ts": "legacy",
        "billing-storage-logical.spec.ts": "logical",
    }
    manifest = json.loads((Path(__file__).resolve().parents[1] / "ci_coverage_manifest.json").read_text())
    assert ci_environment.BILLING_STORAGE_PROFILES == expected
    assert runner.BILLING_STORAGE_PROFILES == expected
    assert set(manifest["groups"]["storage_billing_metering"]["specs"]) == set(expected)
    assert not set(expected).intersection(ci_environment.CAPACITY_WORKLOAD_SPECS)
    assert not set(expected).intersection(runner.CAPACITY_WORKLOAD_SPECS)


def test_capacity_profile_does_not_enable_storage_billing():
    profile = ci_environment.compose_profile("a" * 40, storage_capacity=True)
    for service in ("api", "core-worker", "ai-worker"):
        assert "STORAGE_LOGICAL_S3_BILLING_ENABLED" not in profile["services"][service]["environment"]
        assert not any(isinstance(mount, str) and mount.endswith(":/app/ci-storage-billing")
                       for mount in profile["services"][service]["volumes"])


@pytest.mark.parametrize("mode,flag", [("legacy", "0"), ("logical", "1")])
def test_billing_profile_limits_flag_and_private_bind_to_api(mode, flag):
    profile = ci_environment.compose_profile(
        "a" * 40, billing_profile=mode, account_emails=["ci-one@example.com"]
    )
    services = profile["services"]
    api = services["api"]
    assert api["environment"]["STORAGE_LOGICAL_S3_BILLING_ENABLED"] == flag
    assert api["environment"]["OPENMATES_CI_ISOLATED"] == "1"
    assert api["environment"]["S3_ENDPOINT_URL"] == "http://storage.ci.test:9000"
    assert any(isinstance(mount, str) and mount.endswith(":/app/ci-storage-billing")
               for mount in api["volumes"])
    for service in ("core-worker", "ai-worker"):
        assert "STORAGE_LOGICAL_S3_BILLING_ENABLED" not in services[service]["environment"]
        assert not any(isinstance(mount, str) and mount.endswith(":/app/ci-storage-billing")
                       for mount in services[service]["volumes"])
        assert "OPENAI_API_KEY" not in services[service]["environment"]
    assert profile["networks"]["default"]["internal"] is True


@pytest.mark.parametrize("profile_mode,invalid_expiry", [
    ("logical", None), ("logical", "missing"), ("logical", "large_object"),
    ("logical", "ledger_changed"), ("legacy", None),
])
def test_billing_probe_uses_private_selector_and_only_public_totals(tmp_path, monkeypatch, profile_mode, invalid_expiry):
    runner = _runner(monkeypatch)
    profile = ci_environment.compose_profile(
        "a" * 40, billing_profile=profile_mode, account_emails=["ci-one@example.com"]
    )
    private = tmp_path / "storage-billing"
    private.mkdir(mode=0o700)
    compose_path = tmp_path / "compose.json"
    compose_path.write_text(json.dumps(profile))
    monkeypatch.setattr(runner, "COMPOSE_PATH", compose_path)
    monkeypatch.setattr(runner, "require_runner", lambda: None)
    monkeypatch.setattr(runner, "cms_admin_token", lambda _: "private-admin-token")
    user_id = "4da92a23-c566-4f02-a4a6-d36aeb8a88e2"
    hashed_email = base64.b64encode(hashlib.sha256(b"ci-one@example.com").digest()).decode()
    def users(url, token=None):
        import urllib.parse
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        assert query["filter[hashed_email][_eq]"] == [hashed_email]
        assert "filter[email][_eq]" not in query
        return {"data": [{"id": user_id, "email": hashed_email + "@example.com",
                          "hashed_email": hashed_email}]}
    monkeypatch.setattr(runner, "request", users)
    calls = []

    def fake_compose(*args, **_kwargs):
        calls.append(args)
        if "node" in args:
            assert profile_mode == "logical"
            return SimpleNamespace(stdout=json.dumps({key: True for key in runner.STORAGE_BILLING_PG_PROOF_FLAGS}))
        if "prepare" in args:
            receipt_name = Path(args[args.index("--receipt-file") + 1]).name
            (private / receipt_name).write_text("{}")
            summary = {
                "prepared": True, "legacy_upload_bytes": 96, "page_bytes": 321,
                "full_total_bytes": 417, "team_unrated": True, "dedup": True,
                "conflict_failed_closed": True,
                "expiry": {"verified": True, "real_regional_purge": True,
                           "ledger_unchanged": True, "warned_only_waived": True,
                           "physical_object_bytes": 224},
            }
            if profile_mode == "legacy":
                summary["expiry"] = None
            if invalid_expiry == "missing":
                summary.pop("expiry")
            elif invalid_expiry == "large_object":
                summary["expiry"]["physical_object_bytes"] = 1024
            elif invalid_expiry == "ledger_changed":
                summary["expiry"]["ledger_unchanged"] = False
            return SimpleNamespace(stdout=json.dumps(summary))
        return SimpleNamespace(stdout='{"cleaned": true}')

    monkeypatch.setattr(runner, "compose", fake_compose)
    if invalid_expiry:
        with pytest.raises(RuntimeError, match="complete bounded receipt"):
            runner.prepare_storage_billing_fixture(
                {"OPENMATES_TEST_ACCOUNT_EMAIL": "ci-one@example.com"}, "logical"
            )
        assert "cleanup" in calls[-1]
        return
    env, paths = runner.prepare_storage_billing_fixture(
        {"OPENMATES_TEST_ACCOUNT_EMAIL": "ci-one@example.com"}, profile_mode
    )
    selector, receipt = paths
    assert stat.S_IMODE(selector.stat().st_mode) == 0o600
    private_value = json.loads(selector.read_text())
    assert private_value["source_commit"] == "a" * 40
    assert private_value["user_id"] == user_id
    assert private_value["fixture_prefix"].startswith("ci-storage-billing/")
    assert env == {
        "E2E_STORAGE_BILLING_EXPECTED_LEGACY_BYTES": "96",
        "E2E_STORAGE_BILLING_EXPECTED_PAGE_BYTES": "321",
        "E2E_STORAGE_BILLING_EXPECTED_TOTAL_BYTES": "417",
        "E2E_STORAGE_BILLING_TEAM_UNRATED": "1",
        "E2E_STORAGE_BILLING_CONFLICT_REJECTED": "1",
        "E2E_STORAGE_BILLING_LEGACY_PROFILE": "1" if profile_mode == "legacy" else "0",
        "E2E_STORAGE_BILLING_LOGICAL_PROFILE": "1" if profile_mode == "logical" else "0",
        "E2E_STORAGE_BILLING_EXPIRY_VERIFIED": "1" if profile_mode == "logical" else "0",
    }
    assert receipt.exists()
    runner.cleanup_storage_billing_fixture(paths)
    if profile_mode == "legacy":
        assert "prepare" in calls[0] and "cleanup" in calls[1]
        assert not list(private.glob("pg-proof-*.json"))
        return
    assert "node" in calls[0] and "prepare" in calls[1] and "cleanup" in calls[2]
    assert calls[0][-2:] == (user_id, hashed_email)
    assert calls[0][-4] == "node" and calls[0][-5] == "cms"
    assert set(calls[0][index + 1] for index, arg in enumerate(calls[0]) if arg == "-e") == {
        "OPENMATES_CI_ISOLATED=1", "OPENMATES_STORAGE_CAPACITY_FIXTURES=true",
        "S3_ENDPOINT_URL=http://storage.ci.test:9000", "SERVER_ENVIRONMENT=development",
        "BUILD_COMMIT_SHA=" + "a" * 40,
    }
    pg_receipt = next(private.glob("pg-proof-*.json"))
    assert stat.S_IMODE(pg_receipt.stat().st_mode) == 0o600
    assert json.loads(pg_receipt.read_text())["passed"] is True
    assert user_id not in pg_receipt.read_text()


@pytest.mark.parametrize("failure", ["missing", "false", "oversized", "process"])
def test_pg_probe_requires_complete_receipt_and_sanitizes_private_logs(tmp_path, monkeypatch, failure):
    import subprocess
    runner = _runner(monkeypatch)
    env = ci_environment.compose_profile("a" * 40, billing_profile="logical")["services"]["api"]["environment"]
    user_id = "4da92a23-c566-4f02-a4a6-d36aeb8a88e2"
    receipt = tmp_path / "proof.json"

    def compose(*args, **kwargs):
        assert kwargs == {"capture": True, "timeout": 300}
        assert "api" not in args and "cms" in args
        proof = {key: True for key in runner.STORAGE_BILLING_PG_PROOF_FLAGS}
        if failure == "missing":
            proof.pop("rollback_verified")
        if failure == "false":
            proof["actual_expiry_transaction"] = False
        if failure == "oversized":
            return SimpleNamespace(stdout=" " * 4097 + json.dumps(proof))
        if failure == "process":
            raise subprocess.CalledProcessError(1, args,
                stderr=f"secret-token {user_id}\nstorage_billing_pg_probe_failed:stale_credit_balance\n")
        return SimpleNamespace(stdout=json.dumps(proof))

    monkeypatch.setattr(runner, "compose", compose)
    with pytest.raises(RuntimeError, match="PG proof failed") as failure_message:
        runner.run_storage_billing_pg_probe(env, user_id, receipt,
            hashed_email=base64.b64encode(hashlib.sha256(b"ci-one@example.com").digest()).decode())
    logged = receipt.read_text()
    assert user_id not in logged and "secret-token" not in logged
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    assert json.loads(logged)["passed"] is False
    if failure == "process":
        assert json.loads(logged)["error"] == "stale_credit_balance"
        assert str(failure_message.value).endswith(":stale_credit_balance")
    assert user_id not in str(failure_message.value) and "secret-token" not in str(failure_message.value)


def test_billing_probe_fails_before_user_lookup_if_profile_is_not_exact(tmp_path, monkeypatch):
    runner = _runner(monkeypatch)
    profile = ci_environment.compose_profile("a" * 40, billing_profile="legacy")
    profile["services"]["api"]["environment"]["STORAGE_LOGICAL_S3_BILLING_ENABLED"] = "1"
    compose_path = tmp_path / "compose.json"
    compose_path.write_text(json.dumps(profile))
    monkeypatch.setattr(runner, "COMPOSE_PATH", compose_path)
    monkeypatch.setattr(runner, "require_runner", lambda: None)
    monkeypatch.setattr(runner, "cms_admin_token", lambda _: pytest.fail("CMS lookup started"))
    with pytest.raises(RuntimeError, match="exact isolated profile"):
        runner.prepare_storage_billing_fixture(
            {"OPENMATES_TEST_ACCOUNT_EMAIL": "ci-one@example.com"}, "legacy"
        )
