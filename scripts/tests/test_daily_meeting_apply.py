# contract-test-file: tooling
"""Structured decisions-note tables: parsing, resolving, planning and verification."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import daily_meeting_apply as apply  # noqa: E402

NOTE = """DECISIONS 2026-11-09
Check-in: progress 3, energy 2; did: x; priorities: y
Focus tasks:
1. Send the email (done when: sent)
Reminder changes:
| Action | Reminder (exact title) | List | New due | New title | Notes |
|---|---|---|---|---|---|
| move | Buy nose strips | OpenMates | 2026-11-09 13:15 | | |
| done | Book trip back from Munich | | | | |
| delete | Design onesie pattern | | | | |
| create | Cancel the webinar | Personal Tasks | 2026-11-09 17:30 | | |
| move | Call the journalist | | 2026-11-10 | | |
| move | Nothing like this | | 2026-11-10 10:00 | | |
| update | Blog posts (Jugend hackt, privacy, other landingpage blog posts) | | | Blog posts (privacy) | write on the bus |
Task changes:
| Action | Task (exact title) | New title | Priority | Status | Label | Due | Description |
|---|---|---|---|---|---|---|---|
| edit | Fix the PDF upload | | high | | milestone:money | | |
| done | Old task | | | | | | |
| create | Review the archives | | high | todo | | 2026-11-11 | plain words |
| edit | Third task | | | | | 2026-11-12 | |
Goals:
| Level | Item | Action |
|---|---|---|
| milestone | First paying customer | add |
Meeting:
- shorten block 6 -> adopt
"""

ITEMS = [
    {"id": "r1", "title": "Buy nose strips", "list": "OpenMates", "due": "2026-11-09T10:00:00Z"},
    {"id": "r2", "title": "Book trip back from Munich", "list": "OpenMates", "due": None},
    {"id": "r3", "title": "Design onesie pattern (14 day free trial)", "list": "Personal Tasks", "due": None},
    {"id": "r4", "title": "Call the journalist", "list": "OpenMates", "due": None},
    {"id": "r5", "title": "Blog posts (Jugend hackt, privacy, other landingpage blog posts)", "list": "OpenMates", "due": None},
]
TASKS = [{"task_id": "t1", "title": "Fix the PDF upload", "status": "todo", "priority_level": "none", "labels": []},
         {"task_id": "t2", "title": "Old task", "status": "todo", "priority_level": "low", "labels": []},
         {"task_id": "t4", "title": "Third task", "status": "todo", "priority_level": "low", "labels": []}]


def test_parse_tables_and_manual_sections():
    sections = apply.parse_sections(NOTE)
    assert len(apply.reminder_rows(sections)) == 7 and len(apply.task_rows(sections)) == 4
    assert len(sections["goals"]) == 3 and sections["meeting"] == ["- shorten block 6 -> adopt"]


def test_legacy_lines_still_parse():
    sections = apply.parse_sections('DECISIONS 2026-11-04\nReminders:\n- "Buy nose strips" -> move 2026-11-09 13:15\n'
                                    '- "Old" -> done\nNew reminders:\n- "New one" (OpenMates, 2026-11-10 09:00)\n')
    rows = apply.reminder_rows(sections)
    assert [r["action"] for r in rows] == ["move", "done", "create"] and rows[0]["due"] == "2026-11-09 13:15"


def test_reminder_plan_flags_every_problem_instead_of_skipping():
    rows = apply.reminder_rows(apply.parse_sections(NOTE))
    plan = apply.plan_reminders(rows, ITEMS)
    status = [e["status"] for e in plan]
    assert status == ["ready", "ready", "ready", "ready", "attention", "attention", "ready"]
    assert "time" in plan[4]["reason"] and "no unique match" in plan[5]["reason"]
    assert plan[2]["ops"] == [{"action": "delete", "id": "r3"}]  # unique prefix of a longer title
    assert plan[6]["ops"][0]["id"] == "r5" and plan[6]["ops"][0]["title"] == "Blog posts (privacy)"


def test_verification_compares_live_data():
    plan = apply.plan_reminders(apply.reminder_rows(apply.parse_sections(NOTE)), ITEMS)
    after = [dict(ITEMS[0], due="2026-11-09T12:15:00Z"), ITEMS[3],
             dict(ITEMS[4], title="Blog posts (privacy)", notes="write on the bus"),
             {"id": "n", "title": "Cancel the webinar", "list": "Personal Tasks", "due": "2026-11-09T16:30:00Z"}]
    assert [apply.verify_reminder(e, after) for e in plan if e["status"] == "ready"] == ["", "", "", "", ""]
    assert "still open" in apply.verify_reminder(plan[1], ITEMS)
    assert "due is" in apply.verify_reminder(plan[0], ITEMS)


def test_task_plan_and_verification():
    plan = apply.plan_tasks(apply.task_rows(apply.parse_sections(NOTE)), TASKS)
    assert [e["status"] for e in plan] == ["ready", "ready", "ready", "ready"]
    assert plan[0]["cmds"] == [["edit", "t1", "--priority", "high", "--add-label", "milestone:money"]]
    created_due, edited_due = 1794355200, 1794441600  # 2026-11-11 and 2026-11-12 at 00:00 UTC
    assert plan[1]["cmds"] == [["done", "t2"]] and plan[2]["cmds"][0][-2:] == ["--due", str(created_due)]
    assert plan[3]["cmds"] == [["edit", "t4", "--due", str(edited_due)]]
    after = [dict(TASKS[0], priority_level="high", labels=["milestone:money"]), dict(TASKS[1], status="done"),
             {"task_id": "t3", "title": "Review the archives", "status": "todo", "priority_level": "high", "labels": [],
              "due_at": created_due}, dict(TASKS[2], due_at=edited_due)]
    assert [apply.verify_task(e, after) for e in plan] == ["", "", "", ""]
    assert "priority_level" in apply.verify_task(plan[0], TASKS)
    assert "due date is empty" in apply.verify_task(plan[3], TASKS)
    assert "another due date" in apply.verify_task(plan[2], [dict(after[2], due_at=None)])


def test_task_due_is_berlin_time_and_a_bad_due_needs_attention():
    assert apply.task_due_epoch("2026-11-11 16:00") == 1794355200 + 15 * 3600  # 16:00 Berlin is 15:00 UTC
    assert apply.task_due_epoch("2026-11-11") == 1794355200 and apply.task_due_epoch("next week") is None
    row = {"action": "edit", "title": "Third task", "new_title": "", "priority": "", "status": "", "label": "",
           "due": "tomorrow", "description": "", "assign": ""}
    bad = apply.plan_tasks([row], TASKS)[0]
    assert bad["status"] == "attention" and "YYYY-MM-DD" in bad["reason"] and not bad["cmds"]


def test_report_marks_unverified_rows_and_lists_manual_sections():
    plan = apply.plan_reminders(apply.reminder_rows(apply.parse_sections(NOTE)), ITEMS)
    verdicts = {("Reminder", 1): "", ("Reminder", 2): "still open on the Mac"}
    text, bad = apply.report(plan, verdicts, {"goals": 4, "meeting": 1, "chats": 0})
    assert "FAILED: still open" in text and "NEEDS ATTENTION" in text and "Manual steps" in text and bad == 3
