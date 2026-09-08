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


def test_partial_cutover_queues_core_and_reports_cloud_hold(tmp_path, monkeypatch, capsys):
    import json
    from scripts import ci_dispatch
    from scripts.ci_coordinator import Queue

    root = repository(tmp_path)
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    cutover = root / "logs/ci-coordinator/cutover.json"
    cutover.parent.mkdir(parents=True)
    cutover.write_text(json.dumps({"ready": True}))
    monkeypatch.setattr(ci_dispatch, "select_specs", lambda *_: [
        "tasks-flow.spec.ts", "anonymous-production-repair.spec.ts"
    ])
    monkeypatch.setattr(ci_dispatch, "ensure_coordinator", lambda *_: None)
    result = ci_dispatch.run([
        "--worktree", str(root), "--expected-commit", source,
        "--spec", "tasks-flow.spec.ts", "--detach"
    ])
    assert result == 2
    assert "official-cloud" in capsys.readouterr().out
    jobs = Queue(root / "logs/ci-coordinator/queue.sqlite3").status()
    assert len(jobs) == 1
    assert json.loads(jobs[0]["specs"]) == ["tasks-flow.spec.ts"]


def test_daily_discovery_includes_nested_component_specs(tmp_path, monkeypatch):
    from scripts import ci_dispatch, daily_ai_test_policy
    folder = tmp_path / "frontend/apps/web_app/tests/components"
    folder.mkdir(parents=True)
    (folder / "nested.spec.ts").write_text("// isolated component")
    monkeypatch.setattr(daily_ai_test_policy, "load_manifest", lambda *_: {})
    monkeypatch.setattr(daily_ai_test_policy, "discover_specs", lambda names, **kwargs: list(names))
    monkeypatch.setattr(daily_ai_test_policy, "daily_plan", lambda *args, **kwargs: SimpleNamespace(selected=[]))
    assert ci_dispatch.select_snapshot_specs(tmp_path, SimpleNamespace(spec=[], daily=True)) == ["components/nested.spec.ts"]


def test_cold_daily_discovers_actual_inventory_without_legacy_accounts(monkeypatch):
    from pathlib import Path
    from scripts import ci_dispatch
    from scripts.ci_coverage import partition

    for key in tuple(ci_dispatch.os.environ):
        if key.startswith(("TEST_ACCOUNT", "OPENMATES_TEST_ACCOUNT_")):
            monkeypatch.delenv(key)
    root = Path(ci_dispatch.__file__).resolve().parents[1]
    selected = ci_dispatch.select_snapshot_specs(root, SimpleNamespace(spec=[], daily=True))
    admitted, held = partition(selected)
    assert "account-interests-settings.spec.ts" in admitted
    assert "import-account-v1.spec.ts" in admitted
    assert "prod-smoke/prod-smoke-signup-giftcard-chat.spec.ts" not in selected
    assert "daily-ai-fixed-canary.spec.ts" in held
    assert "daily-ai-rotating-canary.spec.ts" in held
