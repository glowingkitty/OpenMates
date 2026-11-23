# contract-test-file: tooling
"""Dev-host calendar, authenticated submission receipts and private reflection handoff."""

from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import daily_meeting_accountability as accountability  # noqa: E402 - scripts dir added above
import daily_meeting_briefing as briefing  # noqa: E402 - scripts dir added above
import daily_meeting_morning as morning  # noqa: E402 - scripts dir added above
import daily_meeting_reflection as reflection  # noqa: E402 - scripts dir added above

TUESDAY = date(2026, 11, 24)
MONDAY = TUESDAY - timedelta(days=1)


def local(day, hour, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=accountability.TZ)


def connector_receipt(audit, submitted, note, *, session="owner", ok=True):
    with audit.open("a") as handle:
        handle.write(json.dumps({"ts": submitted.isoformat(), "verb": "submit_decisions",
                                 "session": session, "ok": ok, "args": {"note": note}}) + "\n")


def test_first_night_reminder_start_weekend_and_summer():
    assert accountability.slots(local(MONDAY, 11)) == []
    assert accountability.slots(local(MONDAY, 22)) == ["evening"]
    assert accountability.slots(local(TUESDAY, 8, 30)) == ["briefing"]
    assert accountability.slots(local(TUESDAY, 10, 30)) == []
    assert accountability.slots(local(TUESDAY, 11)) == ["reminder"]
    assert accountability.slots(local(TUESDAY, 11, 30)) == ["reminder"]
    assert accountability.slots(local(TUESDAY, 11, 35)) == []
    assert accountability.slots(local(TUESDAY, 22)) == ["evening", "reminder"]
    assert accountability.slots(local(date(2026, 11, 28), 22)) == []
    assert accountability.slots(datetime.fromisoformat("2027-07-27T09:00:00+00:00")
                                .astimezone(accountability.TZ)) == ["reminder"]
    samples = [accountability.reminder(local(TUESDAY, 11 + i // 2, i % 2 * 30)) for i in range(8)]
    assert len(set(samples)) == 8
    assert all(len(sample) < 110 for sample in samples)


def test_today_is_required_in_both_the_receipt_and_note(tmp_path):
    audit = tmp_path / "audit"
    expected = f"DECISIONS {TUESDAY}\nFocus: first working demo"
    connector_receipt(audit, local(MONDAY, 23, 59), expected)
    connector_receipt(audit, local(TUESDAY, 9), f"DECISIONS {MONDAY}\nFocus: old")
    connector_receipt(audit, local(TUESDAY, 9), expected, ok=False)
    connector_receipt(audit, local(TUESDAY, 9), expected, session="")
    connector_receipt(audit, local(TUESDAY, 9), f"DECISIONS {TUESDAY}")
    assert not accountability.submitted_decisions(tmp_path, audit, TUESDAY)
    connector_receipt(audit, local(TUESDAY, 0, 1), expected)
    with audit.open("a") as handle:
        handle.write('{"verb": "submit_decisions"')
    assert accountability.submitted_decisions(tmp_path, audit, TUESDAY) == expected
    (tmp_path / f"{TUESDAY}-decisions.md").write_text(expected)
    assert accountability.submitted_decisions(tmp_path, tmp_path / "missing", TUESDAY) == expected


def test_dispatch_deduplicates_and_stops_in_next_slot(tmp_path, monkeypatch):
    audit = tmp_path / "audit"
    monkeypatch.setattr(accountability, "audit_path", lambda _: audit)
    delivered = []

    def post(root, message):
        delivered.append(message)
        return {"message_id": str(len(delivered))}

    monkeypatch.setattr(briefing, "post_discord", post)
    assert accountability.dispatch(tmp_path, local(TUESDAY, 11)) == 0
    assert accountability.dispatch(tmp_path, local(TUESDAY, 11, 1)) == 0
    assert len(delivered) == 1
    connector_receipt(audit, local(TUESDAY, 11, 12), f"DECISIONS {TUESDAY}\nFocus: first working demo")
    assert accountability.dispatch(tmp_path, local(TUESDAY, 11, 30)) == 0
    assert len(delivered) == 1


def test_failed_evening_push_can_retry_and_does_not_affect_reminders(tmp_path, monkeypatch):
    monkeypatch.setattr(reflection, "configured_task", lambda **_: "reply-task")
    deliveries = []

    def post(root, message):
        deliveries.append(message)
        if len(deliveries) == 1:
            raise RuntimeError("Discord timed out")
        return {"message_id": str(len(deliveries))}

    monkeypatch.setattr(briefing, "post_discord", post)
    assert accountability.dispatch(tmp_path, local(TUESDAY, 22)) == 1
    assert accountability.dispatch(tmp_path, local(TUESDAY, 22, 1)) == 0
    assert len(deliveries) == 3
    assert deliveries[0] == deliveries[2]
    assert "#task-id=reply-task" in deliveries[2]


def test_evening_reply_skips_deleted_bot_and_outside_window():
    monday = date(2026, 11, 30)
    start = reflection.previous_evening(monday)
    assert start == local(date(2026, 11, 27), 22)

    def comment(minutes, text, **changes):
        return {"kind": "comment", "actor_type": "user", "message": text,
                "created_at": int((start + timedelta(minutes=minutes)).timestamp()), **changes}

    entries = [
        comment(-10, "before the prompt"),
        comment(5, "a first draft"),
        comment(8, "the useful reflection"),
        comment(9, "deleted", deleted_at=1),
        comment(10, "agent", actor_type="agent"),
        comment(4000, "after briefing started"),
    ]
    assert reflection.latest_reply(entries, start, local(monday, 8, 30)) == "the useful reflection"


def test_morning_uses_yesterdays_sources_and_reuses_private_reply(tmp_path, monkeypatch):
    out = tmp_path / "logs/daily-meetings"
    out.mkdir(parents=True)
    (out / f"{MONDAY}-decisions.md").write_text(
        f"DECISIONS {MONDAY}\nFocus: onboarding\nFocus tasks:\n1. Fix the onboarding demo\n")
    monkeypatch.setattr(morning, "read_reflection", lambda *_: {
        "day": str(MONDAY), "text": "Demo went well. The follow-up slipped.", "unavailable": False})
    evidence = {
        "git": {"commits_on_dev": [{"subject": "Onboarding fix", "day": str(MONDAY)},
                                   {"subject": "This morning only", "day": str(TUESDAY)}]},
        "claude_chats": [{"title": "New demo chat", "active_days": [str(MONDAY), str(TUESDAY)]}],
        "tasks": {"done_since_last_meeting": [{"title": "Finish demo", "updated_at": local(MONDAY, 15).timestamp()}]},
        "focus_file": "# Focus\n\n## Current priorities\n- onboarding: signup, activation\n"}
    result = "\n".join(morning.render(morning.collect(tmp_path, out, evidence, local(TUESDAY, 8, 30))))
    for expected in ("Onboarding fix", "New demo chat", "Finish demo", "Fix the onboarding demo",
                     "Today’s priorities", "Mood check", "Founder’s nudge", "The follow-up slipped"):
        assert expected in result
    assert "This morning only" not in result
