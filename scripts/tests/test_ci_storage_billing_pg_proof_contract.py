# contract-test-file: infrastructure
"""Require the complete SQL billing proof for the frozen source capability."""

import base64
import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

from scripts import ci_environment


PERSONAL_FLAGS = {
    "passed", "frozen_snapshot", "exact_ledger_replay", "partial_invoice_unpaid",
    "four_delivered_warning_gates", "manual_hold", "deleted_owner_closed", "rollback_verified",
    "immutable_selected_units", "actual_expiry_transaction", "exact_warned_waiver",
    "regional_purge_outbox", "expiry_audit_replay",
}
TEAM_FLAGS = {
    "team_wallet_once", "team_four_recipient_warnings",
    "team_exact_warned_waiver", "team_rollback_verified",
}


@pytest.mark.parametrize("team_capable", [False, True])
@pytest.mark.parametrize("receipt_kind", [
    "personal", "team", "missing", "extra", "false", "numeric",
    "missing_team", "false_team", "numeric_team",
])
def test_sql_billing_proof_contract_is_exact_for_source_capability(
    tmp_path, monkeypatch, team_capable, receipt_kind,
):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner

    monkeypatch.setattr(runner, "has_team_storage_billing_schema", lambda _: team_capable)
    expected = PERSONAL_FLAGS | (TEAM_FLAGS if team_capable else set())
    keys = PERSONAL_FLAGS | (TEAM_FLAGS if receipt_kind == "team" else set())
    if receipt_kind not in ("personal", "team"):
        keys = expected.copy()
    if receipt_kind.endswith("_team"):
        keys = PERSONAL_FLAGS | TEAM_FLAGS
    proof = {key: True for key in keys}
    if receipt_kind == "missing":
        del proof["regional_purge_outbox"]
    elif receipt_kind == "extra":
        proof["unexpected_proof"] = True
    elif receipt_kind == "false":
        proof["actual_expiry_transaction"] = False
    elif receipt_kind == "numeric":
        proof["actual_expiry_transaction"] = 1
    elif receipt_kind == "missing_team":
        del proof["team_wallet_once"]
    elif receipt_kind == "false_team":
        proof["team_four_recipient_warnings"] = False
    elif receipt_kind == "numeric_team":
        proof["team_exact_warned_waiver"] = 1
    monkeypatch.setattr(runner, "compose", lambda *_, **__: SimpleNamespace(stdout=json.dumps(proof)))
    env = {
        "OPENMATES_CI_ISOLATED": "1", "OPENMATES_STORAGE_CAPACITY_FIXTURES": "true",
        "S3_ENDPOINT_URL": "http://storage.ci.test:9000", "SERVER_ENVIRONMENT": "development",
        "STORAGE_LOGICAL_S3_BILLING_ENABLED": "1", "BUILD_COMMIT_SHA": "a" * 40,
        **({"TEAM_STORAGE_BILLING_ENABLED": "1"} if team_capable else {}),
    }
    receipt = tmp_path / "pg-proof.json"
    hashed_email = base64.b64encode(hashlib.sha256(b"ci-proof@example.com").digest()).decode()
    accepted = receipt_kind == ("team" if team_capable else "personal")
    def call():
        runner.run_storage_billing_pg_probe(
            env, "4da92a23-c566-4f02-a4a6-d36aeb8a88e2", receipt, hashed_email=hashed_email,
        )
    if accepted:
        call()
        assert json.loads(receipt.read_text())["proof"] == proof
    else:
        with pytest.raises(RuntimeError, match="probe_receipt_invalid_or_timeout"):
            call()
    assert json.loads(receipt.read_text())["passed"] is accepted


@pytest.mark.parametrize("team_capable", [False, True])
def test_personal_legacy_profile_never_runs_logical_sql_probe(tmp_path, monkeypatch, team_capable):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner

    monkeypatch.setattr(runner, "has_team_storage_billing_schema", lambda _: team_capable)
    monkeypatch.setattr(runner, "compose", lambda *_, **__: pytest.fail("Legacy must not execute the logical SQL proof"))
    env = {
        "OPENMATES_CI_ISOLATED": "1", "OPENMATES_STORAGE_CAPACITY_FIXTURES": "true",
        "S3_ENDPOINT_URL": "http://storage.ci.test:9000", "SERVER_ENVIRONMENT": "development",
        "STORAGE_LOGICAL_S3_BILLING_ENABLED": "0", "TEAM_STORAGE_BILLING_ENABLED": "0",
        "BUILD_COMMIT_SHA": "a" * 40,
    }
    hashed_email = base64.b64encode(hashlib.sha256(b"ci-proof@example.com").digest()).decode()
    with pytest.raises(RuntimeError, match="requires the isolated logical profile"):
        runner.run_storage_billing_pg_probe(
            env, "4da92a23-c566-4f02-a4a6-d36aeb8a88e2", tmp_path / "proof.json", hashed_email=hashed_email,
        )


@pytest.mark.parametrize("team_flag", [None, "0"])
def test_team_source_requires_enabled_team_logical_profile(tmp_path, monkeypatch, team_flag):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts import ci_run_tests as runner

    monkeypatch.setattr(runner, "has_team_storage_billing_schema", lambda _: True)
    monkeypatch.setattr(runner, "compose", lambda *_, **__: pytest.fail("Disabled Team profile must not run SQL proof"))
    env = {
        "OPENMATES_CI_ISOLATED": "1", "OPENMATES_STORAGE_CAPACITY_FIXTURES": "true",
        "S3_ENDPOINT_URL": "http://storage.ci.test:9000", "SERVER_ENVIRONMENT": "development",
        "STORAGE_LOGICAL_S3_BILLING_ENABLED": "1", "BUILD_COMMIT_SHA": "a" * 40,
        **({"TEAM_STORAGE_BILLING_ENABLED": team_flag} if team_flag is not None else {}),
    }
    hashed_email = base64.b64encode(hashlib.sha256(b"ci-proof@example.com").digest()).decode()
    with pytest.raises(RuntimeError, match="requires the isolated logical profile"):
        runner.run_storage_billing_pg_probe(
            env, "4da92a23-c566-4f02-a4a6-d36aeb8a88e2", tmp_path / "proof.json", hashed_email=hashed_email,
        )
