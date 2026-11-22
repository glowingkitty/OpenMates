# contract-test-file: tooling
"""Waiting chats are never stopped as idle and are woken or reopened when the wait ends (TASK-662).

Regression: on 2026-11-15 chat d2a774d9 parked its CI step on a disk-coordinator wait; the
lifecycle stopped it as idle after 64 min and nothing reopened it when the disk was cleaned.

Run: python3 -m pytest scripts/tests/test_claude_chat_waiters.py
"""

import json
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import claude_chat_waiters as cw  # noqa: E402  (path set above)
import claude_idle_chats as lc  # noqa: E402
import disk_coordinator_state as state  # noqa: E402

NOW = 1_800_000_000.0
HOUR = 3600
CHAT = "d2a774d9-9ed9-54e0-b82b-55445d6a0b5e"
OTHER = "b00dd345-c472-59f6-82b4-81f6cff07f48"
CONFIG = dict(lc.DEFAULTS)
MCP = ["npm exec @remotion/mcp@latest"]


def chat(**overrides) -> lc.Chat:
    values = dict(pid=1, session_id=CHAT, name="openmates-d2", status="idle", kind="pane", pane_id="7",
                  zellij_session="claude", last_activity=NOW - 64 * 60, children=list(MCP),
                  last_speaker="assistant", last_text="Parked: the CI rerun waits on disk space. It notifies me.")
    values.update(overrides)
    return lc.Chat(**values)


