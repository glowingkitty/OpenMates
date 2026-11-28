# contract-test-file: infrastructure
"""The one Discord message per AI test-user run: summary lines, causes, verdicts, suspect marks."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ai_test_users_accounts as accounts  # noqa: E402
import ai_test_users_message as message_text  # noqa: E402

URL = "https://nbg1.example.org/openmates-ai-test-user-videos/key.webm?X-Amz-Signature=abc"
START = 1_800_000_000.0


def persona(name: str, findings: list[dict], target: str = "dev", **extra) -> dict:
    return {"persona": name, "target": target, "status": "persona_finished", "video": {"url": URL, "key": "k"},
            "started_at": START, "finished_at": START + 600, "findings": findings, "reports": [], **extra}


def finding(title: str, kept: bool = True, at: float = 100.0, video_seconds: float = 61.0) -> dict:
    return {"title": title, "kept": kept, "at_epoch": START + at, "video_seconds": video_seconds}


# contract-test: supporting surface=cli assertions=ai-test-users.message.dev-production-issues
def test_message_separates_dev_and_production_issues_with_their_debug_status():
    """Owner, 23 Nov 2026: a run that filed issues never reads as clean; each issue shows its title alone,
    its environment and whether a debugging chat started or it waits for approval."""
    cook = persona("cook", [finding("Chat answer never arrives after Send") | {"category": "error messages or crashes"},
                            finding("Sounds are on tip covers header", kept=False)],
                   reports=[{"short_issue_id": "AB12C", "finding_ids": [0], "status": "submitted"}])
    german = persona("german", [finding("Chat answer never arrives after pressing Send", video_seconds=95.0)
                                | {"category": "error messages or crashes"}])
    chef = persona("chef", [finding("Recipe card title wraps oddly") | {"category": "odd UI"}], target="prod",
                   reports=[{"short_issue_id": "ZZ99Y", "finding_ids": [0], "status": "submitted"}])
    text = message_text.run_message("AI test users daily run 2026-11-23", [cook, german, chef], [])
    lines = text.splitlines()
    assert lines[0] == ("❌ AI test users daily run 2026-11-23: 3 personas ran, 1 DEV and 1 PRODUCTION issues; "
                        "0 debug chats started, 1 waiting for your approval.")
    assert lines[1] == "1 finding dropped as not a bug (report.md)."
    assert "No run problems" not in text
    assert lines[2] == "## DEV issues (1)"
    assert lines[3] == "**Chat answer never arrives after Send**"
    assert lines[4] == (f"DEV · debug chat would start (dry run, not started) · report AB12C · 2× (cook, german) · "
                        f"[video 1:01](<{URL}#t=61>)")
    assert lines[5] == "## PRODUCTION issues (1)"
    assert lines[6] == "**Recipe card title wraps oddly**"
    assert lines[7].startswith("PRODUCTION · waiting for your approval, looks subjective (UI, design or wording) · "
                               "report ZZ99Y")
    payload = message_text.discord_payload(text)
    assert [e["title"] for e in payload["embeds"]] == ["DEV issues (1)", "PRODUCTION issues (1)"]


# contract-test: supporting surface=cli assertions=ai-test-users.message.dev-production-issues
def test_started_covered_and_deferred_chats_are_named_in_the_message():
    issue = {"env": "dev", "title": "Composer hangs", "short_issue_id": "AB12C",
             "group": {"members": [{"result": persona("cook", []), "finding": finding("Composer hangs"),
                                    "report": "AB12C"}]}}
    started = message_text.issue_lines(issue | {"debug": {"status": "started",
                                                          "chat_title": "AI test user issue AB12C: investigate"}})
    assert started[1].startswith("DEV · debug chat started: AI test user issue AB12C: investigate · report AB12C")
    covered = message_text.issue_lines(issue | {"debug": {"status": "covered", "covered_by": "open Task TASK-2861"}})
    assert "no new chat, already covered by open Task TASK-2861" in covered[1]
    deferred = message_text.issue_lines(issue | {"debug": {"status": "deferred", "note": "daily cap of 3 automatic chats reached"}})
    assert "no debug chat yet: daily cap of 3 automatic chats reached" in deferred[1]
    second = issue | {"title": "Send button does nothing", "debug": {"status": "started", "chat_title": "c"}}
    text = message_text.run_message("run", [persona("cook", [])], [], issues=[
        issue | {"debug": {"status": "covered", "covered_by": "open Task TASK-2861"}}, second])
    assert "0 debug chats started" not in text and "1 debug chat started, 1 already covered by an open Task or chat, " \
        "0 waiting for your approval." in text
    assert "](<" not in message_text.discord_payload(text)["embeds"][0]["description"]
    assert "\n\n**Send button does nothing**" in message_text.discord_payload(text)["embeds"][0]["description"]


def test_restart_or_deploy_before_a_finding_makes_it_suspect():
    events = [{"at": START + 50, "what": "api restarted at 08:53 UTC"},
              {"at": START + 400, "what": "dev deploy abc1234 at 08:59 UTC"}]
    early = finding("Server error: Embed not found", at=60)
    before = finding("Composer stays disabled", at=10)  # restart 40 s later, beyond the slack
    dev = persona("traveller", [early, before])
    prod = persona("student", [finding("Server error: Embed not found", at=60)], target="prod")
    message_text.mark_suspects([dev, prod], events=lambda start, end: events, base=Path("/nonexistent"))
    assert early["suspect"] == "api restarted at 08:53 UTC"
    assert "suspect" not in before
    assert "suspect" not in prod["findings"][0], "prod deploys are not visible from the dev host"
    line = message_text.run_message("run", [dev], [])
    assert "**Server error: Embed not found**\nDEV · waiting for your approval, may be the environment " \
           "(api restarted at 08:53 UTC)" in line


def test_account_deleted_by_another_process_during_the_run_makes_findings_suspect(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    email = "omtestuser-0000@example.org"
    accounts.register_account(email, "dev", "r1", "cook", "created", tmp_path)
    monkeypatch.setattr(accounts, "datetime", type("Clock", (), {
        "now": staticmethod(lambda tz=None: datetime.fromtimestamp(START + 300, UTC))}))
    accounts.update_status(email, "deleted", tmp_path)
    cook = persona("cook", [finding("Signed out while chatting")], email=email)
    message_text.mark_suspects([cook], events=lambda start, end: [], base=tmp_path)
    assert cook["findings"][0]["suspect"].startswith("test account deleted at ")


def test_problems_and_flows_turn_the_message_into_an_alert():
    flows = {"a_fosdem_chat": {"verdict": "broken", "passed": 0, "runs": 2}}
    text = message_text.run_message("intro-video on prod", [], ["1 test account not deleted"], flows)
    first, second = text.splitlines()[:2]
    assert first.startswith("❌") and second == ("Flows: a broken 0/2. Harness problems: 1 test account not deleted. "
                                                "0 findings dropped as not a bug (report.md).")


def test_long_run_message_goes_out_as_one_discord_message_with_embeds():
    long_url = "https://nbg1.example.org/v.webm?" + "X" * 380
    words = ("composer sidebar billing voice upload search maps travel invoice login export camera "
             "calendar weather").split()
    results = [persona(f"p{i}", [finding(f"{word.title()} {word}panel {word}button broken")], video={"url": long_url})
               for i, word in enumerate(words)]
    problems = [f"prod/p{i} goal not met (did not finish) [video](<{long_url}>)" for i in range(5)]
    text = message_text.run_message("intro-video on prod", results, problems)
    second = text.splitlines()[1]
    assert "video" not in second and "(+2 more in report.md)" in second
    payload = message_text.discord_payload(text)
    assert payload["content"] == "\n".join(text.splitlines()[:2]) and len(payload["content"]) <= 2000
    descriptions = [e["description"] for e in payload["embeds"]]
    assert all(len(d) <= 4096 for d in descriptions) and sum(map(len, descriptions)) <= 6000
    assert len(payload["embeds"]) <= 10 and descriptions[-1].endswith("more lines in report.md)")
    sent = []
    message_text.push(text, post=lambda **kw: sent.append(kw) or {"message_id": "1"}, sleep=lambda s: None)
    assert len(sent) == 1 and sent[0]["payload"] == payload
    assert "](<" not in descriptions[0] and f"]({long_url}#t=61)" in descriptions[0]


# contract-test: supporting surface=cli assertions=ai-test-users.message.dev-production-issues
def test_clean_run_message_says_so_in_both_sections():
    payload = message_text.discord_payload(message_text.run_message("run", [], []))
    assert payload["content"].startswith("✅ run: 0 personas ran, 0 DEV and 0 PRODUCTION issues")
    assert [e["description"] for e in payload["embeds"]] == ["none", "none"]
