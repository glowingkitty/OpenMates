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
        ai_test_users.main(["run", "--credit-cap", "5000", "--total-cap-usd", "20"])


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
