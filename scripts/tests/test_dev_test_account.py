# contract-test-file: tooling
"""Throwaway dev test account fallback: lease choice, export-then-delete, sweep."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import dev_test_account as dta  # noqa: E402 - scripts dir is on the path at runtime


@pytest.fixture
def world(monkeypatch, tmp_path):
    calls: list[str] = []
    state = {"personal_busy": False, "export_fails": False}
    monkeypatch.setattr(dta, "REGISTRY", tmp_path / "accounts" / "registry.json")
    monkeypatch.setattr(dta, "BACKUPS", tmp_path / "backups")
    monkeypatch.setattr(dta, "personal_environment", lambda: {"OPENMATES_TEST_ACCOUNT_EMAIL": "personal@example.org"})
    monkeypatch.setattr(
        dta, "try_personal_account_lease",
        lambda prefix, sid: None if state["personal_busy"] else ("acct", "owner", {"a"}, "exclusive"),
    )
    monkeypatch.setattr(dta, "stack_lease", lambda prefix, sid, timeout: ("stack", "owner", {"s"}, "shared"))
    monkeypatch.setattr(
        dta, "wait_for_personal_leases",
        lambda prefix, sid, timeout: calls.append("wait") or [("acct", "o", {"a"}, "exclusive")],
    )
    monkeypatch.setattr(dta, "release_leases", lambda leases: calls.append("release") or [])

    def provision(name):
        calls.append("provision")
        dta.registry_update("t@example.org", created_at=datetime.now(UTC).isoformat(), status="provisioned")
        return {"OPENMATES_TEST_ACCOUNT_EMAIL": "t@example.org", "OPENMATES_TEST_ACCOUNT_PASSWORD": "p"}

    def export(credentials, destination):
        calls.append("export")
        if state["export_fails"]:
            raise dta.ThrowawayAccountError("boom")
        destination.mkdir(parents=True)

    monkeypatch.setattr(dta, "provision_throwaway", provision)
    monkeypatch.setattr(dta, "export_chats", export)
    monkeypatch.setattr(dta, "delete_account", lambda email: calls.append("delete") or "ok")
    return calls, state


def test_personal_free_uses_personal(world):
    calls, _ = world
    account = dta.acquire_real_test_account("p", "s", "t", stack_timeout=1)
    assert account.kind == "personal" and len(account.leases) == 2 and "provision" not in calls


def test_busy_provisions_throwaway(world):
    calls, state = world
    state["personal_busy"] = True
    account = dta.acquire_real_test_account("p", "s", "t", stack_timeout=1)
    assert account.kind == "throwaway" and account.email == "t@example.org"
    assert [lease[0] for lease in account.leases] == ["stack"] and "wait" not in calls


def test_busy_personal_only_waits(world):
    calls, state = world
    state["personal_busy"] = True
    account = dta.acquire_real_test_account("p", "s", "t", stack_timeout=1, allow_throwaway=False)
    assert account.kind == "personal" and calls == ["wait"]


def test_finish_exports_then_deletes(world):
    calls, state = world
    state["personal_busy"] = True
    account = dta.acquire_real_test_account("p", "s", "my-test", stack_timeout=1)
    receipt = dta.finish_real_test_account(account)
    assert calls[-3:] == ["release", "export", "delete"]
    assert receipt["export"]["status"] == "ok" and receipt["delete"]["status"] == "ok"
    backup = Path(receipt["export"]["path"])
    assert (backup / "manifest.json").exists() and "t@example.org" not in (backup / "manifest.json").read_text()
    assert dta.registry_entries()[0]["status"] == "deleted"


def test_export_failure_still_deletes(world):
    calls, state = world
    state.update(personal_busy=True, export_fails=True)
    receipt = dta.finish_real_test_account(dta.acquire_real_test_account("p", "s", "t", stack_timeout=1))
    assert receipt["export"]["status"] == "failed" and "boom" in receipt["export"]["error"]
    assert receipt["delete"]["status"] == "ok" and calls[-1] == "delete"


def test_sweep_cleans_stale_accounts_and_old_backups(world):
    calls, _ = world
    now = datetime.now(UTC)
    dta.registry_update("old@example.org", created_at=(now - timedelta(hours=3)).isoformat(), status="provisioned")
    dta.registry_update("new@example.org", created_at=now.isoformat(), status="provisioned")
    dta.registry_update("gone@example.org", created_at=(now - timedelta(days=1)).isoformat(), status="deleted")
    old = dta.BACKUPS / (now - timedelta(days=8)).strftime("%Y-%m-%d")
    fresh = dta.BACKUPS / (now - timedelta(days=2)).strftime("%Y-%m-%d")
    old.mkdir(parents=True)
    fresh.mkdir(parents=True)

    dry = dta.sweep(dry_run=True)
    assert len(dry["accounts"]) == 1 and old.exists() and "delete" not in calls

    dta.sweep()
    assert calls.count("delete") == 1 and not old.exists() and fresh.exists()
    statuses = {e["email"]: e["status"] for e in dta.registry_entries()}
    assert statuses == {"old@example.org": "deleted", "new@example.org": "provisioned", "gone@example.org": "deleted"}


def test_delete_account_treats_missing_user_as_absent(monkeypatch):
    def fake_docker(*args, **kwargs):
        raise dta.ThrowawayAccountError("docker exec -i failed: ❌ No user found with email: <email>")

    monkeypatch.setattr(dta, "_docker", fake_docker)
    assert dta.delete_account("devtest-x@example.org") == "absent"


def test_delete_account_reraises_other_failures(monkeypatch):
    def fake_docker(*args, **kwargs):
        raise dta.ThrowawayAccountError("docker exec -i failed: connection refused")

    monkeypatch.setattr(dta, "_docker", fake_docker)
    with pytest.raises(dta.ThrowawayAccountError):
        dta.delete_account("devtest-x@example.org")
