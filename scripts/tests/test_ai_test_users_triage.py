# contract-test-file: infrastructure
"""Owner, 23 Nov 2026: clear functional errors start a debugging chat by themselves, subjective findings
wait for Marco's approval, and an open Task or chat covering the issue is linked instead of a duplicate."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ai_test_users_triage as triage  # noqa: E402

ISSUE_ID = "4bc37539-8082-4fef-9adf-65728500063d"


def finding(title: str, category: str = "", evidence: str = "", **extra) -> dict:
    return {"title": title, "category": category, "evidence": evidence, "kept": True, **extra}


# contract-test: supporting surface=cli assertions=ai-test-users.debug.functional-errors-start-chats
def test_functional_errors_start_chats_and_subjective_findings_wait_for_approval():
    auto = [
        finding("Raw JSON payload leaked into user message bubble", "unreadable data"),
        finding("Long message sending hangs indefinitely with Tiptap RangeError", "slow responses",
                "waited 120.5s for the reply (settled=False); console warning: RangeError: Unknown node type: listItem"),
        finding("Weather card shows code", "wrong data", 'bubble shows {"skill_id":"search"} instead of the embed'),
        finding("Message not sent", "odd UI", "Failed to send: the message stays grey"),
        finding("App crashed after opening settings", "error messages or crashes"),
    ]
    approval = [
        finding("Sticky top bar overlaps user message text", "broken, overlapping, cut-off or odd UI, also on phone size",
                "the floating top bar is obscuring the text"),
        finding("Recipe card title awkwardly split and wrapped", "broken, overlapping, cut-off or odd UI"),
        finding("Redundant English prefix in markdown citation link", "odd_ui", "sind laut according to mdr.de"),
        finding("Answers are slow", "slow responses", "waited 41 s, then the answer arrived"),
        finding("Raw JSON shown", "unreadable data", suspect="api restarted at 06:40 UTC"),
    ]
    assert [triage.route(f)[0] for f in auto] == ["auto"] * len(auto)
    assert [triage.route(f)[0] for f in approval] == ["approval"] * len(approval)
    assert triage.route(approval[-1])[1] == "may be the environment (api restarted at 06:40 UTC)"


def run(findings: list[dict], target: str = "dev", short: str = "S6BEV") -> dict:
    return {"persona": "job_seeker", "target": target, "status": "persona_finished", "findings": findings,
            "reports": [{"short_issue_id": short, "finding_ids": [0], "status": "submitted"}]}


# contract-test: supporting surface=cli assertions=ai-test-users.debug.no-duplicate-chats
def test_an_open_task_running_chat_or_recent_debug_chat_is_linked_instead_of_a_new_chat(tmp_path, monkeypatch):
    raw = run([finding("Raw JSON payload leaked into user message bubble", "unreadable data")])
    launched = []

    def launch(issue_id, short_id, env):
        launched.append(short_id)
        return {"status": "started", "chat_title": f"AI test user issue {short_id}: investigate"}

    monkeypatch.setattr(triage, "start_chat", lambda issue, launch_fn=None: launch(ISSUE_ID, issue["short_issue_id"],
                                                                                  issue["env"]))
    task = {"short_id": "TASK-2861", "title": "Web: Apps result follow-up shows raw JSON (issue S6BEV)"}
    [issue] = triage.triage([raw], tmp_path, dispatch=True, tasks=[task], chats=[])
    assert issue["debug"] == {"route": "auto", "why": "functional error", "status": "covered",
                              "covered_by": "open Task TASK-2861"}
    chat = {"chat": "01ec699c-d04a", "last_prompt": "fix it", "sessions": [{"task": "Raw JSON payload leaked into "
                                                                                     "the user message bubble"}]}
    [issue] = triage.triage([raw], tmp_path, dispatch=True, tasks=[], chats=[chat])
    assert issue["debug"]["covered_by"] == "running chat 01ec699c"
    assert launched == []
    [issue] = triage.triage([raw], tmp_path, dispatch=True, tasks=[], chats=[])
    assert issue["debug"]["status"] == "started" and launched == ["S6BEV"]
    again = run([finding("Raw JSON payload leaked into the user message bubble", "unreadable data")], short="QQ11A")
    [issue] = triage.triage([again], tmp_path, dispatch=True, tasks=[], chats=[])
    assert issue["debug"]["status"] == "covered" and "AI test user issue S6BEV" in issue["debug"]["covered_by"]
    assert launched == ["S6BEV"]


# contract-test: supporting surface=cli assertions=ai-test-users.debug.no-duplicate-chats,ai-test-users.debug.functional-errors-start-chats
def test_no_chat_starts_when_open_tasks_cannot_be_checked_or_for_approval_items(tmp_path):
    raw = run([finding("Raw JSON payload leaked into user message bubble", "unreadable data")])
    [issue] = triage.triage([raw], tmp_path, dispatch=True, tasks=None, chats=[])
    assert issue["debug"]["status"] == "failed" and "could not be checked" in issue["debug"]["note"]
    sticky = run([finding("Recipe card title awkwardly split", "odd UI")], target="prod", short="25EFC")
    [issue] = triage.triage([sticky], tmp_path, dispatch=True, tasks=[], chats=[])
    assert issue["env"] == "prod" and issue["debug"]["status"] == "approval"


def test_dropped_findings_are_not_issues():
    dropped = run([finding("Sounds are on tip covers header", "odd UI") | {"kept": False}])
    assert triage.triage([dropped], None, dispatch=False) == []