def ledger(path: Path, rows) -> Path:
    """rows: (id, thread, operation, state, reason, created_at, updated_at)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS requests (id TEXT, thread TEXT, operation TEXT, state TEXT, "
                     "reason TEXT, created_at REAL, updated_at REAL)")
        conn.execute("DELETE FROM requests")
        conn.executemany("INSERT INTO requests VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    return path


def disk_wait(ready=False, created=NOW - HOUR, request_id="1f81b951aaaa", thread=CHAT):
    reason = state.PARKED_READY_REASON if ready else "Waiting for disk capacity: 9 additional bytes needed"
    return (request_id, thread, "ci-source:fe65", "waiting", reason, created, created)


def sources(tmp_path: Path, rows=(), sessions=None) -> cw.Sources:
    return cw.Sources(root=tmp_path, state=tmp_path / "state", ledger=ledger(tmp_path / "ledger.sqlite3", rows),
                      sessions=sessions or {})


# ---------------------------------------------------------------------------
# 1) A chat with a waiter is never stopped as idle; a timed-out waiter is stalled.
# ---------------------------------------------------------------------------


def test_the_d2a774d9_case_a_parked_disk_wait_keeps_the_idle_chat_running(tmp_path):
    found = cw.collect(sources(tmp_path, [disk_wait()]), NOW)
    target = chat(waiters=found[CHAT])
    assert lc.decide(chat(), NOW, CONFIG, "other").action == "continue"  # stopped on 2026-11-15; woken since TASK-7707
    decision = lc.decide(target, NOW, CONFIG, "other")
    assert decision.action == "keep" and decision.hard
    assert "waits on disk: disk space for ci-source:fe65" in decision.reason
    assert not lc.cap_victims([target] * 25, NOW, CONFIG, "other")


def test_a_waiter_past_its_timeout_is_stalled_and_no_longer_blocks_idle_stop(tmp_path):
    found = cw.collect(sources(tmp_path, [disk_wait(created=NOW - 7 * HOUR)]), NOW)
    (waiter,) = found[CHAT]
    assert waiter.stalled(NOW) and "STALLED" in waiter.label(NOW)
    assert lc.decide(chat(waiters=[waiter]), NOW, CONFIG, "other").action == "stop"
    (entry,) = cw.stalled_entries(found, {}, {}, NOW)
    assert entry["session_id"] == CHAT and entry["reason"].startswith("waiter timed out: disk:")


def test_a_ready_waiter_keeps_the_chat_even_after_its_timeout(tmp_path):
    found = cw.collect(sources(tmp_path, [disk_wait(ready=True, created=NOW - 7 * HOUR)]), NOW)
    assert found[CHAT][0].ready and not found[CHAT][0].stalled(NOW)
    assert lc.decide(chat(waiters=found[CHAT]), NOW, CONFIG, "other").action == "keep"


def test_disk_waits_superseded_by_a_later_granted_request_or_older_than_a_day_do_not_count(tmp_path):
    rows = [disk_wait(created=NOW - 3 * HOUR, request_id="old-left-over"),
            ("later", CHAT, "ci-result:x", "complete", "", NOW - 2 * HOUR, NOW - 2 * HOUR),
            disk_wait(created=NOW - 25 * HOUR, request_id="expired", thread=OTHER),
            disk_wait(created=NOW - HOUR, request_id="current")]
    found = cw.collect(sources(tmp_path, rows), NOW)
    assert [w.key for w in found[CHAT]] == ["disk:current"] and OTHER not in found


# ---------------------------------------------------------------------------
# 2) When the wait ends the chat is woken: typed into a live pane, reopened when closed.
# ---------------------------------------------------------------------------


class Recorder:
    def __init__(self, typed_ok=True, resume_outcome="ok"):
        self.typed, self.resumed, self.events = [], [], []
        self.typed_ok, self.resume_outcome = typed_ok, resume_outcome

    def type_into(self, target, text):
        self.typed.append((target.session_id, text))
        return self.typed_ok

    def resume(self, chat_id, text):
        self.resumed.append((chat_id, text))
        return self.resume_outcome

    def run(self, found, live, registry, directory, room=5, now=NOW, asks=lambda c: False):
        return cw.deliver(found, live, registry, directory, now, type_into=self.type_into, resume=self.resume,
                          room=room, log=self.events.append, asks=asks)


def test_a_closed_chat_is_reopened_once_with_a_clear_message_when_disk_space_frees(tmp_path):
    found = cw.collect(sources(tmp_path, [disk_wait(ready=True)]), NOW)
    registry = {CHAT: {"state": "stopped", "title": "Apple core"}}
    rec = Recorder()
    delivered, failures = rec.run(found, {}, registry, tmp_path)
    assert failures == [] and delivered == {"disk:1f81b951aaaa"}
    (chat_id, text), = rec.resumed
    assert chat_id == CHAT and text.startswith(cw.WAKE_PREFIX)
    assert "space for your waiting step ci-source:fe65" in text and "rerun that step now" in text
    assert rec.events[0]["event"] == "waiter_woken" and rec.events[0]["how"] == "resumed"
    rec.run(found, {}, registry, tmp_path)  # the same ready set is delivered only once
    assert len(rec.resumed) == 1


def test_an_idle_live_pane_chat_is_typed_into_and_a_busy_one_waits_for_a_later_cycle(tmp_path):
    found = cw.collect(sources(tmp_path, [disk_wait(ready=True)]), NOW)
    rec = Recorder()
    rec.run(found, {CHAT: chat(status="busy")}, {}, tmp_path)
    assert rec.typed == [] and rec.resumed == []
    rec.run(found, {CHAT: chat()}, {}, tmp_path)
    assert [c for c, _ in rec.typed] == [CHAT] and rec.resumed == []


def test_no_free_slot_or_a_failed_reopen_is_retried_and_reported(tmp_path):
    found = cw.collect(sources(tmp_path, [disk_wait(ready=True)]), NOW)
    rec = Recorder(resume_outcome="no free chat slot")
    rec.run(found, {}, {}, tmp_path, room=0)
    assert rec.resumed == []
    _, failures = rec.run(found, {}, {}, tmp_path)
    assert failures and "waking it failed (no free chat slot)" in failures[0]["reason"]
    rec.resume_outcome = "ok"
    rec.run(found, {}, {}, tmp_path)
    assert len(rec.resumed) == 2 and rec.events[-1]["event"] == "waiter_woken"


def test_archived_chats_and_chats_asking_the_owner_are_not_woken(tmp_path):
    found = cw.collect(sources(tmp_path, [disk_wait(ready=True)]), NOW)
    rec = Recorder()
    rec.run(found, {}, {CHAT: {"state": "archived"}}, tmp_path)
    assert rec.resumed == []
    _, failures = Recorder().run(found, {CHAT: chat()}, {}, tmp_path / "b", asks=lambda c: True)
    assert "asks you something" in failures[0]["reason"]


def test_a_ci_job_that_ends_while_its_chat_is_closed_reopens_it(tmp_path):
    queue = tmp_path / "logs" / "ci-coordinator" / "queue.sqlite3"
    queue.parent.mkdir(parents=True)
    with sqlite3.connect(queue) as conn:
        conn.execute("CREATE TABLE jobs (id TEXT, owner TEXT, mode TEXT, state TEXT, created REAL, updated REAL)")
        conn.execute("INSERT INTO jobs VALUES ('b97b9ff6abcd', 'fe65', 'apple-ui', 'running', ?, ?)",
                     (NOW - HOUR, NOW - HOUR))
    src = sources(tmp_path, sessions={CHAT: ["fe65"]})
    first = cw.collect(src, NOW)
    assert [w.key for w in first[CHAT]] == ["ci:b97b9ff6abcd"] and not first[CHAT][0].ready
    cw.remember(src.state, first, set())
    with sqlite3.connect(queue) as conn:
        conn.execute("UPDATE jobs SET state='failure', updated=?", (NOW + 60,))
    second = cw.collect(src, NOW + 300)
    (job,) = second[CHAT]
    assert job.ready and "finished: failure" in job.ready_text
    rec = Recorder()
    delivered, _ = rec.run(second, {}, {CHAT: {"state": "stopped"}}, src.state, now=NOW + 300)
    assert rec.resumed and "ci_coordinator.py result b97b9ff6abcd" in rec.resumed[0][1]
    cw.remember(src.state, second, delivered)
    assert cw.collect(src, NOW + 600) == {}


def test_a_live_chat_that_already_saw_its_ci_result_is_not_woken_twice(tmp_path):
    job = cw.Waiter(CHAT, "ci", "ci:j1", "CI e2e job j1", NOW - HOUR, NOW + HOUR, ready=True,
                    ready_text="CI e2e job j1 finished: success", ready_at=NOW - 600)
    rec = Recorder()
    delivered, _ = rec.run({CHAT: [job]}, {CHAT: chat(last_activity=NOW - 300)}, {}, tmp_path)
    assert rec.typed == [] and delivered == {"ci:j1"}


# ---------------------------------------------------------------------------
# Handoffs and other registered waiters.
# ---------------------------------------------------------------------------


def test_a_registered_handoff_keeps_the_chat_and_firing_it_wakes_the_chat_once(tmp_path):
    src = sources(tmp_path)
    key = cw.add(src.state, CHAT, "handoff", "the web Rust chat 547d hands over the drafts core", now=NOW)
    found = cw.collect(src, NOW + 60)
    assert lc.decide(chat(waiters=found[CHAT]), NOW + 60, CONFIG, "other").action == "keep"
    cw.fire(src.state, CHAT, key, "drafts core landed in 1a2b3c4", now=NOW + 120)
    found = cw.collect(src, NOW + 180)
    rec = Recorder()
    delivered, _ = rec.run(found, {}, {CHAT: {"state": "stopped"}}, src.state, now=NOW + 180)
    assert "drafts core landed in 1a2b3c4" in rec.resumed[0][1] and delivered == {f"reg:{key}"}
    assert cw.collect(src, NOW + 240) == {}  # delivered registrations are removed
    with pytest.raises(KeyError):
        cw.fire(src.state, OTHER, key)


def test_add_refuses_unknown_kinds_and_non_chat_ids(tmp_path):
    with pytest.raises(ValueError):
        cw.add(tmp_path, CHAT, "disk", "x")
    with pytest.raises(ValueError):
        cw.add(tmp_path, "not-a-chat", "handoff", "x")


# ---------------------------------------------------------------------------
# 3) status.json reports waiting chats as waiting, not idle or done.
# ---------------------------------------------------------------------------


def test_status_lists_waiting_chats_running_and_closed_with_what_they_wait_on(tmp_path):
    found = cw.collect(sources(tmp_path, [disk_wait(), disk_wait(request_id="r2", thread=OTHER)]), NOW)
    entries = cw.status_entries(found, {CHAT: chat()}, {OTHER: {"state": "stopped", "title": "Web core"}}, NOW)
    by_id = {entry["session_id"]: entry for entry in entries}
    assert by_id[CHAT]["running"] and not by_id[OTHER]["running"]
    assert by_id[OTHER]["kinds"] == ["disk"] and by_id[OTHER]["title"] == "Web core"
    assert by_id[CHAT]["waits_on"][0].startswith("disk: disk space for ci-source:fe65 (waiting")
    summary = lc.counts([chat()], {}, NOW, CONFIG, "other", waiting=entries)
    assert summary["waiting_running"] == 1 and summary["waiting_closed"] == 1
    lc.write_status(tmp_path, summary, {}, waiting=entries)
    assert json.loads((tmp_path / "status.json").read_text())["waiting"] == entries


def test_run_cycle_keeps_the_waiting_chat_and_reopens_it_after_it_was_closed(tmp_path, monkeypatch):
    """The whole d2a774d9 sequence through the lifecycle cycle, with process control faked."""
    monkeypatch.setenv("OPENMATES_CHAT_LIFECYCLE_DIR", str(tmp_path))
    rows = [disk_wait()]
    monkeypatch.setattr(lc, "gather_waiters", lambda now: cw.collect(sources(tmp_path, rows), now))
    live = [chat(last_activity=lc.time.time() - 64 * 60)]
    monkeypatch.setattr(lc, "live_chats", lambda home, config, found=None: [
        lc.Chat(**{**c.__dict__, "waiters": (found or {}).get(c.session_id, [])}) for c in live])
    stopped, resumed = [], []
    monkeypatch.setattr(lc, "stop", lambda target: stopped.append(target.session_id) or True)
    monkeypatch.setattr(lc, "guard_unfinished", lambda plan, *a, **k: (plan, []))
    monkeypatch.setattr(lc, "unfinished_stalled", lambda registry: [])
    import claude_dispatch
    monkeypatch.setattr(claude_dispatch, "resume_chat",
                        lambda chat_id, text, **kw: resumed.append((chat_id, text, kw)) or "ok")
    args = type("Args", (), {"command": "reap", "dry_run": False, "pressure": False, "claude_home": tmp_path})()
    lc.run_cycle(args, CONFIG)
    assert stopped == []
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["waiting"][0]["session_id"] == CHAT and status["waiting_running"] == 1
    live.clear()  # the chat went away while it still waited (zellij crash, an older stop)
    rows[0] = disk_wait(ready=True)
    lc.run_cycle(args, CONFIG)
    assert resumed and resumed[0][0] == CHAT and resumed[0][2] == {"title": f"wake {CHAT[:8]}", "admitted": True}
    assert "waiter_woken" in (tmp_path / "events.jsonl").read_text()


# ---------------------------------------------------------------------------
# 2) The disk coordinator marks a parked wait ready instead of leaving it silent.
# ---------------------------------------------------------------------------


from collections import namedtuple  # noqa: E402

from scripts import disk_coordinator as disk  # noqa: E402  (as in test_disk_coordinator.py)

Usage = namedtuple("Usage", "total used free")


def fixture(tmp_path, *, free, used):
    now, usage = [1000.0], [Usage(1000, used, free)]
    root = tmp_path / "repo"
    root.mkdir()
    c = disk.Coordinator(tmp_path / "host", usage=lambda _: usage[0], inodes=lambda _: 100000, clock=lambda: now[0])
    c.register(root, maintenance=())
    return c, root, now, usage


def request(c, root, *, thread):
    return c.request(root, 70, operation="ci-source:fe65", thread=thread, min_free=50, max_used_percent=99,
                     min_inodes=10)


@pytest.fixture
def parked(tmp_path):
    c, root, now, usage = fixture(tmp_path, free=100, used=900)
    thread = str(uuid.uuid4())
    row = request(c, root, thread=thread)
    with c.leadership():
        c.tick(recovery_margin=0)
        assert c.get(row["id"])["state"] == "waiting"  # 70 + 50 floor > 100 free
        with c.db(write=True) as db:  # the chat's tool process exited: the wait is parked
            db.execute("UPDATE requests SET pid=2147483000 WHERE id=?", (row["id"],))
        yield c, root, now, usage, row, thread


def test_a_parked_wait_is_marked_ready_but_not_granted_when_space_frees(parked):
    c, root, now, usage, row, thread = parked
    c.tick(recovery_margin=0)
    assert c.get(row["id"])["reason"] != state.PARKED_READY_REASON
    usage[0] = Usage(1000, 700, 300)  # cleanup freed space
    c.tick(recovery_margin=0)
    after = c.get(row["id"])
    assert after["state"] == "waiting" and after["reason"] == state.PARKED_READY_REASON
    with c.db() as db:
        kinds = [r[0] for r in db.execute("SELECT kind FROM events")]
    assert kinds.count("parked_ready") == 1 and "grant" not in kinds
    again = request(c, root, thread=thread)  # the reopened chat retries the step
    assert again["id"] == row["id"]
    c.tick(recovery_margin=0)
    assert c.get(row["id"])["state"] == "granted"


def test_a_parked_wait_older_than_a_day_is_cancelled_as_stalled(parked):
    c, root, now, usage, row, thread = parked
    now[0] += state.PARKED_WAIT_EXPIRY + 1
    c.tick(recovery_margin=0)
    after = c.get(row["id"])
    assert after["state"] == "cancelled" and after["reason"].startswith("Stalled")


# ---------------------------------------------------------------------------
# Timer waiters (TASK-9844): wake a chat at a time, e.g. after the weekly usage reset.
# ---------------------------------------------------------------------------


def test_a_timer_lets_the_chat_stop_then_reopens_it_once_when_due(tmp_path):
    src = sources(tmp_path)
    key = cw.add(src.state, CHAT, "timer", "Usage has reset. Continue the job search.", now=NOW, at=NOW + 3 * HOUR)
    found = cw.collect(src, NOW + 60)
    assert not found[CHAT][0].blocks_stop(NOW + 60) and not found[CHAT][0].stalled(NOW + 60)
    assert not found[CHAT][0].ready
    found = cw.collect(src, NOW + 3 * HOUR + 1)
    rec = Recorder()
    delivered, _ = rec.run(found, {}, {CHAT: {"state": "stopped"}}, src.state, now=NOW + 3 * HOUR + 1)
    assert "Continue the job search" in rec.resumed[0][1] and delivered == {f"reg:{key}"}
    assert cw.collect(src, NOW + 4 * HOUR) == {}  # fired once, then removed


def test_a_usage_checked_timer_sleeps_an_hour_while_usage_is_used_up(tmp_path):
    from datetime import datetime, timezone

    reset = datetime.fromtimestamp(NOW + 7 * 24 * HOUR, timezone.utc)
    src = sources(tmp_path)
    src.usage = lambda: (99.0, reset)
    cw.add(src.state, CHAT, "timer", "Usage has reset.", now=NOW, at=NOW + HOUR, usage_check=True)
    found = cw.collect(src, NOW + HOUR + 1)
    assert not found[CHAT][0].ready and found[CHAT][0].timeout_at == NOW + 2 * HOUR + 1
    calls = []
    src.usage = lambda: calls.append(1) or (3.0, reset)
    cw.add(src.state, OTHER, "timer", "Usage has reset too.", now=NOW, at=NOW + HOUR, usage_check=True)
    found = cw.collect(src, NOW + 2 * HOUR + 2)
    assert found[CHAT][0].ready and "weekly usage is 3%" in found[CHAT][0].ready_text
    assert found[OTHER][0].ready and len(calls) == 1  # one usage read for all due timers


def test_a_timer_needs_a_time_with_zone(tmp_path):
    with pytest.raises(ValueError):
        cw.add(tmp_path, CHAT, "timer", "x")
    with pytest.raises(ValueError):
        cw.parse_at("2026-11-20T10:05:00", False)
    assert cw.parse_at("2026-11-20T10:05:00+00:00", False) == (1795169100.0, False)


def test_the_reset_wake_reopens_a_few_chats_by_task_priority_and_results_before_timers(tmp_path):
    """Owner, 2026-11-20: the usage-reset wake filled all 20 slots with chats that did one step."""
    ids = [f"{n:08d}-0000-4000-8000-000000000000" for n in range(6)]
    found = {cid: [cw.Waiter(cid, "timer", f"reg:{n}", "resume", NOW - 9 * HOUR + n, NOW - HOUR, ready=True,
                             ready_text="your timer is due", ready_at=NOW - HOUR)] for n, cid in enumerate(ids)}
    found[ids[5]] = [cw.Waiter(ids[5], "ci", "ci:job", "CI e2e job", NOW - 2 * HOUR, NOW + HOUR, ready=True,
                               ready_text="CI finished", ready_at=NOW - 60)]
    registry = {cid: {"state": "stopped", "title": cid[:8]} for cid in ids}
    rec = Recorder()
    cw.deliver(found, {}, registry, tmp_path, NOW, type_into=rec.type_into, resume=rec.resume, room=3,
               log=rec.events.append, priority={ids[3]: 0, ids[1]: 2})
    assert [chat_id for chat_id, _ in rec.resumed] == [ids[5], ids[3], ids[1]]  # CI result, urgent, medium
    cw.deliver(found, {}, registry, tmp_path, NOW, type_into=rec.type_into, resume=rec.resume, room=0,
               log=rec.events.append)
    assert len(rec.resumed) == 3  # no room left: the rest waits for a later cycle


def test_a_timed_out_handoff_shows_as_timed_out_not_stalled_and_is_dropped_a_day_later(tmp_path):
    state_dir = tmp_path / "state"
    key = cw.add(state_dir, CHAT, "handoff", "owner answer on the disk proposal", timeout_minutes=60, now=NOW - 2 * HOUR)
    found = cw.collect(sources(tmp_path), NOW)
    (waiter,) = found[CHAT]
    assert "timed out" in waiter.label(NOW) and "STALLED" not in waiter.label(NOW) and not waiter.late(NOW)
    (entry,) = cw.status_entries(found, {}, {}, NOW)
    assert entry["timed_out"] and not entry["stalled"]
    assert cw.stalled_entries(found, {}, {}, NOW) == []
    events: list = []
    assert cw.expire(state_dir, NOW + (cw.EXPIRE_HOURS - 2) * 3600, events.append) == []  # not a full day past yet
    assert cw.expire(state_dir, NOW + (cw.EXPIRE_HOURS + 1) * 3600, events.append) == [key]
    assert events[0]["event"] == "waiter_expired" and CHAT not in cw.collect(sources(tmp_path), NOW + 26 * HOUR)


def test_a_chat_without_a_transcript_here_is_reported_once_and_its_waiters_dropped(tmp_path):
    """TASK-9435: 5 chats were retried 11,354 times with 'no transcript on this host'."""
    found = {CHAT: [cw.Waiter(CHAT, "ci", "ci:job", "CI e2e job", NOW - HOUR, NOW + HOUR, ready=True,
                              ready_text="CI finished", ready_at=NOW - 60)]}
    registry = {CHAT: {"state": "stopped", "title": "Remote chat"}}
    rec = Recorder(resume_outcome="no transcript on this host")
    delivered, failures = rec.run(found, {}, registry, tmp_path)
    assert delivered == {"ci:job"}
    assert len(failures) == 1 and "waiting stopped" in failures[0]["reason"]
    assert [e["event"] for e in rec.events] == ["waiter_wake_failed", "waiter_dropped"]
    delivered, failures = rec.run(found, {}, registry, tmp_path)
    assert len(rec.resumed) == 1 and failures == []  # never retried


def test_a_transient_wake_failure_is_retried(tmp_path):
    found = {CHAT: [cw.Waiter(CHAT, "ci", "ci:job", "CI e2e job", NOW - HOUR, NOW + HOUR, ready=True,
                              ready_text="CI finished", ready_at=NOW - 60)]}
    rec = Recorder(resume_outcome="no free chat slot (cap)")
    rec.run(found, {}, {CHAT: {"state": "stopped"}}, tmp_path)
    rec.run(found, {}, {CHAT: {"state": "stopped"}}, tmp_path)
    assert len(rec.resumed) == 2
