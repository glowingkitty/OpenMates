#!/usr/bin/env python3
# contract-test-file: tooling
"""Contract tests for active OpenCode progress Discord notifications.

The notifier observes existing OpenCode presence and bounded transcript
projections, asks Gemini Flash-Lite for one progress digest, and posts only
that digest to Discord. Tests use fakes for the model and Discord so they never send
network traffic or expose real chat transcript content.
Architecture: docs/specs/opencode-active-progress-notifier/spec.yml.
"""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "scripts" / "opencode_progress_notifier.py"
LONG_TASK = "Document every visible notifier task in Discord without replacing the final words with an ellipsis marker or hiding additional pending work"
LONG_SUMMARY_TAIL = "including this final clause about cron approval and validation."


def load_module(name: str = "opencode_progress_notifier_test"):
    spec = importlib.util.spec_from_file_location(name, RUNNER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def live_item(session_id: str, *, title: str, execution: str, parent_id: str = "", updated_at: str = "2026-08-10T12:50:00Z") -> dict:
    return {
        "opencode_session_id": session_id,
        "top_level_session_id": parent_id or session_id,
        "parent_id": parent_id,
        "child_role": "read_only" if parent_id else "unknown",
        "execution": execution,
        "attention": "none",
        "turn": "running" if execution == "busy" else "completed",
        "task": title,
        "updated_at": updated_at,
    }


def fake_status() -> dict:
    return {
        "live": {
            "working": [
                live_item("ses-parent", title="Build notifier", execution="busy"),
                live_item("ses-child", title="Child reviewer", execution="busy", parent_id="ses-parent"),
            ],
            "waiting_for_user": [
                live_item("ses-wait", title="Needs decision", execution="idle"),
                live_item("ses-stale-wait", title="Old Fiverr research", execution="idle", updated_at="2026-08-09T12:50:00Z"),
            ],
            "idle_after_response": [live_item("ses-idle", title="Done", execution="idle")],
            "stopped_or_failed": [],
        }
    }


def fake_status_with_timestamp(timestamp: str) -> dict:
    status = fake_status()
    for section in ("working", "waiting_for_user", "idle_after_response", "stopped_or_failed"):
        for item in status["live"].get(section, []):
            item["updated_at"] = timestamp
    return status


def fake_chat_view(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "sessions": [
            {
                "session_id": session_id,
                "title": "Build notifier" if session_id == "ses-parent" else "Needs decision",
                "directory": str(ROOT),
                "time_updated": "2026-08-10T12:51:00Z",
            }
        ],
        "repository_sessions": [{"modified_files": ["scripts/example.py"]}],
        "issue_signals": [
            {
                "kind": "tool_error",
                "tool": "bash",
                "text": "HTTP 401 while checking GitHub credentials",
            }
        ],
        "messages": [
            {
                "message_id": "msg-1",
                "role": "assistant",
                "time_updated": "2026-08-10T12:51:00Z",
                "parts": [
                    {"type": "text", "text": "Chose option 2 and hit a GitHub auth issue."},
                    {
                        "type": "tool",
                        "tool": "todowrite",
                        "status": "completed",
                        "input": {
                            "todos": [
                                {"content": "Create executable spec", "status": "completed", "priority": "high"},
                                {"content": "Implement notifier format", "status": "in_progress", "priority": "high"},
                                {"content": "Send validation Discord message", "status": "pending", "priority": "high"},
                                {"content": LONG_TASK, "status": "pending", "priority": "medium"},
                            ]
                        },
                    },
                    {"type": "file", "filename": "private.png", "content_omitted": True},
                ],
            }
        ],
        "truncated": {"messages": False, "parts": False, "fields": False},
    }


def fake_digest(active_chats: list[dict]) -> dict:
    return {
        "overall_summary": "Two chats are active; one made an architecture decision and one needs input.",
        "summary_bullets": ["Architecture decision made using Gemini 3.5 Flash Lite", "One chat needs input"],
        "important_decisions": ["Adopted 15-minute cadence and Gemini 3.5 Flash Lite for notifier summaries."],
        "watch_points": ["GitHub auth returned 401."],
        "_usage_metadata": {"promptTokenCount": 2000, "candidatesTokenCount": 500, "totalTokenCount": 2500},
        "chats": [
            {
                "session_id": chat["session_id"],
                "summary": f"{chat['title']} is {chat['status_label']} with Gemini 3.5 Flash Lite summaries, complete detail about formatter cleanup, task rendering, Discord validation, and {LONG_SUMMARY_TAIL}",
                "tasks": {
                    "completed": ["Generated completed task"],
                    "current": ["Generated current task"],
                    "next": ["Generated next task"],
                },
                "important_decisions": [],
                "watch_points": [],
            }
            for chat in active_chats
        ],
    }


def test_selection_groups_recent_work_waiting_and_completed_only() -> None:
    notifier = load_module("progress_selection")

    selected = notifier.select_active_chat_roots(fake_status(), now=datetime(2026, 8, 10, 12, 55, tzinfo=timezone.utc))

    assert [chat.session_id for chat in selected] == ["ses-parent", "ses-wait", "ses-idle"]
    assert selected[0].active_child_session_ids == ["ses-child"]
    assert selected[0].status_label == "active"
    assert selected[1].status_label == "waiting_for_user"
    assert selected[2].status_label == "completed_recently"
    assert "ses-stale-wait" not in [chat.session_id for chat in selected]


def test_legacy_periodic_run_is_disabled_without_force(tmp_path: Path) -> None:
    notifier = load_module("progress_no_active")
    calls: list[str] = []

    result = notifier.run_once(
        status_loader=lambda: calls.append("status") or fake_status(),
        chat_reader=lambda _session_id: fake_chat_view(_session_id),
        summarizer=lambda **_kwargs: calls.append("model") or {},
        discord_sender=lambda **_kwargs: calls.append("discord") or {"message_id": "1"},
        state_path=tmp_path / "state.json",
        api_key="test-key",
        webhook_url="https://example.invalid/webhook",
        now=datetime(2026, 8, 10, 12, 55, tzinfo=timezone.utc),
    )

    assert result["status"] == "skipped_legacy_periodic_disabled"
    assert calls == []


def test_forced_legacy_run_with_no_active_chats_skips_model_and_discord(tmp_path: Path) -> None:
    notifier = load_module("progress_no_active_forced")
    calls: list[str] = []

    result = notifier.run_once(
        status_loader=lambda: {"live": {"working": [], "waiting_for_user": [], "idle_after_response": [], "stopped_or_failed": []}},
        chat_reader=lambda _session_id: fake_chat_view(_session_id),
        summarizer=lambda **_kwargs: calls.append("model") or {},
        discord_sender=lambda **_kwargs: calls.append("discord") or {"message_id": "1"},
        state_path=tmp_path / "state.json",
        api_key="test-key",
        webhook_url="https://example.invalid/webhook",
        force=True,
        legacy_periodic_enabled=True,
        now=datetime(2026, 8, 10, 12, 55, tzinfo=timezone.utc),
    )

    assert result["status"] == "skipped_no_active_chats"
    assert calls == []


def test_run_once_uses_gemini_flash_lite_and_posts_digest(tmp_path: Path) -> None:
    notifier = load_module("progress_model_payload")
    captured: dict[str, object] = {}

    def summarize(*, evidence: dict, api_key: str, model: str) -> dict:
        captured["model"] = model
        captured["api_key"] = api_key
        captured["evidence"] = evidence
        return fake_digest(evidence["active_chats"])

    def send(*, webhook_url: str, payload: dict) -> dict[str, str]:
        captured["webhook_url"] = webhook_url
        captured["payload"] = payload
        return {"message_id": "discord-1"}

    result = notifier.run_once(
        status_loader=fake_status,
        chat_reader=fake_chat_view,
        summarizer=summarize,
        discord_sender=send,
        state_path=tmp_path / "state.json",
        api_key="test-key",
        webhook_url="https://example.invalid/webhook",
        force=True,
        legacy_periodic_enabled=True,
        now=datetime(2026, 8, 10, 12, 55, tzinfo=timezone.utc),
    )

    assert result["status"] == "sent"
    assert result["model_called"] is True
    assert result["new_count"] == 3
    assert result["updated_count"] == 0
    assert captured["model"] == notifier.DEFAULT_MODEL
    assert captured["api_key"] == "test-key"
    assert captured["webhook_url"] == "https://example.invalid/webhook"
    assert result["cost_estimate"]["estimated_usd"] > 0
    assert result["cost_estimate"]["token_source"] == "usage"
    assert result["cost_estimate"]["input_tokens_estimate"] == 2000
    assert result["cost_estimate"]["output_tokens_estimate"] == 500
    assert result["cost_estimate"]["input_usd_per_million_tokens"] == 0.30
    assert result["cost_estimate"]["output_usd_per_million_tokens"] == 2.50
    assert result["cost_estimate"]["daily_runs"] == 48
    evidence = captured["evidence"]
    assert evidence["active_chats"][0]["task_items"][0]["content"] == "Create executable spec"
    assert evidence["active_chats"][0]["task_items"][1]["status"] == "in_progress"
    payload = captured["payload"]
    combined = payload["content"] + "\n" + "\n".join(embed["description"] for embed in payload["embeds"])
    assert "**🧭 OpenCode Progress**" in combined
    assert "🆕 3 new · 🔄 0 updated · ✅ 0 completed" in combined
    assert "**🆕 New Chats**" in combined
    assert "Overview:" in combined
    assert "💸 Cost:" not in combined
    assert "~$" not in payload["content"]
    assert notifier.DEFAULT_MODEL not in payload["content"]
    assert "Gemini 3.5" not in combined
    assert "gemini-3.5" not in combined
    assert "Tasks:" in combined
    assert LONG_SUMMARY_TAIL in combined
    assert "✅ Done: Create executable spec" in combined
    assert "🔵 Now: Implement notifier format" in combined
    assert "⏭️ Next: Send validation Discord message" in combined
    assert f"⏭️ Next: {LONG_TASK}" in combined
    assert "... +" not in combined
    assert "…" not in combined
    assert "Generated current task" not in combined
    assert "Old Fiverr research" not in combined
    assert "Build notifier" in combined
    assert "https://code.dev.openmates.org/" in combined
    assert "ses-parent" in combined


def test_model_task_fallback_renders_without_todowrite_input(tmp_path: Path) -> None:
    notifier = load_module("progress_generated_tasks")

    def chat_without_tasks(session_id: str) -> dict:
        view = fake_chat_view(session_id)
        view["messages"][0]["parts"] = [{"type": "text", "text": "Working through implementation."}]
        return view

    sent: dict[str, object] = {}
    result = notifier.run_once(
        status_loader=fake_status,
        chat_reader=chat_without_tasks,
        summarizer=lambda **kwargs: fake_digest(kwargs["evidence"]["active_chats"]),
        discord_sender=lambda **kwargs: sent.setdefault("payload", kwargs["payload"]) or {"message_id": "discord-1"},
        state_path=tmp_path / "state.json",
        api_key="test-key",
        webhook_url="https://example.invalid/webhook",
        force=True,
        legacy_periodic_enabled=True,
        now=datetime(2026, 8, 10, 12, 55, tzinfo=timezone.utc),
    )

    assert result["status"] == "sent"
    combined = sent["payload"]["content"] + "\n" + "\n".join(embed["description"] for embed in sent["payload"]["embeds"])
    assert "✅ Done: Generated completed task" in combined
    assert "🔵 Now: Generated current task" in combined
    assert "⏭️ Next: Generated next task" in combined


def test_known_chat_followup_is_deterministic_task_delta_without_model(tmp_path: Path) -> None:
    notifier = load_module("progress_deterministic_followup")
    state_path = tmp_path / "state.json"
    state = notifier.load_state(state_path)
    now = datetime(2026, 8, 10, 12, 55, tzinfo=timezone.utc)
    initial_view = fake_chat_view("ses-parent")
    initial_chat = notifier.project_chat_view(
        notifier.ActiveChatRoot("ses-parent", "active", "Build notifier", "2026-08-10T12:50:00Z", []),
        initial_view,
    )
    notifier.record_chat_snapshots(state, {"ses-parent": notifier._chat_snapshot(initial_chat, now=now)})
    notifier.save_state(state_path, state)

    def changed_status() -> dict:
        return {"live": {"working": [live_item("ses-parent", title="Build notifier", execution="busy", updated_at="2026-08-10T13:05:00Z")], "waiting_for_user": [], "idle_after_response": [], "stopped_or_failed": []}}

    def changed_chat(_session_id: str) -> dict:
        view = fake_chat_view("ses-parent")
        todos = view["messages"][0]["parts"][1]["input"]["todos"]
        todos[1]["status"] = "completed"
        todos[2]["status"] = "in_progress"
        todos.append({"content": "Review deterministic delta output", "status": "pending", "priority": "high"})
        return view

    calls: list[str] = []
    sent: dict[str, object] = {}
    result = notifier.run_once(
        status_loader=changed_status,
        chat_reader=changed_chat,
        summarizer=lambda **_kwargs: calls.append("model") or {},
        discord_sender=lambda **kwargs: sent.setdefault("payload", kwargs["payload"]) or {"message_id": "discord-1"},
        state_path=state_path,
        api_key="test-key",
        webhook_url="https://example.invalid/webhook",
        force=True,
        legacy_periodic_enabled=True,
        now=datetime(2026, 8, 10, 13, 5, tzinfo=timezone.utc),
    )

    assert result["status"] == "sent"
    assert result["model_called"] is False
    assert calls == []
    assert result["new_count"] == 0
    assert result["updated_count"] == 1
    combined = sent["payload"]["content"] + "\n" + "\n".join(embed["description"] for embed in sent["payload"]["embeds"])
    assert "🆕 0 new · 🔄 1 updated · ✅ 0 completed" in combined
    assert "**🔄 Updates Since Last Check**" in combined
    assert "✅ Completed:" in combined
    assert "• Implement notifier format" in combined
    assert "🔵 Now:" in combined
    assert "• Send validation Discord message" in combined
    assert "⏭️ New Next:" in combined
    assert "• Review deterministic delta output" in combined
    assert "Overview:" not in combined


def test_task_list_changed_event_is_disabled(tmp_path: Path) -> None:
    notifier = load_module("progress_task_event")
    state_path = tmp_path / "state.json"
    state = notifier.load_state(state_path)
    state["task_events"] = {
        "ses-parent": {
            "task_snapshot": [
                {"content": "Create executable spec", "status": "completed"},
                {"content": "Implement notifier format", "status": "in_progress"},
            ]
        }
    }
    notifier.save_state(state_path, state)
    sent: list[object] = []

    result = notifier.notify_task_list_changed(
        session_id="ses-parent",
        todos=[
            {"content": "Create executable spec", "status": "completed", "priority": "high"},
            {"content": "Implement notifier format", "status": "completed", "priority": "high"},
            {"content": "Wire hook trigger", "status": "in_progress", "priority": "high"},
        ],
        chat_reader=fake_chat_view,
        discord_sender=lambda **kwargs: sent.append(kwargs) or {"message_id": "discord-1"},
        state_path=state_path,
        webhook_url="https://example.invalid/webhook",
        now=datetime(2026, 8, 10, 13, 5, tzinfo=timezone.utc),
    )

    assert result["status"] == "skipped_task_notifications_disabled"
    assert sent == []


def test_task_list_changed_event_disabled_even_for_identical_snapshot(tmp_path: Path) -> None:
    notifier = load_module("progress_task_event_dedupe")
    state_path = tmp_path / "state.json"
    todos = [{"content": "Create executable spec", "status": "completed", "priority": "high"}]
    state = notifier.load_state(state_path)
    state["task_events"] = {"ses-parent": {"task_snapshot": notifier._task_snapshot({"task_items": todos})}}
    notifier.save_state(state_path, state)

    result = notifier.notify_task_list_changed(
        session_id="ses-parent",
        todos=todos,
        chat_reader=fake_chat_view,
        discord_sender=lambda **_kwargs: {"message_id": "discord-1"},
        state_path=state_path,
        webhook_url="https://example.invalid/webhook",
        now=datetime(2026, 8, 10, 13, 5, tzinfo=timezone.utc),
    )

    assert result["status"] == "skipped_task_notifications_disabled"


def test_response_completed_event_posts_deterministic_assistant_preview(tmp_path: Path) -> None:
    notifier = load_module("progress_completion_event")
    captured: dict[str, object] = {}
    view = fake_chat_view("ses-parent")
    view["messages"][0]["message_id"] = "msg-assistant-1"
    view["messages"][0]["parts"][0]["text"] = "\n".join(
        [
            "Implemented the event-driven notifier and prepared verification.",
            "Task notifications are disabled.",
            "Completion notifications are deterministic.",
            "Secrets like sk-test123456789 are redacted.",
            "This is the fifth visible line.",
            "This sixth line should be omitted.",
        ]
    )

    result = notifier.notify_response_completed(
        session_id="ses-parent",
        message_id="msg-assistant-1",
        chat_reader=lambda _session_id: view,
        discord_sender=lambda **kwargs: captured.setdefault("payload", kwargs["payload"]) or {"message_id": "discord-1"},
        state_path=tmp_path / "state.json",
        api_key="test-key",
        webhook_url="https://example.invalid/webhook",
        delay_seconds=0,
        now=datetime(2026, 8, 10, 13, 5, tzinfo=timezone.utc),
    )

    assert result["status"] == "sent"
    assert captured["payload"]["embeds"] == []
    content = captured["payload"]["content"]
    assert content.startswith("Build notifier\n")
    assert "Implemented the event-driven notifier" in content
    assert "Completion notifications are deterministic." in content
    assert "<API_KEY>" in content
    assert "This is the fifth visible line." in content
    assert "This sixth line should be omitted." not in content
    assert "Chose option 2" not in content


def test_response_completed_event_skips_when_user_replies_during_delay(tmp_path: Path) -> None:
    notifier = load_module("progress_completion_event_user_reply")
    initial = fake_chat_view("ses-parent")
    initial["messages"][0]["message_id"] = "msg-assistant-1"
    initial["messages"][0]["time_updated"] = "2026-08-10T13:05:00Z"
    replied = fake_chat_view("ses-parent")
    replied["messages"][0] = initial["messages"][0]
    replied["messages"].append(
        {
            "message_id": "msg-user-2",
            "role": "user",
            "time_created": "2026-08-10T13:06:00Z",
            "time_updated": "2026-08-10T13:06:00Z",
            "parts": [{"type": "text", "text": "Thanks, continue."}],
        }
    )
    reads = [initial, replied]
    slept: list[float] = []
    sent: list[object] = []

    result = notifier.notify_response_completed(
        session_id="ses-parent",
        message_id="msg-assistant-1",
        chat_reader=lambda _session_id: reads.pop(0),
        discord_sender=lambda **kwargs: sent.append(kwargs) or {"message_id": "discord-1"},
        state_path=tmp_path / "state.json",
        webhook_url="https://example.invalid/webhook",
        delay_seconds=300,
        sleeper=lambda seconds: slept.append(seconds),
        now=datetime(2026, 8, 10, 13, 5, tzinfo=timezone.utc),
    )

    assert result["status"] == "skipped_user_responded"
    assert slept == [300]
    assert sent == []


def test_response_completed_event_skips_when_chat_still_running_after_delay(tmp_path: Path) -> None:
    notifier = load_module("progress_completion_event_still_running")
    view = fake_chat_view("ses-parent")
    view["messages"][0]["message_id"] = "msg-assistant-1"
    view["messages"][0]["time_updated"] = "2026-08-10T13:05:00Z"
    sent: list[object] = []

    result = notifier.notify_response_completed(
        session_id="ses-parent",
        message_id="msg-assistant-1",
        chat_reader=lambda _session_id: view,
        discord_sender=lambda **kwargs: sent.append(kwargs) or {"message_id": "discord-1"},
        state_path=tmp_path / "state.json",
        webhook_url="https://example.invalid/webhook",
        delay_seconds=0,
        status_loader=lambda: {
            "live": {
                "working": [
                    {
                        "opencode_session_id": "ses-parent",
                        "top_level_session_id": "ses-parent",
                    }
                ]
            }
        },
        now=datetime(2026, 8, 10, 13, 5, tzinfo=timezone.utc),
    )

    assert result["status"] == "skipped_still_running"
    assert sent == []


def test_todowrite_output_is_not_used_as_task_evidence() -> None:
    notifier = load_module("progress_no_tool_output_tasks")
    view = fake_chat_view("ses-parent")
    view["messages"][0]["parts"] = [
        {
            "type": "tool",
            "tool": "todowrite",
            "status": "completed",
            "output": '[{"content":"leaked output task","status":"in_progress","priority":"high"}]',
        },
        {
            "type": "tool",
            "tool": "bash",
            "status": "completed",
            "output_preview": "raw command output should not be projected",
        },
    ]

    evidence = notifier.project_chat_view(
        notifier.ActiveChatRoot("ses-parent", "working", "Build notifier", "2026-08-10T12:50:00Z", []),
        view,
    )
    encoded = json.dumps(evidence)

    assert evidence["task_items"] == []
    assert "leaked output task" not in encoded
    assert "raw command output should not be projected" not in encoded


def test_unchanged_known_chats_skip_model_and_discord(tmp_path: Path) -> None:
    notifier = load_module("progress_dedupe")
    state_path = tmp_path / "state.json"
    sends: list[dict] = []

    kwargs = {
        "status_loader": fake_status,
        "chat_reader": fake_chat_view,
        "summarizer": lambda **kwargs: fake_digest(kwargs["evidence"]["active_chats"]),
        "discord_sender": lambda **kwargs: sends.append(kwargs["payload"]) or {"message_id": "discord-1"},
        "state_path": state_path,
        "api_key": "test-key",
        "webhook_url": "https://example.invalid/webhook",
        "interval_minutes": 10,
        "legacy_periodic_enabled": True,
    }

    first = notifier.run_once(now=datetime(2026, 8, 10, 12, 55, tzinfo=timezone.utc), **kwargs)
    second = notifier.run_once(now=datetime(2026, 8, 10, 13, 0, tzinfo=timezone.utc), **kwargs)

    assert first["status"] == "sent"
    assert second["status"] == "skipped_no_changes"
    assert len(sends) == 1
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["duplicate_suppressions"] == 1
    assert "ses-parent" in state["chats"]


def test_heartbeat_only_status_changes_do_not_defeat_dedupe(tmp_path: Path) -> None:
    notifier = load_module("progress_heartbeat_dedupe")
    sends: list[dict] = []
    state_path = tmp_path / "state.json"

    first = notifier.run_once(
        status_loader=lambda: fake_status_with_timestamp("2026-08-10T12:55:00Z"),
        chat_reader=fake_chat_view,
        summarizer=lambda **kwargs: fake_digest(kwargs["evidence"]["active_chats"]),
        discord_sender=lambda **kwargs: sends.append(kwargs["payload"]) or {"message_id": "discord-1"},
        state_path=state_path,
        api_key="test-key",
        webhook_url="https://example.invalid/webhook",
        interval_minutes=10,
        legacy_periodic_enabled=True,
        now=datetime(2026, 8, 10, 12, 55, tzinfo=timezone.utc),
    )
    second = notifier.run_once(
        status_loader=lambda: fake_status_with_timestamp("2026-08-10T12:59:59Z"),
        chat_reader=fake_chat_view,
        summarizer=lambda **kwargs: fake_digest(kwargs["evidence"]["active_chats"]),
        discord_sender=lambda **kwargs: sends.append(kwargs["payload"]) or {"message_id": "discord-2"},
        state_path=state_path,
        api_key="test-key",
        webhook_url="https://example.invalid/webhook",
        interval_minutes=10,
        legacy_periodic_enabled=True,
        now=datetime(2026, 8, 10, 13, 0, tzinfo=timezone.utc),
    )

    assert first["status"] == "sent"
    assert second["status"] == "skipped_no_changes"
    assert len(sends) == 1


def test_evidence_projection_redacts_secrets_and_omits_attachment_content() -> None:
    notifier = load_module("progress_privacy")
    view = fake_chat_view("ses-parent")
    view["messages"][0]["parts"] = [
        {
            "type": "text",
            "text": (
                "Webhook https://discord.com/api/webhooks/123/SECRET and api_key=abcd1234efgh5678 "
                "Authorization: Bearer eyJheaderaaaa.payloadbbbb.signaturecccc "
                "ghp_abcdefghijklmnopqrstuvwxyz123456 AIzaSyDabcdefghijklmnopqrstuvwxyz12 "
                "https://example.invalid/path?token=secretvalue123456 "
                "DEPLOY_TOKEN=deploysecret123456 OPENAI_API_KEY=openaisekret123456 "
                "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE AWS_SECRET_ACCESS_KEY=fakeawssecret123456 "
                "DATABASE_URL=postgres://user:databasepass123456@db.internal/openmates "
                "REDIS_URL=redis://:redispass123456@cache.internal:6379/0 "
                "-----BEGIN PRIVATE KEY-----\nfakeprivatekey1234567890\n-----END PRIVATE KEY-----"
            ),
        },
        {"type": "file", "filename": "secret.png", "content": "raw-bytes", "content_omitted": True},
    ]

    evidence = notifier.project_chat_view(
        notifier.ActiveChatRoot("ses-parent", "working", "Build notifier", "2026-08-10T12:50:00Z", []),
        view,
    )
    encoded = json.dumps(evidence)

    assert "https://discord.com/api/webhooks" not in encoded
    assert "abcd1234efgh5678" not in encoded
    assert "secretvalue123456" not in encoded
    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in encoded
    assert "AIzaSyDabcdefghijklmnopqrstuvwxyz12" not in encoded
    assert "deploysecret123456" not in encoded
    assert "openaisekret123456" not in encoded
    assert "AKIAIOSFODNN7EXAMPLE" not in encoded
    assert "fakeawssecret123456" not in encoded
    assert "databasepass123456" not in encoded
    assert "redispass123456" not in encoded
    assert "fakeprivatekey1234567890" not in encoded
    assert "-----BEGIN PRIVATE KEY-----" not in encoded
    assert "<DISCORD_WEBHOOK>" in encoded
    assert "Authorization: Bearer <REDACTED>" in encoded
    assert "<GITHUB_TOKEN>" in encoded
    assert "<GOOGLE_API_KEY>" in encoded
    assert "<PRIVATE_KEY>" in encoded
    assert "<REDACTED_URL>" in encoded
    assert "attachment content omitted" in encoded
    assert "raw-bytes" not in encoded


def test_payload_keeps_twenty_chat_links_and_disables_mentions() -> None:
    notifier = load_module("progress_payload_bounds")
    chats = [
        {
            "session_id": f"ses-{index:02d}",
            "title": f"Chat {index} @everyone [watch](me) " + ("very-long-title " * 12),
            "url": f"https://code.dev.openmates.org/{'project-segment-' * 10}/session/ses-{index:02d}",
            "status_label": "working",
            "summary": "Long active-chat summary " * 30,
            "important_decisions": ["Decision " * 20],
            "watch_points": ["Watch " * 20],
        }
        for index in range(1, 21)
    ]
    payload = notifier.build_discord_payload(
        {
            "overall_summary": "Many chats are active.",
            "important_decisions": ["Do not ping @everyone."],
            "watch_points": [],
            "chats": chats,
        },
        active_count=len(chats),
        now=datetime(2026, 8, 10, 13, 5, tzinfo=timezone.utc),
    )

    description = "\n".join(embed["description"] for embed in payload["embeds"])
    assert payload["allowed_mentions"] == {"parse": []}
    assert all(len(embed["description"]) <= notifier.MAX_DISCORD_EMBED_DESCRIPTION_CHARS for embed in payload["embeds"])
    assert sum(len(embed["title"]) + len(embed["description"]) for embed in payload["embeds"]) <= notifier.MAX_DISCORD_EMBED_TOTAL_CHARS
    assert len(payload["embeds"]) <= 9
    for index in range(1, 21):
        assert f"ses-{index:02d}" in description
    assert "...[truncated to fit Discord" not in description


def test_render_crontab_installs_fifteen_minute_once_command(tmp_path: Path) -> None:
    notifier = load_module("progress_cron")
    root = tmp_path / "OpenMates"

    rendered = notifier.render_crontab("0 1 * * * existing\n", root)

    assert notifier.CRON_BEGIN in rendered
    assert notifier.CRON_END in rendered
    assert "*/15 * * * *" in rendered
    assert "opencode_progress_notifier.py --once" in rendered
    assert "existing" in rendered
    assert rendered.count("opencode_progress_notifier.py") == 1


def test_remove_managed_cron_block_removes_legacy_progress_schedule() -> None:
    notifier = load_module("progress_cron_remove")
    existing = "\n".join(
        [
            "0 1 * * * existing-job",
            notifier.CRON_BEGIN,
            "# Every 15 minutes.",
            "*/15 * * * * cd /repo && python3 /repo/scripts/opencode_progress_notifier.py --once",
            notifier.CRON_END,
            "15 2 * * * keep-me",
        ]
    )

    rendered = "\n".join(notifier._remove_managed_cron_block(existing.splitlines()))

    assert "opencode_progress_notifier.py" not in rendered
    assert notifier.CRON_BEGIN not in rendered
    assert "existing-job" in rendered
    assert "keep-me" in rendered
