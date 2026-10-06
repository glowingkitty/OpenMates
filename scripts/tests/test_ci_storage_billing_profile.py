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


@pytest.mark.parametrize("team_case", ["old", "rated", "unrated", "missing_crypto", "missing_team_id", "missing_team_bytes", "missing_disabled", "false_disabled", "rated_legacy", "nonzero_legacy", "profile_mismatch"])
@pytest.mark.parametrize("profile_mode,invalid_expiry", [
    ("logical", None), ("logical", "missing"), ("logical", "large_object"),
    ("logical", "ledger_changed"), ("legacy", None),
])
def test_billing_probe_uses_private_selector_and_only_public_totals(tmp_path, monkeypatch, profile_mode, invalid_expiry, team_case):
    runner = _runner(monkeypatch)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    if team_case != "old":
        schema = tmp_path / "backend/core/directus/schemas/team_storage_billing.yml"
        schema.parent.mkdir(parents=True)
        schema.write_text("team_storage_billing_periods: {}\n")
    monkeypatch.setattr(ci_environment, "has_team_storage_billing_schema", lambda _: team_case != "old")
    profile = ci_environment.compose_profile(
        "a" * 40, billing_profile=profile_mode, account_emails=["ci-one@example.com"]
    )
    if team_case != "old":
        profile["services"]["api"]["environment"]["TEAM_STORAGE_BILLING_ENABLED"] = "1" if profile_mode == "logical" else "0"
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
            return SimpleNamespace(stdout=json.dumps({key: True for key in (runner.STORAGE_BILLING_PG_PROOF_FLAGS |
                (runner.TEAM_STORAGE_BILLING_PG_PROOF_FLAGS if team_case != "old" else set()))}))
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
            if team_case != "old":
                summary.update(team_id="5cd17363-d30c-40c4-ac66-a3eeaa98fca9", team_total_bytes=227,
                               team_rated=profile_mode == "logical", team_contact_crypto=profile_mode == "logical",
                               cms_team_disabled_claim_rejected=profile_mode == "legacy")
                if profile_mode == "legacy":
                    summary["team_total_bytes"] = 0
                if team_case == "unrated":
                    summary["team_rated"] = not summary["team_rated"]
                if team_case == "missing_disabled" and profile_mode == "legacy":
                    summary.pop("cms_team_disabled_claim_rejected")
                if team_case == "false_disabled" and profile_mode == "legacy":
                    summary["cms_team_disabled_claim_rejected"] = False
                if team_case == "rated_legacy" and profile_mode == "legacy":
                    summary["team_rated"] = True
                if team_case == "nonzero_legacy" and profile_mode == "legacy":
                    summary["team_total_bytes"] = 1
                if team_case == "missing_crypto":
                    summary.pop("team_contact_crypto")
                elif team_case == "missing_team_id":
                    summary.pop("team_id")
                elif team_case == "missing_team_bytes":
                    summary.pop("team_total_bytes")
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
    if team_case == "profile_mismatch":
        profile["services"]["api"]["environment"]["TEAM_STORAGE_BILLING_ENABLED"] = "0" if profile_mode == "logical" else "1"
        compose_path.write_text(json.dumps(profile))
        with pytest.raises(RuntimeError, match="exact Team profile"):
            runner.prepare_storage_billing_fixture(
                {"OPENMATES_TEST_ACCOUNT_EMAIL": "ci-one@example.com"}, profile_mode,
            )
        assert calls == []
        return
    team_invalid = team_case in {"unrated", "missing_team_id", "missing_team_bytes"} or (
        team_case == "missing_crypto"
    ) or (profile_mode == "legacy" and team_case in {
        "missing_disabled", "false_disabled", "rated_legacy", "nonzero_legacy"}
    )
    if invalid_expiry or team_invalid:
        with pytest.raises(RuntimeError, match="complete bounded receipt"):
            runner.prepare_storage_billing_fixture(
                {"OPENMATES_TEST_ACCOUNT_EMAIL": "ci-one@example.com"}, profile_mode
            )
        assert "cleanup" in calls[-1]
        return
    env, paths = runner.prepare_storage_billing_fixture(
        {"OPENMATES_TEST_ACCOUNT_EMAIL": "ci-one@example.com"}, profile_mode
    )
    if team_case == "old":
        assert env["E2E_STORAGE_BILLING_TEAM_UNRATED"] == "1"
        assert "E2E_STORAGE_BILLING_TEAM_RATED" not in env
    elif profile_mode == "legacy":
        assert env["E2E_STORAGE_BILLING_CMS_TEAM_DISABLED_CLAIM_REJECTED"] == "1"
        assert "E2E_STORAGE_BILLING_TEAM_RATED" not in env
    else:
        assert env["E2E_STORAGE_BILLING_TEAM_RATED"] == "1"
        assert env["E2E_STORAGE_BILLING_TEAM_BYTES"] == "227"
        assert "E2E_STORAGE_BILLING_TEAM_UNRATED" not in env
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
        **({"E2E_STORAGE_BILLING_TEAM_UNRATED": "1"} if team_case == "old" else
           {"E2E_STORAGE_BILLING_CMS_TEAM_DISABLED_CLAIM_REJECTED": "1"} if profile_mode == "legacy" else
           {"E2E_STORAGE_BILLING_TEAM_RATED": "1",
            "E2E_STORAGE_BILLING_TEAM_ID": "5cd17363-d30c-40c4-ac66-a3eeaa98fca9",
            "E2E_STORAGE_BILLING_TEAM_BYTES": "227"}),
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


