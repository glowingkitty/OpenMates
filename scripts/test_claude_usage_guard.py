# contract-test-file: tooling
"""Tests for the deterministic parts of scripts/claude_usage_guard.py."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import claude_usage_guard as guard  # noqa: E402  (path set above)

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def resets_in(hours: float) -> datetime:
    return NOW + timedelta(hours=hours)


def test_below_threshold_does_nothing() -> None:
    assert guard.decide(89.9, resets_in(60), NOW, None).action == "below_threshold"


def test_triggers_at_threshold_with_more_than_24h_left() -> None:
    assert guard.decide(90.0, resets_in(24.5), NOW, None).action == "trigger"


def test_near_reset_waits_instead_of_triggering() -> None:
    assert guard.decide(95.0, resets_in(24.0), NOW, None).action == "near_reset"
    assert guard.decide(95.0, resets_in(5), NOW, None).action == "near_reset"


def test_sent_once_per_window_and_rearms_for_next_window() -> None:
    reset = resets_in(40)
    record = {"window": guard.window_key(reset), "sent_at": "x"}
    assert guard.decide(97, reset, NOW, record).action == "already_sent"
    next_week = reset + timedelta(days=7)
    later = NOW + timedelta(days=7)
    assert guard.decide(91, next_week, later, record).action == "trigger"


def test_window_key_ignores_subsecond_reset_jitter() -> None:
    a = datetime(2026, 11, 6, 10, 0, 0, 123, tzinfo=timezone.utc)
    b = datetime(2026, 11, 6, 10, 0, 0, 987654, tzinfo=timezone.utc)
    assert guard.window_key(a) == guard.window_key(b)


def test_gives_up_after_max_failed_attempts() -> None:
    reset = resets_in(40)
    record = {"window": guard.window_key(reset), "attempts": guard.MAX_ATTEMPTS}
    assert guard.decide(95, reset, NOW, record).action == "gave_up"
    record["attempts"] = guard.MAX_ATTEMPTS - 1
    assert guard.decide(95, reset, NOW, record).action == "trigger"


def test_message_states_usage_reset_and_required_steps() -> None:
    text = guard.wrapup_message(91.4, resets_in(40), 40)
    assert text.splitlines()[0].startswith("Weekly Claude usage is at 91%")
    assert "orderly way" in text and "URGENT" not in text
    for needle in ("can be completed in about 10 minutes", "exact next command or file", "/new-task",
                   "recommended next steps", "overrides this message"):
        assert needle in text


def test_sender_mode_mirrors_uniform_target_mode_and_warns_when_mixed() -> None:
    assert guard.sender_mode([{"permissionMode": "auto"}, {"permissionMode": "auto"}]) == ("auto", "")
    assert guard.sender_mode([{"permissionMode": "plan"}]) == ("plan", "")
    mode, warning = guard.sender_mode([{"permissionMode": "auto"}, {"permissionMode": "plan"}])
    assert mode == guard.FALLBACK_MODE and "mixed" in warning
    assert guard.sender_mode([{"permissionMode": ""}])[1]


def test_chat_permission_mode_reads_latest_recorded_mode(tmp_path: Path) -> None:
    transcript = tmp_path / "chat.jsonl"
    transcript.write_text("\n".join(json.dumps(row) for row in [
        {"type": "user", "permissionMode": "plan"}, {"type": "assistant"},
        {"type": "user", "permissionMode": "auto"}, {"type": "assistant"}]))
    assert guard.chat_permission_mode(transcript) == "auto"
    assert guard.chat_permission_mode(None) == ""


def test_active_targets_skip_idle_done_and_own_chat(tmp_path: Path, monkeypatch) -> None:
    recent = tmp_path / "recent.jsonl"
    recent.write_text("{}")
    stale = tmp_path / "stale.jsonl"
    stale.write_text("{}")
    old = NOW.timestamp() - 3 * 3600
    os.utime(stale, (old, old))
    monkeypatch.setattr(guard, "transcripts", lambda root: {"busy": recent, "done": recent, "wait": recent,
                                                            "stale": stale, "me": recent})
    rows = [
        {"name": "busy-one", "sessionId": "busy", "status": "busy"},
        {"name": "finished-bg", "sessionId": "done", "status": "idle", "state": "done"},
        {"name": "waiting-recent", "sessionId": "wait", "status": "idle"},
        {"name": "long-idle", "sessionId": "stale", "status": "idle"},
        {"name": "self", "sessionId": "me", "status": "busy"},
    ]
    now = recent.stat().st_mtime + 60
    names = [t["name"] for t in guard.active_targets(rows, tmp_path, now, 30, exclude_session="me")]
    assert names == ["busy-one", "waiting-recent"]


def test_run_check_delivers_once_and_records_it(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(guard, "fetch_weekly_usage", lambda: (92.0, resets_in(48)))
    monkeypatch.setattr(guard, "list_background_agents", lambda: [{"name": "a", "sessionId": "s", "status": "busy"}])
    monkeypatch.setattr(guard, "transcripts", lambda root: {})
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(guard, "deliver", lambda targets, message, root, mode: sent.append((mode, message)) or '{"sent": ["a"]}')
    assert guard.run_check(False, 90, 24, 30, tmp_path, NOW).action == "trigger"
    assert guard.run_check(False, 90, 24, 30, tmp_path, NOW).action == "already_sent"
    assert len(sent) == 1
    assert json.loads((tmp_path / "state.json").read_text())["sent_at"]


def test_failed_delivery_is_retried_then_abandoned(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(guard, "fetch_weekly_usage", lambda: (92.0, resets_in(48)))
    monkeypatch.setattr(guard, "list_background_agents", lambda: [{"name": "a", "sessionId": "s", "status": "busy"}])
    monkeypatch.setattr(guard, "transcripts", lambda root: {})

    def fail(*args: object) -> str:
        raise guard.DeliveryFailed("boom")

    monkeypatch.setattr(guard, "deliver", fail)
    actions = [guard.run_check(False, 90, 24, 30, tmp_path, NOW).action for _ in range(guard.MAX_ATTEMPTS + 1)]
    assert actions == ["trigger"] * guard.MAX_ATTEMPTS + ["gave_up"]


def test_resend_follows_up_once_to_the_recorded_chats(tmp_path: Path, monkeypatch) -> None:
    reset = resets_in(48)
    guard.save_record(tmp_path, {"window": guard.window_key(reset), "sent_at": "x", "targets": [
        {"name": "a", "sessionId": "s1", "permissionMode": "auto"},
        {"name": "me", "sessionId": "own", "permissionMode": "auto"}]})
    monkeypatch.setattr(guard, "fetch_weekly_usage", lambda: (91.0, reset))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "own")
    sent: list[list[str]] = []
    monkeypatch.setattr(guard, "deliver", lambda targets, message, root, mode: sent.append([t["name"] for t in targets]) or "ok")
    assert guard.run_resend(tmp_path, NOW) == 0
    assert sent == [["a"]]
    try:
        guard.run_resend(tmp_path, NOW)
    except guard.DeliveryFailed as error:
        assert "already sent" in str(error)
    else:
        raise AssertionError("second follow-up must be refused")


def test_resend_refused_when_nothing_was_sent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(guard, "fetch_weekly_usage", lambda: (91.0, resets_in(48)))
    try:
        guard.run_resend(tmp_path, NOW)
    except guard.DeliveryFailed as error:
        assert "nothing was sent" in str(error)
    else:
        raise AssertionError("resend without a first message must be refused")


def test_reset_time_wobble_around_the_hour_is_the_same_window(tmp_path: Path, monkeypatch) -> None:
    """Regression: 10:59:58 vs 11:00:01 flipped the hour-floored key and re-sent to every chat."""
    early = datetime(2026, 11, 6, 10, 59, 58, tzinfo=timezone.utc)
    late = datetime(2026, 11, 6, 11, 0, 1, tzinfo=timezone.utc)
    record = {"window": guard.window_key(early), "sent_at": "x"}
    assert guard.window_key(early) != guard.window_key(late)
    assert guard.decide(95, late, NOW, record).action == "already_sent"
    assert guard.decide(95, late + timedelta(days=7), NOW + timedelta(days=7), record).action == "trigger"
    monkeypatch.setattr(guard, "list_background_agents", lambda: [])
    monkeypatch.setattr(guard, "transcripts", lambda root: {})
    guard.save_record(tmp_path, record)
    monkeypatch.setattr(guard, "fetch_weekly_usage", lambda: (95.0, late))
    assert guard.run_check(False, 90, 24, 30, tmp_path, NOW - timedelta(days=5)).action == "already_sent"


def test_reserve_tier_triggers_at_3_percent_left_with_more_than_10h() -> None:
    args = (guard.RESERVE_THRESHOLD_PERCENT, guard.RESERVE_MIN_HOURS_TO_RESET)
    assert guard.decide(96.9, resets_in(20), NOW, None, *args).action == "below_threshold"
    assert guard.decide(97.0, resets_in(10.5), NOW, None, *args).action == "trigger"
    assert guard.decide(99.0, resets_in(10.0), NOW, None, *args).action == "near_reset"


def test_reserve_tier_fires_even_when_wrapup_already_sent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(guard, "fetch_weekly_usage", lambda: (98.0, resets_in(30)))
    monkeypatch.setattr(guard, "list_background_agents", lambda: [{"name": "a", "sessionId": "s", "status": "busy"}])
    monkeypatch.setattr(guard, "transcripts", lambda root: {})
    sent: list[str] = []
    monkeypatch.setattr(guard, "deliver", lambda targets, message, root, mode: sent.append(message) or "ok")
    guard.save_record(tmp_path, {"window": guard.window_key(resets_in(30)), "sent_at": "x"})
    assert guard.run_check(False, 90, 24, 30, tmp_path, NOW).action == "already_sent"
    assert guard.run_check(False, 97, 10, 30, tmp_path, NOW, tier=guard.RESERVE_TIER).action == "trigger"
    assert guard.run_check(False, 97, 10, 30, tmp_path, NOW, tier=guard.RESERVE_TIER).action == "already_sent"
    assert len(sent) == 1 and sent[0].startswith("EMERGENCY RESERVE")
    assert (tmp_path / "state-reserve.json").exists()


def test_reserve_message_demands_an_immediate_stop() -> None:
    text = guard.reserve_message(97.6, resets_in(30), 30)
    assert "EMERGENCY RESERVE" in text and "usage is at 98%" in text and "stop this chat now" in text
    assert "exact next command or file" in text and "overrides this message" in text


def test_pace_requires_15_percent_per_full_day_left() -> None:
    assert guard.pace_days(160.5) == 6 and guard.pace_required_remaining(160.5) == 90
    assert guard.pace_required_remaining(48.1) == 30 and guard.pace_threshold(48.1) == 70
    assert guard.pace_required_remaining(23.9) == 0  # last day: the reserve tiers take over
    assert guard.pace_required_remaining(7 * 24) == 90  # a fresh window never demands more than 100%


def test_pace_decision_uses_the_falling_threshold() -> None:
    # 80% left with 6.7 days to go is below 6 x 15% = 90% -> stop; the same 80% left with 5.2 days is fine.
    assert guard.decide(20, resets_in(160.5), NOW, None, guard.pace_threshold(160.5), 0).action == "trigger"
    assert guard.decide(20, resets_in(125), NOW, None, guard.pace_threshold(125), 0).action == "below_threshold"
    assert guard.decide(26, resets_in(125), NOW, None, guard.pace_threshold(125), 0).action == "trigger"


def _pace_env(monkeypatch, rows: list[dict], used: float = 20.0, hours: float = 160.5) -> list[list[str]]:
    monkeypatch.setattr(guard, "fetch_weekly_usage", lambda: (used, resets_in(hours)))
    monkeypatch.setattr(guard, "list_background_agents", lambda: rows)
    monkeypatch.setattr(guard, "transcripts", lambda root: {})
    sent: list[list[str]] = []
    monkeypatch.setattr(guard, "deliver", lambda targets, message, root, mode:
                        sent.append([t["sessionId"] for t in targets]) or message.splitlines()[0])
    return sent


def test_pace_tells_each_chat_once_but_reaches_chats_started_later(tmp_path: Path, monkeypatch) -> None:
    rows = [{"name": "a", "sessionId": "s1", "status": "busy"}]
    sent = _pace_env(monkeypatch, rows)
    assert guard.run_check(False, 0, 0, 30, tmp_path, NOW, tier=guard.PACE_TIER).action == "trigger"
    guard.run_check(False, 0, 0, 30, tmp_path, NOW, tier=guard.PACE_TIER)
    rows.append({"name": "b", "sessionId": "s2", "status": "busy"})
    guard.run_check(False, 0, 0, 30, tmp_path, NOW, tier=guard.PACE_TIER)
    assert sent == [["s1"], ["s2"]]
    assert json.loads((tmp_path / "state-pace.json").read_text())["notified"] == ["s1", "s2"]


def test_pace_tells_chats_again_on_the_next_day_step(tmp_path: Path, monkeypatch) -> None:
    rows = [{"name": "a", "sessionId": "s1", "status": "busy"}]
    sent = _pace_env(monkeypatch, rows, used=40.0, hours=160.5)
    guard.run_check(False, 0, 0, 30, tmp_path, NOW, tier=guard.PACE_TIER)
    _pace_env(monkeypatch, rows, used=39.9, hours=100.0)  # step 4 needs 60%; 60.1% left is fine
    assert guard.run_check(False, 0, 0, 30, tmp_path, NOW, tier=guard.PACE_TIER).action == "below_threshold"
    sent_after = _pace_env(monkeypatch, rows, used=45.0, hours=100.0)  # 55% left < 60% -> stop again
    assert guard.run_check(False, 0, 0, 30, tmp_path, NOW, tier=guard.PACE_TIER).action == "trigger"
    assert sent == [["s1"]] and sent_after == [["s1"]]


def test_pace_successful_deliveries_never_exhaust_the_attempt_budget(tmp_path: Path, monkeypatch) -> None:
    rows: list[dict] = []
    sent = _pace_env(monkeypatch, rows)
    for index in range(guard.MAX_ATTEMPTS + 2):
        rows.append({"name": f"c{index}", "sessionId": f"s{index}", "status": "busy"})
        assert guard.run_check(False, 0, 0, 30, tmp_path, NOW, tier=guard.PACE_TIER).action == "trigger"
    assert len(sent) == guard.MAX_ATTEMPTS + 2


def test_pace_message_demands_a_stop_with_progress_and_open_items() -> None:
    text = guard.pace_message(20, resets_in(160.5), 160.5)
    assert text.startswith("STOP: only 80% of the weekly Claude budget is left")
    assert "6 full day(s)" in text and "= 90%" in text
    for needle in ("progress made and what remains open", "exact next command or file", "/new-task",
                   "overrides this message"):
        assert needle in text
    assert guard.tier_message(guard.PACE_TIER, 20, resets_in(160.5), 160.5) == text


def test_pace_tier_is_off_unless_enabled(monkeypatch, capsys) -> None:
    seen: list[str] = []
    monkeypatch.setattr(guard, "run_check", lambda *args, tier=guard.WRAPUP_TIER, **kw: seen.append(tier))
    assert guard.main(["check"]) == 0
    assert seen == [guard.RESERVE_TIER, guard.WRAPUP_TIER]
    seen.clear()
    assert guard.main(["check", "--enable-pace"]) == 0
    assert seen == [guard.RESERVE_TIER, guard.PACE_TIER, guard.WRAPUP_TIER]
    guard.main(["message"])
    assert "--- pace ---" not in capsys.readouterr().out
