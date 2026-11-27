# contract-test-file: tooling
"""Per-category disk budgets (scripts/host_disk_budgets.py): oldest first, never what is in use."""

from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import host_disk_budgets as budgets  # noqa: E402 - repo-local modules, path set just above
import host_disk_usage as usage  # noqa: E402

GB = usage.GB
NOW = 2_000_000_000.0
HOUR = 3600


def _folder(path: Path, age_hours: float) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "file").write_text("x")
    stamp = NOW - age_hours * HOUR
    for item in (path / "file", path):
        os.utime(item, (stamp, stamp))
    return path


def _report() -> dict:
    return {"deleted": [], "skipped": {"recent": 0, "in_use": 0, "permission": 0}, "failures": []}


def test_trim_removes_least_recently_used_first_until_the_target(tmp_path):
    units = [budgets.Unit(_folder(tmp_path / name, age), NOW - age * HOUR)
             for name, age in (("new", 2), ("oldest", 30), ("old", 10))]
    report = _report()
    left = budgets.trim(units, 30 * GB, 12 * GB, apply=True, now=NOW, idle=HOUR, protected=lambda unit: None,
                        report=report, category="rust", size=lambda path: 10 * GB)
    assert left == 10 * GB
    assert [Path(item["path"]).name for item in report["deleted"]] == ["oldest", "old"]
    assert (tmp_path / "new").is_dir() and not (tmp_path / "oldest").exists()


def test_trim_skips_recent_and_protected_units(tmp_path):
    units = [budgets.Unit(_folder(tmp_path / "busy", 30), NOW - 30 * HOUR),
             budgets.Unit(_folder(tmp_path / "fresh", 0.5), NOW - 0.5 * HOUR)]
    report = _report()
    left = budgets.trim(units, 30 * GB, 0, apply=True, now=NOW, idle=HOUR,
                        protected=lambda unit: "cargo_running" if unit.path.name == "busy" else None,
                        report=report, category="rust", size=lambda path: GB)
    assert left == 30 * GB and report["deleted"] == []
    assert report["skipped"] == {"recent": 1, "in_use": 0, "permission": 0, "cargo_running": 1}


def test_report_mode_removes_nothing(tmp_path):
    unit = budgets.Unit(_folder(tmp_path / "old", 30), NOW - 30 * HOUR)
    report = _report()
    budgets.trim([unit], 2 * GB, 0, apply=False, now=NOW, idle=HOUR, protected=lambda unit: None,
                 report=report, category="rust", size=lambda path: GB)
    assert len(report["deleted"]) == 1 and unit.path.is_dir()


@pytest.fixture
def host(tmp_path, monkeypatch):
    """A fake projects folder: canonical checkout, two worktrees with targets, CI runs, scratch."""
    projects = tmp_path / "projects"
    repo = projects / "OpenMates"
    worktrees = repo / ".openmates-agent-worktrees"
    targets = {"busy": _folder(worktrees / "agent-busy/target", 30),
               "idle": _folder(worktrees / "agent-idle/target", 40),
               "cache": _folder(tmp_path / "home/.cache/openmates-rust-target/host", 50)}
    for worktree in ("agent-busy", "agent-idle"):
        _folder(worktrees / worktree / "src", 30)
    for name, age in (("run-old", 90), ("run-held", 100), ("run-new", 0.2)):
        _folder(repo / "test-results/ci-runs" / name, age)
    scratch = tmp_path / "scratch"
    for chat, entries in (("chat-a", (("big-old", 20), ("big-new", 1))), ("chat-b", (("small", 30),))):
        for name, age in entries:
            _folder(scratch / "-project" / chat / "scratchpad" / name, age)
    monkeypatch.setattr(usage, "HOME", tmp_path / "home")
    monkeypatch.setattr(budgets, "SHARED_RUST_ROOT", tmp_path / "home/.cache/openmates-rust-target")
    monkeypatch.setattr(usage, "rust_paths", lambda projects_: [str(p) for p in (targets["busy"], targets["idle"])]
                        + [str(tmp_path / "home/.cache/openmates-rust-target")])
    monkeypatch.setattr(usage, "filesystem", lambda path: {"percent": 60.0})
    sizes = {"agent-busy": 12, "agent-idle": 12, "host": 12, "run-old": 3, "run-held": 3, "run-new": 3,
             "big-old": 1.5, "big-new": 1, "small": 0.1, "chat-a": 2.5, "chat-b": 0.1}
    monkeypatch.setattr(budgets, "_size", lambda path: int(sizes.get(path.name, sizes.get(path.parent.name, 0)) * GB))
    monkeypatch.setattr(usage, "du_bytes", lambda path: int(sizes.get(Path(path).name, 0) * GB))
    return {"repo": repo, "targets": targets, "scratch": scratch, "worktrees": worktrees}


def _enforce(host, totals, *, cargo=(), references=frozenset(), apply=True):
    return budgets.enforce(host["repo"], apply=apply, in_use=[], cargo=list(cargo), references=set(references),
                           now=NOW, scratch_root=host["scratch"], measure=lambda cats: totals)


