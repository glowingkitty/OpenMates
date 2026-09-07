# contract-test-file: tooling
"""Verify test selection is bound to the published candidate.

Dirty local tests must neither enter nor alter a requested commit's inventory.
The fixture repository is disposable and does not dispatch any GitHub jobs.
Existing daily AI policy remains authoritative for scheduled selection.
See docs/plans/isolated-github-tests/plan.yml.
"""

from types import SimpleNamespace
import subprocess
import pytest
from scripts.ci_dispatch import select_specs
from test_ci_source import repository


def test_selection_reads_immutable_source(tmp_path):
    root = repository(tmp_path)
    tests = root / "frontend/apps/web_app/tests"
    tests.mkdir(parents=True)
    (tests / "present.spec.ts").write_text("// original")
    (root / "scripts").mkdir()
    (root / "scripts/daily_ai_test_manifest.json").write_text("{}")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=CI",
            "-c",
            "user.email=ci@example.com",
            "commit",
            "-m",
            "subject",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    (tests / "present.spec.ts").unlink()
    (tests / "dirty.spec.ts").write_text("// untested")
    assert select_specs(
        root, SimpleNamespace(spec=["present.spec.ts"], daily=False), source
    ) == ["present.spec.ts"]
    with pytest.raises(ValueError, match="Unknown E2E"):
        select_specs(root, SimpleNamespace(spec=["dirty.spec.ts"], daily=False), source)


def test_migration_hold_fails_before_source_publication(tmp_path, monkeypatch):
    from scripts import ci_dispatch

    root = repository(tmp_path)
    monkeypatch.setattr(
        ci_dispatch,
        "ensure_coordinator",
        lambda *_: pytest.fail("HOLD cannot start a dispatcher"),
    )
    with pytest.raises(RuntimeError, match="migration HOLD"):
        ci_dispatch.run(
            [
                "--worktree",
                str(root),
                "--session",
                "fixture",
                "--spec",
                "present.spec.ts",
            ]
        )


def test_daily_units_queue_while_e2e_hold_is_reported(tmp_path, monkeypatch, capsys):
    from scripts import ci_dispatch
    from scripts.ci_coordinator import Queue

    root = repository(tmp_path)
    source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    monkeypatch.setattr(ci_dispatch, "select_specs", lambda *_: ["held.spec.ts"])
    monkeypatch.setattr(ci_dispatch, "ensure_coordinator", lambda *_: None)
    result = ci_dispatch.run(
        ["--worktree", str(root), "--daily", "--expected-commit", source, "--detach"]
    )
    assert result == 2
    assert "held.spec.ts" in capsys.readouterr().out
    jobs = Queue(root / "logs/ci-coordinator/queue.sqlite3").status()
    assert sorted(job["mode"] for job in jobs) == ["pytest", "vitest"]
