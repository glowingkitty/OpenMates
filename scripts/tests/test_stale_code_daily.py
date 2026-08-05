#!/usr/bin/env python3
"""
Tests for report-only stale-code scheduling and Discord notification.

The daily runner must preserve local evidence on every path, redact notification
content, install one idempotent cron entry, and never dispatch an editing agent.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "stale_code_daily.py"


def load_module():
    spec = importlib.util.spec_from_file_location("openmates_stale_code_daily", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sample_report() -> dict:
    return {
        "status": "ok",
        "total_found": 3,
        "summary": {
            "python": {
                "count": 3,
                "deletion_ready": 1,
                "review_only": 1,
                "suppressed": 1,
                "auto_fixable": 1,
            }
        },
        "errors": [],
        "analyzers": {"ruff": "ok"},
        "items": [
            {
                "file": "backend/example.py",
                "line": 4,
                "code": "SensitiveLookingName",
                "message": "source snippet must stay local",
                "classification": "deletion_ready",
                "fingerprint": "a" * 64,
            }
        ],
    }


def test_reports_are_written_atomically_and_discord_is_redacted(tmp_path: Path) -> None:
    module = load_module()
    report = sample_report()

    json_path, markdown_path = module.write_reports(
        report,
        "# Local details\nsource snippet must stay local\n",
        tmp_path,
        commit="abcdef123456",
    )
    payload = module.build_discord_payload(report, "abcdef123456", json_path)

    stored = json.loads(json_path.read_text(encoding="utf-8"))
    assert stored["subject_commit"] == "abcdef123456"
    assert markdown_path.read_text(encoding="utf-8").startswith("# Local details")
    encoded = json.dumps(payload)
    assert "SensitiveLookingName" not in encoded
    assert "source snippet" not in encoded
    assert "1 deletion-ready" in encoded
    assert str(tmp_path) not in encoded
    assert "stale-code.json" in encoded
    assert not list(tmp_path.glob("*.tmp"))


def test_missing_webhook_is_visible_skip_not_failure() -> None:
    module = load_module()

    status = module.notify_discord(sample_report(), "abcdef12", Path("logs/nightly-reports/stale-code.json"), "")

    assert status == "skipped_missing_webhook"


def test_discord_failure_does_not_remove_local_reports(tmp_path: Path) -> None:
    module = load_module()
    report = sample_report()
    json_path, _markdown_path = module.write_reports(report, "# report\n", tmp_path, commit="abcdef12")

    def fail_request(*_args, **_kwargs):
        raise OSError("network unavailable")

    status = module.notify_discord(
        report,
        "abcdef12",
        json_path,
        "https://discord.invalid/<PLACEHOLDER>",
        opener=fail_request,
    )

    assert status.startswith("failed:")
    assert json_path.exists()


def test_cron_rendering_is_idempotent_and_removes_legacy_auto_removal() -> None:
    module = load_module()
    existing = (
        "15 5 * * * /other/job\n"
        "0 9 * * * /custom/nightly-dead-code-removal.sh --audit-only\n"
        "#DISABLED 0 2 * * 1-5 /repo/scripts/nightly-dead-code-removal.sh\n"
    )
    root = Path("/srv/openmates")

    first = module.render_crontab(existing, root)
    second = module.render_crontab(first, root)

    assert first == second
    assert first.count(module.CRON_BEGIN) == 1
    assert first.count("scripts/stale_code_daily.py") == 1
    assert "/custom/nightly-dead-code-removal.sh" in first
    assert "/repo/scripts/nightly-dead-code-removal.sh" not in first
    assert "0 2 * * *" in first
    assert "logs/stale-code-daily.log" in first
    assert "/other/job" in first


def test_cron_rendering_rejects_malformed_managed_block() -> None:
    module = load_module()
    malformed = f"0 1 * * * /before\n{module.CRON_BEGIN}\n0 3 * * * /must-not-disappear\n"

    with pytest.raises(ValueError, match="managed cron block"):
        module.render_crontab(malformed, Path("/srv/openmates"))


def test_cron_command_quotes_apostrophe_paths_without_sourcing_env() -> None:
    module = load_module()
    rendered = module.render_crontab("", Path("/srv/open'mates"))
    cron_line = next(line for line in rendered.splitlines() if "stale_code_daily.py" in line)
    command = " ".join(cron_line.split()[5:])

    assert ".env" not in cron_line
    assert subprocess.run(["bash", "-n", "-c", command], check=False).returncode == 0


def test_canonical_checkout_root_uses_git_common_directory() -> None:
    module = load_module()

    assert module.root_from_common_git_dir(Path("/srv/openmates/.git"), Path("/tmp/worktree")) == Path("/srv/openmates")
    assert module.root_from_common_git_dir(Path("/tmp/not-dot-git"), Path("/tmp/worktree")) == Path("/tmp/worktree")


def test_runner_source_has_no_agent_or_deploy_dispatch() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")

    assert "run_opencode_session" not in source
    assert "sessions.py deploy" not in source
    assert "git commit" not in source
    assert "git push" not in source


def test_detector_exception_writes_failure_report(tmp_path: Path, monkeypatch) -> None:
    module = load_module()

    def fail_scan(*_args, **_kwargs):
        raise RuntimeError("detector exploded")

    monkeypatch.setattr(module, "scan_repository", fail_scan)

    result = module.run_daily(tmp_path, tmp_path / "reports", 10, dry_run_notify=True)

    stored = json.loads((tmp_path / "reports" / "stale-code.json").read_text(encoding="utf-8"))
    assert result == 1
    assert stored["status"] == "error"
    assert stored["errors"] == ["Detector failed: RuntimeError"]
    assert (tmp_path / "reports" / "stale-code.md").exists()


def test_run_lock_rejects_overlapping_execution(tmp_path: Path) -> None:
    module = load_module()

    with module.run_lock(tmp_path):
        with pytest.raises(module.AlreadyRunningError):
            with module.run_lock(tmp_path):
                pass


def test_cleanup_skill_forbids_file_wide_ruff_fix() -> None:
    skill = (ROOT / ".claude/skills/remove-stale-code/SKILL.md").read_text(encoding="utf-8")

    assert "ruff check --select F401 --fix <file>" not in skill
    assert "selected import statement" in skill