@pytest.mark.parametrize("marker,expected", [
    ("storage_billing_fixture_failed:storage_billing_upload_not_verified", "storage_billing_upload_not_verified"),
    ("storage_billing_fixture_failed:private-owner@example.com", "probe_failed"),
])
def test_fixture_process_failure_exposes_only_static_diagnostic(tmp_path, monkeypatch, marker, expected):
    import subprocess
    runner = _runner(monkeypatch)
    profile = ci_environment.compose_profile("a" * 40, billing_profile="legacy")
    private = tmp_path / "storage-billing"
    private.mkdir(mode=0o700)
    compose_path = tmp_path / "compose.json"
    compose_path.write_text(json.dumps(profile))
    monkeypatch.setattr(runner, "COMPOSE_PATH", compose_path)
    monkeypatch.setattr(runner, "require_runner", lambda: None)
    monkeypatch.setattr(runner, "cms_admin_token", lambda _: "private-admin-token")
    user_id = "4da92a23-c566-4f02-a4a6-d36aeb8a88e2"
    hashed_email = base64.b64encode(hashlib.sha256(b"ci-one@example.com").digest()).decode()
    monkeypatch.setattr(runner, "request", lambda *_args, **_kwargs: {"data": [{
        "id": user_id, "email": hashed_email + "@example.com", "hashed_email": hashed_email,
    }]})
    def compose(*args, **_kwargs):
        raise subprocess.CalledProcessError(1, args, stderr=f"secret-token {user_id}\n{marker}\n")
    monkeypatch.setattr(runner, "compose", compose)
    with pytest.raises(RuntimeError) as failure:
        runner.prepare_storage_billing_fixture({"OPENMATES_TEST_ACCOUNT_EMAIL": "ci-one@example.com"}, "legacy")
    assert str(failure.value).endswith(":" + expected)
    assert all(value not in str(failure.value) for value in (user_id, "secret-token", "private-owner@example.com"))


def test_team_storage_component_keeps_static_fixture_classification():
    manifest = json.loads((Path(__file__).resolve().parents[1] / "ci_coverage_manifest.json").read_text())
    icon_groups = [key for key, group in manifest["groups"].items()
                   if "components/settings-teams-icons.spec.ts" in group["specs"]]
    storage_groups = [key for key, group in manifest["groups"].items()
                      if "components/settings-teams-storage.spec.ts" in group["specs"]]
    assert len(icon_groups) == 1
    assert storage_groups == icon_groups



@pytest.mark.parametrize("service,key,value", [
    ("api", "OPENMATES_DEPLOYMENT_MODE", "official_cloud"),
    ("cms", "OPENMATES_DEPLOYMENT_MODE", "self_host"),
    ("cms", "OPENMATES_CLOUD_OVERLAY_ENABLED", "true"),
    ("api", "OPENMATES_CLOUD_OVERLAY_PACKAGE", "OpenMatesCloud"),
    ("cms", "TEAM_STORAGE_BILLING_ENABLED", "1"),
])
def test_team_legacy_runner_requires_isolated_cms_and_valid_api_mode(tmp_path, monkeypatch, service, key, value):
    runner = _runner(monkeypatch)
    monkeypatch.setattr(runner, "has_team_storage_billing_schema", lambda _: True)
    monkeypatch.setattr(ci_environment, "has_team_storage_billing_schema", lambda _: True)
    profile = ci_environment.compose_profile("a" * 40, billing_profile="legacy")
    for name in ("api", "core-worker", "cms"):
        assert profile["services"][name]["environment"]["OPENMATES_DEPLOYMENT_MODE"] == ("official_cloud" if name == "cms" else "self_host")
        assert profile["services"][name]["environment"]["TEAM_STORAGE_BILLING_ENABLED"] == "0"
    profile["services"][service]["environment"][key] = value
    compose_path = tmp_path / "compose.json"
    compose_path.write_text(json.dumps(profile))
    monkeypatch.setattr(runner, "COMPOSE_PATH", compose_path)
    monkeypatch.setattr(runner, "require_runner", lambda: None)
    monkeypatch.setattr(runner, "cms_admin_token", lambda _: pytest.fail("Identity lookup must not run"))
    with pytest.raises(RuntimeError, match="isolated CMS guard profile"):
        runner.prepare_storage_billing_fixture({"OPENMATES_TEST_ACCOUNT_EMAIL": "ci-one@example.com"}, "legacy")


def test_team_legacy_cms_fence_preserves_generic_and_logical_self_host_profiles(monkeypatch):
    monkeypatch.setattr(ci_environment, "has_team_storage_billing_schema", lambda _: True)
    for options in ({}, {"billing_profile": "logical"}):
        profile = ci_environment.compose_profile("a" * 40, **options)
        assert profile["services"]["api"]["environment"]["OPENMATES_DEPLOYMENT_MODE"] == "self_host"
        assert "OPENMATES_DEPLOYMENT_MODE" not in profile["services"]["cms"]["environment"]