def test_rust_over_budget_loses_the_least_recently_used_target_but_never_one_cargo_uses(host):
    report = _enforce(host, {"rust": 40 * GB}, cargo=[str(host["worktrees"] / "agent-idle")])
    deleted = [item["path"] for item in report["deleted"] if item["category"] == "rust"]
    # Oldest is the shared cache subfolder (50 h), then agent-idle (40 h, but cargo works in
    # that worktree), then agent-busy (30 h): 40 - 12 - 12 = 16 GB <= 25 GB.
    assert deleted == [str(host["targets"]["cache"]), str(host["targets"]["busy"])]
    assert report["skipped"]["cargo_running"] == 1
    assert report["categories"]["rust"] == {"before": 40 * GB, "after": 16 * GB, "target": 25 * GB}
    assert host["targets"]["idle"].is_dir() and not host["targets"]["cache"].exists()


def test_under_budget_nothing_is_touched(host):
    report = _enforce(host, {"rust": 20 * GB, "ci_artifacts": 9 * GB, "scratchpads": 2 * GB, "worktrees": GB})
    assert [item for item in report["deleted"] if item["category"] != "scratchpads"] == []


def test_ci_runs_go_oldest_first_except_those_a_live_job_references(host):
    report = _enforce(host, {"ci_artifacts": 12 * GB}, references={"run-held"})
    assert [Path(item["path"]).name for item in report["deleted"] if item["category"] == "ci_artifacts"] == ["run-old"]
    assert (host["repo"] / "test-results/ci-runs/run-held").is_dir()


def test_unreadable_ci_queue_skips_ci_artifacts(host):
    report = budgets.enforce(host["repo"], apply=True, in_use=[], cargo=[], references=None, now=NOW,
                             scratch_root=host["scratch"], measure=lambda cats: {"ci_artifacts": 30 * GB})
    assert "ci_artifacts" not in report["categories"] and report["skipped"]["queue_unreadable"] == 1


def test_a_chat_over_its_2_gb_scratch_share_loses_its_oldest_idle_entry(host):
    report = _enforce(host, {"scratchpads": 2.6 * GB})
    assert [Path(item["path"]).name for item in report["deleted"]] == ["big-old"]
    assert (host["scratch"] / "-project/chat-a/scratchpad/big-new").is_dir()


def test_pressure_from_75_percent_aims_at_80_percent_of_each_cap(host, monkeypatch):
    monkeypatch.setattr(usage, "filesystem", lambda path: {"percent": 76.0})
    report = _enforce(host, {"rust": 24 * GB})
    assert report["pressure"] is True and report["categories"]["rust"]["target"] == 20 * GB
    assert [item["path"] for item in report["deleted"] if item["category"] == "rust"] == [str(host["targets"]["cache"])]


def test_dependency_folders_of_idle_worktrees_only(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    worktrees = projects / "OpenMates/.openmates-agent-worktrees"
    _folder(worktrees / "agent-idle/frontend/node_modules", 40)
    _folder(worktrees / "agent-idle/src", 40)
    monkeypatch.setattr(usage, "worktree_roots", lambda projects_: [str(worktrees / "agent-idle")])
    units = budgets.dependency_units(projects)
    assert [unit.path for unit in units] == [worktrees / "agent-idle/frontend/node_modules"]
    assert units[0].last_used == pytest.approx(NOW - 40 * HOUR)


def test_ci_evidence_and_runtime_scratch_of_idle_worktrees_are_units(tmp_path, monkeypatch):
    """Downloaded CI results inside worktrees count toward the worktrees budget (TASK-5181)."""
    projects = tmp_path / "projects"
    worktrees = projects / "OpenMates/.openmates-agent-worktrees"
    _folder(worktrees / "agent-idle/test-results/ci-runs/run", 40)
    _folder(worktrees / "agent-idle/.runtime/proof-1", 40)
    _folder(worktrees / "agent-idle/src", 40)
    monkeypatch.setattr(usage, "worktree_roots", lambda projects_: [str(worktrees / "agent-idle")])
    paths = {unit.path for unit in budgets.dependency_units(projects)}
    assert paths == {worktrees / "agent-idle/test-results", worktrees / "agent-idle/.runtime"}


def test_sibling_project_rust_target_goes_only_when_nothing_works_in_that_project(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    repo = projects / "OpenMates"
    repo.mkdir(parents=True)
    idle = _folder(projects / "idle-project/target", 30)
    busy = _folder(projects / "busy-project/target", 40)
    monkeypatch.setattr(usage, "rust_paths", lambda projects_: [str(idle), str(busy)])
    monkeypatch.setattr(usage, "other_project_roots",
                        lambda projects_: [str(projects / "busy-project"), str(projects / "idle-project")])
    monkeypatch.setattr(usage, "worktree_roots", lambda projects_: [])
    monkeypatch.setattr(usage, "filesystem", lambda path: {"percent": 60.0})
    monkeypatch.setattr(budgets, "_size", lambda path: 20 * GB)
    report = budgets.enforce(repo, apply=True, in_use=[str(projects / "busy-project/frontend")], cargo=[],
                             references=set(), now=NOW, scratch_root=tmp_path / "scratch",
                             measure=lambda cats: {"rust": 40 * GB})
    assert [item["path"] for item in report["deleted"] if item["category"] == "rust"] == [str(idle)]
    assert busy.is_dir() and report["skipped"]["in_use"] == 1
