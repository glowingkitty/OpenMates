# contract-test-file: infrastructure
"""Tooling checks for the AI test-user trial: personas, budget refusal, finding dedup."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ai_test_users  # noqa: E402 - scripts/ is the import root for tooling tests
from ai_test_users_personas import PERSONAS, select  # noqa: E402


def test_personas_are_complete_and_unique():
    ids = [p["id"] for p in PERSONAS]
    assert len(ids) == len(set(ids)) == 10
    for persona in PERSONAS:
        assert persona["goals"] and persona["name"] and persona["device_label"]
        assert {"width", "height"} <= set(persona["device"])
    assert any(p["device"].get("mobile") for p in PERSONAS)
    assert any(not p["device"].get("mobile") for p in PERSONAS)
    assert any(p.get("voice_text") for p in PERSONAS)
    assert any(p.get("locale", "").startswith("de") for p in PERSONAS)


def test_select_rejects_unknown_persona():
    assert [p["id"] for p in select("cook,privacy")] == ["cook", "privacy"]
    with pytest.raises(SystemExit):
        select("cook,astronaut")


def test_run_refuses_caps_above_total_budget(monkeypatch):
    monkeypatch.setattr(ai_test_users.dev_test_account, "server_is_development", lambda: True)
    with pytest.raises(SystemExit, match="above --total-cap-usd"):
        ai_test_users.main(["run", "--harness-cap-usd", "5", "--total-cap-usd", "20"])


def test_similar_titles_merge_but_different_ones_do_not():
    a = "Header controls overlap the top message on mobile"
    b = "Header buttons overlap top message content on mobile view"
    c = "Weather card shows raw ISO date string"
    assert ai_test_users.similar(a, b) >= 0.45
    assert ai_test_users.similar(a, c) < 0.2


def test_slow_replies_and_reviewer_groups_become_one_task_each():
    def finding(fid, title, category="broken_ui", evidence=""):
        return {"id": fid, "title": title, "category": category, "evidence": evidence, "persona": {"persona": fid}}

    findings = [
        finding("a#1", "Reply took 70 s", "slow responses", "waited 72.4s for the reply"),
        finding("b#1", "Header overlaps message on phone"),
        finding("c#1", "Pinned top bar covers user bubble"),
        finding("d#1", "Follow-up latency", "slow", "waited 111.1s"),
        finding("e#1", "Raw i18n key in settings"),
    ]
    clusters = ai_test_users.cluster_findings(findings, ai_test_users.merge_groups("b#1+c#1"))
    assert [[f["id"] for f in c] for c in clusters] == [["b#1", "c#1"], ["a#1", "d#1"], ["e#1"]]
    assert ai_test_users.slow_title(clusters[1]) == "Slow chat replies on dev: 2 test users waited 72-111 s for answers"


def test_run_holds_the_shared_dev_stack_lease_and_releases_it(monkeypatch):
    import types

    calls = []
    fake = types.SimpleNamespace(
        DOCKER_RESOURCE_DEV_STACK="dev-stack",
        acquire_test_resource_lease=lambda lease_id, owner, resources, mode, timeout: calls.append(
            ("acquire", lease_id, frozenset(resources), mode)),
        release_test_resource_lease=lambda lease_id: calls.append(("release", lease_id)),
    )
    monkeypatch.setitem(sys.modules, "sessions", fake)
    with pytest.raises(RuntimeError):
        with ai_test_users.dev_stack_lease("20261120-120000"):
            assert calls == [("acquire", "ai-test-users-20261120-120000", frozenset({"dev-stack"}), "shared")]
            held = ai_test_users.dev_test_lock.holders()
            assert [h["kind"] for h in held.values()] == ["ai-test-users"]
            raise RuntimeError("worker crashed")
    assert calls[-1] == ("release", "ai-test-users-20261120-120000")
    assert ai_test_users.dev_test_lock.holders() == {}


def test_notify_failure_pushes_one_alert_with_the_unit_result(monkeypatch):
    sent = []
    monkeypatch.setattr(ai_test_users.accounts, "_push", lambda message, title: sent.append(message))
    monkeypatch.setattr(ai_test_users, "failure_detail", lambda unit: f"{unit} exit-code 1: RuntimeError: boom")
    assert ai_test_users.main(["notify-failure"]) == 0
    assert len(sent) == 1 and sent[0].startswith("❌") and "boom" in sent[0]


def test_setup_script_wires_the_failure_alert():
    text = (Path(__file__).resolve().parents[1] / "ai-test-users-setup.sh").read_text()
    assert "OnFailure=ai-test-users-failure.service" in text
    assert "ai_test_users.py notify-failure --unit ai-test-users.service" in text
