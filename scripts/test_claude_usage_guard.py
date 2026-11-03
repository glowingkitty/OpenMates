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
    assert text.splitlines()[0].startswith("URGENT: weekly Claude usage is at 91%")
    for needle in ("final publish remains", "OpenMates Task", "recommended next steps", "overrides this message"):
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
