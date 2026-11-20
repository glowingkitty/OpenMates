# contract-test-file: infrastructure
"""Rotation, accounts, gift cards, prod gate, summary text and daily marker for the AI test users."""

from __future__ import annotations

import os
import stat
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ai_test_users_accounts as accounts  # noqa: E402
import ai_test_users_exec as execution  # noqa: E402
import ai_test_users_report as reporting  # noqa: E402
import ai_test_users_schedule as schedule  # noqa: E402
from ai_test_users_personas import PERSONAS  # noqa: E402

IDS = [p["id"] for p in PERSONAS]
MONDAY = date(2026, 11, 16)


def test_rotation_properties_over_four_weeks():
    for week in range(4):
        start = MONDAY + timedelta(weeks=week)
        dev_seen, prod_seen = set(), set()
        for offset in range(5):
            plan = schedule.personas_for(start + timedelta(days=offset), IDS)
            assert len(plan["dev"]) == 3 and len(plan["prod"]) == 2
            assert not set(plan["dev"]) & set(plan["prod"])
            dev_seen |= set(plan["dev"])
            prod_seen |= set(plan["prod"])
        assert dev_seen == set(IDS) and prod_seen == set(IDS)
        saturday = schedule.personas_for(start + timedelta(days=5), IDS)
        assert saturday["kind"] == "weekly" and saturday["dev"] == IDS and saturday["prod"] == []
        assert schedule.personas_for(start + timedelta(days=6), IDS)["kind"] == "none"


def test_areas_and_persona_texts():
    assert all(p["areas"] for p in PERSONAS)
    plan = schedule.personas_for(MONDAY, IDS)
    areas = schedule.areas_for(plan["dev"] + plan["prod"], PERSONAS)
    assert areas and len(areas) == len(set(areas))


def test_identity_prefix_uniqueness_and_registry_permissions(tmp_path):
    seen = set()
    for _ in range(50):
        identity = accounts.new_identity(tmp_path)
        assert identity["email"].startswith("omtestuser-") and identity["email"].endswith("@inboxkitten.com")
        assert len(identity["email"].split("@")[0]) == len("omtestuser-") + 16
        assert len(identity["password"]) >= 30
        assert identity["email"] not in seen
        seen.add(identity["email"])
        accounts.register_account(identity["email"], "dev", "r1", "cook", base=tmp_path)
    assert len(accounts.registry_entries(tmp_path)) == 50
    assert stat.S_IMODE(os.stat(tmp_path / "accounts.jsonl").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(tmp_path).st_mode) == 0o700
    reused = accounts.registry_entries(tmp_path)[0]["email"]
    assert reused not in {accounts.new_identity(tmp_path)["email"] for _ in range(20)}


