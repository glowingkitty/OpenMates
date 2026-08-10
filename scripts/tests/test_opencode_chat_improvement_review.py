#!/usr/bin/env python3
# contract-test-file: tooling
"""Contract tests for manual OpenCode workflow improvement research.

The manual path may inspect bounded local transcripts, ask GPT-5.6 Luna for
research, publish gitignored reports, and optionally notify Discord. Retired
cron plumbing must not re-enable unattended reports or invoke implementation.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "scripts" / "opencode_chat_improvement_review.py"
WORKFLOW_HELPER_PATH = ROOT / "scripts" / "_workflow_review_helper.py"
OPENCODE_HELPER_PATH = ROOT / "scripts" / "_opencode_utils.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def create_transcript_fixture(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE session ("
        "id TEXT PRIMARY KEY, directory TEXT, parent_id TEXT, title TEXT, "
        "time_created INTEGER, time_updated INTEGER);"
        "CREATE TABLE message ("
        "id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, "
        "time_updated INTEGER, data TEXT);"
        "CREATE TABLE part ("
        "id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT, "
        "time_created INTEGER, time_updated INTEGER, data TEXT);"
    )
    inside = 1_783_073_000_000
    outside = 1_782_900_000_000
    connection.executemany(
        "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("ses-parent", str(ROOT), None, "Parent workflow", inside, inside),
            ("ses-child", str(ROOT), "ses-parent", "Delegated review", inside, inside),
            ("ses-analyzer", str(ROOT), None, "Analyzer", inside, inside),
            ("ses-old", str(ROOT), None, "Old", outside, outside),
            ("ses-other", "/other/repository", None, "Other", inside, inside),
        ],
    )
    connection.executemany(
        "INSERT INTO message VALUES (?, ?, ?, ?, ?)",
        [
            ("msg-parent", "ses-parent", inside, inside, json.dumps({"role": "user", "summary": "Fix the hook"})),
            ("msg-child", "ses-child", inside, inside, json.dumps({"role": "assistant", "model": "gpt-5.6-terra"})),
            ("msg-analyzer", "ses-analyzer", inside, inside, json.dumps({"role": "user"})),
        ],
    )
    connection.executemany(
        "INSERT INTO part VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("part-parent", "msg-parent", "ses-parent", inside, inside, json.dumps({"type": "text", "text": "The hook failed twice"})),
            ("part-child", "msg-child", "ses-child", inside, inside, json.dumps({"type": "tool", "tool": "read", "state": {"status": "error", "error": "missing file"}})),
            ("part-analyzer", "msg-analyzer", "ses-analyzer", inside, inside, json.dumps({"type": "text", "text": "must be excluded"})),
        ],
    )
    connection.commit()
    connection.close()


def test_collector_includes_children_and_excludes_analyzer(tmp_path, monkeypatch) -> None:
    helper = load_module(WORKFLOW_HELPER_PATH, "workflow_review_transcripts")
    database = tmp_path / "opencode.db"
    create_transcript_fixture(database)
    monkeypatch.setattr(helper, "OPENCODE_DB_PATH", database)
    monkeypatch.setattr(helper, "PROJECT_ROOT", ROOT)

    evidence = helper.collect_transcript_evidence(
        "2026-07-03T00:00:00Z",
        "2026-07-04T00:00:00Z",
        exclude_session_ids={"ses-analyzer"},
    )

    assert evidence["session_count"] == 2
    assert [session["session_id"] for session in evidence["sessions"]] == ["ses-parent", "ses-child"]
    assert evidence["sessions"][1]["parent_session_id"] == "ses-parent"
    assert evidence["sessions"][1]["root_session_id"] == "ses-parent"
    encoded = json.dumps(evidence)
    assert "The hook failed twice" in encoded
    assert "missing file" in encoded
    assert "must be excluded" not in encoded
    assert "Old" not in encoded
    assert "Other" not in encoded


def test_collector_enforces_deterministic_bounds(tmp_path, monkeypatch) -> None:
    helper = load_module(WORKFLOW_HELPER_PATH, "workflow_review_bounds")
    database = tmp_path / "opencode.db"
    create_transcript_fixture(database)
    monkeypatch.setattr(helper, "OPENCODE_DB_PATH", database)
    monkeypatch.setattr(helper, "PROJECT_ROOT", ROOT)

    evidence = helper.collect_transcript_evidence(
        "2026-07-03T00:00:00Z",
        "2026-07-04T00:00:00Z",
        max_sessions=1,
        max_parts=1,
        max_field_chars=8,
        max_total_bytes=4_096,
    )

    assert evidence["session_count"] == 1
    assert evidence["limits"]["max_sessions"] == 1
    assert evidence["truncated"]["sessions"] is True
    assert evidence["truncated"]["fields"] is True
    assert len(json.dumps(evidence).encode("utf-8")) <= 4_096


def test_collector_applies_exclusions_before_sql_limit(tmp_path, monkeypatch) -> None:
    helper = load_module(WORKFLOW_HELPER_PATH, "workflow_review_sql_exclusions")
    database = tmp_path / "opencode.db"
    create_transcript_fixture(database)
    monkeypatch.setattr(helper, "OPENCODE_DB_PATH", database)
    monkeypatch.setattr(helper, "PROJECT_ROOT", ROOT)

    evidence = helper.collect_transcript_evidence(
        "2026-07-03T00:00:00Z",
        "2026-07-04T00:00:00Z",
        exclude_session_ids={"ses-analyzer", "ses-child"},
        max_sessions=1,
    )

    assert evidence["session_count"] == 1
    assert evidence["sessions"][0]["session_id"] == "ses-parent"


def test_dispatch_passes_explicit_luna_model(tmp_path, monkeypatch) -> None:
    helper = load_module(OPENCODE_HELPER_PATH, "opencode_utils_model")
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, '{"sessionID":"ses-research"}\n', "")

    monkeypatch.setattr(helper.subprocess, "run", fake_run)

    returncode, session_id = helper.run_opencode_session(
        prompt="Research this bounded evidence.",
        session_title="daily improvement review",
        project_root=str(tmp_path),
        log_prefix="[review]",
        agent="cron-research",
        model="openai/gpt-5.6-luna",
    )

    command = captured["command"]
    assert returncode == 0
    assert session_id == "ses-research"
    assert command[command.index("--model") + 1] == "openai/gpt-5.6-luna"
    assert command[command.index("--agent") + 1] == "cron-research"
    assert "--dangerously-skip-permissions" not in command


def test_dispatch_streams_bounded_output_without_full_buffering() -> None:
    helper = load_module(OPENCODE_HELPER_PATH, "opencode_utils_bounded_output")
    event = json.dumps({"sessionID": "ses-bounded", "type": "text"})

    returncode, output, session_id, timed_out = helper._run_bounded_output(
        [sys.executable, "-c", f"print('x' * 500); print({event!r})"],
        cwd=str(ROOT),
        env=dict(os.environ),
        timeout=10,
        max_chars=100,
    )

    assert returncode == 0
    assert timed_out is False
    assert session_id == "ses-bounded"
    assert len(output) <= 100
    assert event in output


def test_dispatch_bounds_oversized_line_without_newline() -> None:
    helper = load_module(OPENCODE_HELPER_PATH, "opencode_utils_oversized_line")
    event = json.dumps({"sessionID": "ses-no-newline", "type": "text"})

    returncode, output, session_id, timed_out = helper._run_bounded_output(
        [sys.executable, "-c", f"import sys; sys.stdout.write('x' * 1_000_000 + {event!r})"],
        cwd=str(ROOT),
        env=dict(os.environ),
        timeout=10,
        max_chars=200,
    )

    assert returncode == 0
    assert timed_out is False
    assert session_id == "ses-no-newline"
    assert len(output) <= 200
    assert event in output


def test_reporting_publishes_latest_and_dated_artifacts(tmp_path) -> None:
    runner = load_module(RUNNER_PATH, "opencode_improvement_reporting")
    report = {
        "status": "ok",
        "period": {"start": "2026-07-03T00:00:00Z", "end": "2026-07-04T00:00:00Z"},
        "model": "openai/gpt-5.6-luna",
        "recommendations": [{"id": "REC-1", "priority": "high", "title": "Improve hook guidance"}],
    }

    paths = runner.write_reports(report, "# Improvement report\n", tmp_path)

    assert paths.json_latest == tmp_path / "latest.json"
    assert paths.markdown_latest == tmp_path / "latest.md"
    assert paths.json_latest.is_file()
    assert paths.markdown_latest.is_file()
    assert paths.json_dated.is_file()
    assert paths.markdown_dated.is_file()
    assert json.loads(paths.json_latest.read_text(encoding="utf-8"))["model"] == "openai/gpt-5.6-luna"
    assert not list(tmp_path.glob("*.tmp"))


def test_reporting_parses_structured_final_jsonl_response(tmp_path) -> None:
    runner = load_module(RUNNER_PATH, "opencode_improvement_jsonl")
    output = tmp_path / "analysis.jsonl"
    output.write_text(
        json.dumps({"type": "text", "part": {"type": "text", "text": "progress"}})
        + "\n"
        + json.dumps(
            {
                "type": "text",
                "part": {
                    "type": "text",
                    "text": '```json\n{"summary":"complete","recommendations":[]}\n```',
                    "metadata": {"openai": {"phase": "final_answer"}},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert runner._parse_analysis_output(output) == {"summary": "complete", "recommendations": []}


def test_reporting_caps_recommendations_at_ten() -> None:
    runner = load_module(RUNNER_PATH, "opencode_improvement_limit")
    raw = [
        {"id": f"REC-{index}", "title": f"Recommendation {index}", "category": "hook", "priority": "low"}
        for index in range(1, 12)
    ]

    recommendations = runner._validate_recommendations(raw)

    assert len(recommendations) == 10
    assert recommendations[-1]["id"] == "REC-10"


def test_reporting_normalizes_untrusted_priority_and_field_sizes() -> None:
    runner = load_module(RUNNER_PATH, "opencode_improvement_schema_bounds")
    recommendation = {
        "id": "I" * 500,
        "priority": "PRIVATE_TRANSCRIPT",
        "category": "hook",
        "title": "T" * 500,
        "evidence": "E" * 10_000,
        "target_files": ["x" * 1_000] * 30,
        "unexpected": "must not survive",
    }

    normalized = runner._validate_recommendations([recommendation])[0]

    assert normalized["priority"] == "low"
    assert len(normalized["id"]) < 80
    assert len(normalized["title"]) < 230
    assert len(normalized["evidence"]) < 4_050
    assert len(normalized["target_files"]) == 20
    assert "unexpected" not in normalized


def test_reporting_discord_payload_is_bounded_and_attaches_markdown(tmp_path) -> None:
    runner = load_module(RUNNER_PATH, "opencode_improvement_discord")
    report = {
        "status": "ok",
        "period": {"start": "2026-07-03T00:00:00Z", "end": "2026-07-04T00:00:00Z"},
        "model": "openai/gpt-5.6-luna",
        "source_counts": {"sessions": 12, "parts": 300},
        "recommendations": [
            {"id": "REC-1", "priority": "high", "title": "A" * 5000},
            {"id": "REC-2", "priority": "medium", "title": "Do not expose PRIVATE_TRANSCRIPT"},
        ],
    }
    markdown = tmp_path / "latest.md"
    markdown.write_text("# Local report\nPRIVATE_TRANSCRIPT\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_post_attachment(**kwargs):
        captured.update(kwargs)
        return {"message_id": "discord-message", "attachment_id": "discord-attachment"}

    status = runner.notify_discord(
        report,
        markdown,
        "https://discord.invalid/<PLACEHOLDER>",
        attachment_sender=fake_post_attachment,
        text_sanitizer=lambda text: text.replace("PRIVATE_TRANSCRIPT", "[REDACTED]"),
    )

    payload = captured["payload"]
    assert status == "sent"
    assert captured["filename"].endswith(".md")
    assert b"PRIVATE_TRANSCRIPT" not in captured["content"]
    assert b"[REDACTED]" in captured["content"]
    assert len(payload["content"]) <= 1900
    assert "PRIVATE_TRANSCRIPT" not in payload["content"]


def test_reporting_missing_or_failed_discord_is_visible(tmp_path) -> None:
    runner = load_module(RUNNER_PATH, "opencode_improvement_discord_failures")
    markdown = tmp_path / "latest.md"
    markdown.write_text("# Report\n", encoding="utf-8")
    report = {"status": "analysis_failed", "period": {}, "model": "openai/gpt-5.6-luna", "recommendations": []}

    assert runner.notify_discord(report, markdown, "") == "skipped_missing_webhook"
    assert runner.notify_discord(
        report,
        markdown,
        "https://discord.invalid",
        attachment_sender=lambda **_kwargs: None,
        text_sanitizer=lambda text: text,
    ) == "failed"
    assert runner.notify_discord(
        report,
        markdown,
        "https://discord.invalid",
        attachment_sender=lambda **_kwargs: (_ for _ in ()).throw(OSError("network")),
        text_sanitizer=lambda text: text,
    ) == "failed:OSError"
    assert markdown.is_file()


def test_reporting_runner_persists_final_notification_status(tmp_path, monkeypatch) -> None:
    runner = load_module(RUNNER_PATH, "opencode_improvement_run_review")
    root = tmp_path / "repo"
    output_dir = root / "logs" / "nightly-reports" / "opencode-improvements"
    prompt = tmp_path / "prompt.md"
    prompt.write_text(
        "{{PERIOD_START}} {{PERIOD_END}} {{SUBJECT_COMMIT}} {{TRANSCRIPT_EVIDENCE}}",
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "PROMPT_TEMPLATE", prompt)
    monkeypatch.setattr(runner, "canonical_checkout_root", lambda value: value)
    monkeypatch.setattr(runner, "_git_commit", lambda _root: "abc123")
    monkeypatch.setattr(
        runner,
        "collect_transcript_evidence",
        lambda *_args, **_kwargs: {
            "status": "ok",
            "session_count": 1,
            "message_count": 1,
            "part_count": 1,
            "sessions": [],
            "limits": {"max_total_bytes": 4_096},
            "truncated": {},
        },
    )

    def fake_run_opencode_session(**kwargs):
        capture = Path(kwargs["capture_output_path"])
        capture.parent.mkdir(parents=True, exist_ok=True)
        capture.write_text(
            json.dumps(
                {
                    "type": "text",
                    "part": {"type": "text", "text": '{"summary":"ok","recommendations":[]}'},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        assert kwargs["agent"] == "cron-research"
        assert kwargs["model"] == "openai/gpt-5.6-luna"
        return 0, "ses-live"

    monkeypatch.setattr(runner, "run_opencode_session", fake_run_opencode_session)
    monkeypatch.setattr(runner, "notify_discord", lambda *_args, **_kwargs: "failed:OSError")
    monkeypatch.setattr(runner, "_dotenv_value", lambda *_args: "https://discord.invalid/<PLACEHOLDER>")
    monkeypatch.setattr(runner, "write_nightly_report", lambda **_kwargs: None)

    returncode, paths = runner.run_review(root, output_dir, hours=24, dry_run_notify=False)

    stored = json.loads(paths.json_latest.read_text(encoding="utf-8"))
    assert returncode == 0
    assert stored["status"] == "ok"
    assert stored["notification_status"] == "failed:OSError"
    assert stored["analysis_session_id"] == "ses-live"
    assert stored["markdown_sha256"]


def test_main_defaults_to_weekly_manual_interval(monkeypatch) -> None:
    runner = load_module(RUNNER_PATH, "opencode_improvement_manual_default")
    captured: dict[str, object] = {}

    def fake_run_review(project_root, output_dir, *, hours, dry_run_notify, excluded_session_ids):
        captured.update(
            {
                "project_root": project_root,
                "output_dir": output_dir,
                "hours": hours,
                "dry_run_notify": dry_run_notify,
                "excluded_session_ids": excluded_session_ids,
            }
        )
        return 0, SimpleNamespace(json_latest=Path("latest.json"), markdown_latest=Path("latest.md"))

    monkeypatch.setattr(runner, "run_review", fake_run_review)
    monkeypatch.setattr(sys, "argv", ["opencode_chat_improvement_review.py", "--dry-run-notify"])

    assert runner.main() == 0
    assert captured["hours"] == 168
    assert captured["dry_run_notify"] is True


def test_cron_rendering_removes_retired_managed_job() -> None:
    runner = load_module(RUNNER_PATH, "opencode_improvement_cron")
    existing = "\n".join(
        [
            "15 5 * * * /other/job",
            runner.CRON_BEGIN,
            "# Daily at 01:45 UTC. Automatic research and notification only; tracked changes require manual review.",
            "45 1 * * * cd /srv/openmates && python3 /srv/openmates/scripts/opencode_chat_improvement_review.py --hours 24",
            runner.CRON_END,
            "",
        ]
    )
    root = Path("/srv/openmates")

    first = runner.render_crontab(existing, root)
    second = runner.render_crontab(first, root)

    assert first == second
    assert runner.CRON_BEGIN not in first
    assert runner.CRON_END not in first
    assert "scripts/opencode_chat_improvement_review.py" not in first
    assert "implement-opencode-improvements" not in first
    assert "sessions.py deploy" not in first
    assert "git commit" not in first
    assert "/other/job" in first


def test_cron_installation_is_retired() -> None:
    runner = load_module(RUNNER_PATH, "opencode_improvement_cron_install")

    with pytest.raises(RuntimeError, match="retired"):
        runner.install_cron(Path("/srv/openmates"))


def test_cron_source_has_no_implementation_or_deploy_path() -> None:
    source = RUNNER_PATH.read_text(encoding="utf-8")

    assert "sessions.py deploy" not in source
    assert "git commit" not in source
    assert "git push" not in source


def test_cron_research_agent_denies_mutating_tools() -> None:
    config = json.loads((ROOT / "opencode.json").read_text(encoding="utf-8"))
    agent = config["agent"]["cron-research"]

    assert agent["mode"] == "primary"
    assert agent["permission"]["*"] == "deny"
    assert agent["permission"]["edit"] == "deny"
    assert agent["permission"]["bash"] == "deny"
    assert agent["permission"]["task"] == "deny"
    assert agent["permission"]["question"] == "deny"


def test_skills_separate_research_from_user_triggered_implementation() -> None:
    research = (ROOT / ".claude/skills/opencode-improvement-research/SKILL.md").read_text(encoding="utf-8")
    manual = (ROOT / ".claude/skills/opencode-workflow-review/SKILL.md").read_text(encoding="utf-8")
    implementation = (ROOT / ".claude/skills/implement-opencode-improvements/SKILL.md").read_text(encoding="utf-8")

    assert "user-invocable: false" in research
    assert "openai/gpt-5.6-luna" in research
    assert "must not edit tracked files" in research.lower()
    assert "user-invocable: true" in manual
    assert "opencode_chat_improvement_review.py --hours 168 --dry-run-notify" in manual
    assert "must not edit tracked files" in manual.lower()
    assert "user-invocable: true" in implementation
    assert "explicit" in implementation.lower()
    assert "revalid" in implementation.lower()
    assert "scripts/sessions.py start" in implementation