def test_password_only_in_secret_file(tmp_path):
    identity = accounts.new_identity(tmp_path)
    accounts.register_account(identity["email"], "dev", "r1", "cook", base=tmp_path)
    accounts.save_secret(identity["email"], identity, tmp_path)
    assert identity["password"] not in (tmp_path / "accounts.jsonl").read_text()
    path = accounts.secret_path(identity["email"], tmp_path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert [e["email"] for e in accounts.pending_deletions(tmp_path)] == [identity["email"]]
    accounts.update_status(identity["email"], "deleted", tmp_path)
    accounts.remove_secret(identity["email"], tmp_path)
    assert not path.exists() and accounts.pending_deletions(tmp_path) == []
    assert len(accounts.registry_entries(tmp_path)) == 2  # history is kept


def test_prod_code_pop_and_low_push_once(tmp_path):
    (tmp_path / accounts.PROD_CODES_FILE).write_text("".join(f"CODE-{i}\n" for i in range(8)))
    sent = []
    for expected_remaining in (7, 6, 5, 4):
        code, remaining = accounts.pop_prod_code(tmp_path)
        assert remaining == expected_remaining
        accounts.notify_low_codes(remaining, lambda msg, title: sent.append(msg), tmp_path)
    assert code == "CODE-3" and len(sent) == 1 and sent[0].startswith("❓")
    assert "CODE-0" in (tmp_path / (accounts.PROD_CODES_FILE + ".used")).read_text()
    (tmp_path / accounts.PROD_CODES_FILE).write_text("A\n" * 20)
    accounts.notify_low_codes(20, lambda *a: sent.append("x"), tmp_path)  # refill clears the marker
    accounts.notify_low_codes(3, lambda msg, title: sent.append(msg), tmp_path)
    assert len(sent) == 2


def test_pop_without_file_or_empty(tmp_path):
    assert accounts.pop_prod_code(tmp_path) == (None, 0)
    (tmp_path / accounts.PROD_CODES_FILE).write_text("")
    assert accounts.pop_prod_code(tmp_path) == (None, 0)


def test_prod_gate(tmp_path):
    assert execution.gate("prod", tmp_path) == ("prod_disabled", {})
    (tmp_path / accounts.PROD_ENABLED_FILE).write_text("")
    assert execution.gate("prod", tmp_path) == ("no_gift_card", {})
    (tmp_path / accounts.PROD_CODES_FILE).write_text("AAAA-BBBB-CCCC\n" * 9)
    status, extras = execution.gate("prod", tmp_path)
    assert status is None and extras["gift_card_code"] == "AAAA-BBBB-CCCC"


def test_run_persona_prod_disabled_never_creates_account(tmp_path, monkeypatch):
    monkeypatch.setattr(execution.e2b_dev_capacity, "budget_exhausted", lambda: None)
    cfg = execution.Settings(base=tmp_path)
    result = execution.run_persona(PERSONAS[0], "prod", "r1", tmp_path, cfg)
    assert result["status"] == "prod_disabled" and accounts.registry_entries(tmp_path) == []


def test_summary_text_limits_and_marker(tmp_path):
    results = [{"status": "ok", "findings_kept": 2,
                "reports": [{"short_issue_id": f"ABC2{i}"} for i in range(8)]}]
    text = reporting.summary_text("daily", "2026-11-16", results, ["maps"])
    assert text.startswith("✅") and text.count(". ") <= 2
    assert sum(1 for i in range(8) if f"ABC2{i}" in text) == 5 and "+3 more" in text
    quiet = reporting.summary_text("weekly", "2026-11-21", [{"status": "ok"}], ["maps", "jobs"])
    assert "Weekly" in quiet and "Areas: maps, jobs" in quiet
    assert reporting.push_due(tmp_path, "2026-11-16")
    reporting.mark_pushed(tmp_path, "2026-11-16")
    assert not reporting.push_due(tmp_path, "2026-11-16") and reporting.push_due(tmp_path, "2026-11-17")


def test_caps():
    reporting.check_cap("daily", 5, 0.2, 0.1)
    with pytest.raises(SystemExit):
        reporting.check_cap("daily", 5, 0.5, 0.2)  # 3.5 USD
    reporting.check_cap("weekly", 10, 0.4, 0.2)
    with pytest.raises(SystemExit):
        reporting.check_cap("weekly", 10, 0.5, 0.2)  # 7 USD


def _printenv(values):
    return lambda name: values.get(name, "")


def test_signup_mailbox_uses_inbox_kitten_where_the_server_admits_it():
    assert accounts.signup_mailbox("prod") == ("inboxkitten.com", "inboxkitten")
    assert accounts.signup_mailbox("dev", _printenv({})) == ("inboxkitten.com", "inboxkitten")
    allowed = {"SIGNUP_DOMAIN_RESTRICTION": "openmates.org", "SIGNUP_TEST_EMAIL_DOMAINS": "test.example,inboxkitten.com"}
    assert accounts.signup_mailbox("dev", _printenv(allowed)) == ("inboxkitten.com", "inboxkitten")


def test_signup_mailbox_falls_back_to_the_dev_cache_on_a_restricted_dev():
    restricted = {"SIGNUP_DOMAIN_RESTRICTION": "openmates.org", "SIGNUP_TEST_EMAIL_DOMAINS": "@Test.Example, other.example"}
    assert accounts.signup_mailbox("dev", _printenv(restricted)) == ("test.example", "dev_cache")
    with pytest.raises(RuntimeError):
        accounts.signup_mailbox("dev", _printenv({"SIGNUP_DOMAIN_RESTRICTION": "openmates.org"}))


def test_new_identity_keeps_the_fixed_prefix_on_any_domain(tmp_path):
    identity = accounts.new_identity(tmp_path, "test.example")
    assert identity["email"].startswith(accounts.EMAIL_PREFIX) and identity["email"].endswith("@test.example")
    assert len(identity["username"]) < 20


def test_dev_gift_card_codes_match_the_web_deep_link_format():
    import re

    pattern = re.compile(r"^[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$")
    assert all(pattern.match(accounts._random_code()) for _ in range(200))
