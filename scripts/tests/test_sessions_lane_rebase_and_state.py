#!/usr/bin/env python3
# contract-test-file: tooling
"""Lane pipeline contracts: 3-way refresh-base, candidate index regeneration,
and lost-update-free sessions.json saves.

* ``refresh-base --rebase`` merges lane edits that overlap origin/dev changes,
  regenerates generated artifacts and, on a true conflict, reports exact files
  and hunks while leaving the worktree untouched with a recoverable backup.
* ci-source regenerates ``specifications/generated/assertion-index.yml`` when
  an edit moves a ``test()`` line and refuses loudly when generation fails.
* A stale ``_load_sessions`` snapshot saved during a workspace transition no
  longer drops the transition's ``lifecycle`` record (the ``lane_start.py``
  ``KeyError: 'lifecycle'`` race) or sessions created after the load.
Fixtures use isolated Git repositories and state files under tmp_path only.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_sessions_lane_deploy_pipeline as pipeline  # noqa: E402 - sibling fixture module after sys.path setup

from scripts import lane_ci_source, worktree_rebase  # noqa: E402 - repository package import after sys.path setup

advance_dev = pipeline.advance_dev
git = pipeline.git
load_sessions_module = pipeline.load_sessions_module
lane_env = pipeline.lane_env  # shared pytest fixture: isolated dev remote plus lane worktree

TEN_LINES = "".join(f"line {number}\n" for number in range(1, 11))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _seed(root: Path, relative_path: str, text: str) -> str:
    return advance_dev(root, relative_path, text)


def test_overlapping_edits_on_different_lines_are_three_way_rebased(lane_env):
    sessions, root, lane, _base, _metadata = lane_env
    seeded = _seed(root, "notes.txt", TEN_LINES)
    git(lane, "fetch", "origin", "dev")
    git(lane, "merge", "--ff-only", seeded)
    _write(lane / "notes.txt", TEN_LINES.replace("line 2\n", "line 2 lane\n"))
    (lane / "docs/migration/rust/overview.yml").write_text("hand edited stale\n", encoding="utf-8")
    _write(lane / "untouched.txt", "lane only\n")
    (root / "docs/migration/rust/web-lanes.yml").write_text("upstream\n", encoding="utf-8")
    git(root, "add", "docs/migration/rust/web-lanes.yml")  # committed together with notes.txt below
    target = _seed(root, "notes.txt", TEN_LINES.replace("line 9\n", "line 9 dev\n"))

    outcome = sessions.fast_forward_worktree_to_origin_dev(lane, merge_overlap=True)

    assert outcome["status"] == "fast_forwarded"
    assert outcome["merged"] == ["notes.txt"]
    assert git(lane, "rev-parse", "HEAD") == target
    merged = (lane / "notes.txt").read_text(encoding="utf-8")
    assert "line 2 lane\n" in merged and "line 9 dev\n" in merged
    diff = git(lane, "diff", "HEAD", "--", "notes.txt")
    assert "+line 2 lane" in diff and "line 9" not in diff
    # Generated artifacts are regenerated, never merged.
    assert (lane / "docs/migration/rust/overview.yml").read_text(encoding="utf-8") == "# GENERATED\nlanes: upstream\n"
    assert (lane / "untouched.txt").read_text(encoding="utf-8") == "lane only\n"
    ref, commit = outcome["backup"].split("@")
    assert git(lane, "rev-parse", ref) == commit
    assert git(lane, "show", f"{commit}:notes.txt") + "\n" == TEN_LINES.replace("line 2\n", "line 2 lane\n")
    assert git(lane, "show", f"{commit}:untouched.txt") == "lane only"


def test_true_conflict_reports_files_and_hunks_and_leaves_worktree_intact(lane_env):
    sessions, root, lane, base, _metadata = lane_env
    (lane / "changed.txt").write_text("lane edit\n", encoding="utf-8")
    (lane / "other.txt").unlink()
    _write(lane / "fresh.txt", "lane new file\n")
    advance_dev(root, "changed.txt", "upstream edit\n")
    advance_dev(root, "other.txt", "upstream other\n")
    status_before = git(lane, "status", "--porcelain")

    outcome = sessions.fast_forward_worktree_to_origin_dev(lane, merge_overlap=True)

    assert outcome["status"] == "conflicted"
    assert git(lane, "rev-parse", "HEAD") == base
    assert git(lane, "status", "--porcelain") == status_before
    assert (lane / "changed.txt").read_text(encoding="utf-8") == "lane edit\n"
    assert not (lane / "other.txt").exists()
    by_path = {conflict["path"]: conflict for conflict in outcome["conflicts"]}
    assert set(by_path) == {"changed.txt", "other.txt"}
    hunk = by_path["changed.txt"]["hunks"][0]
    assert hunk["line"] == 1
    assert "<<<<<<< lane\nlane edit\n||||||| base\nbefore\n=======\nupstream edit\n>>>>>>> origin/dev" == hunk["text"]
    assert by_path["other.txt"]["reason"] == "lane deleted the file; origin/dev modified it"
    message = worktree_rebase.format_conflicts(outcome)
    assert "changed.txt: both sides changed the same lines" in message
    assert "merged lines 1-7" in message and outcome["backup"] in message
    # The backup commit retains every lane edit, including untracked files.
    commit = outcome["backup"].split("@")[1]
    assert git(lane, "show", f"{commit}:changed.txt") == "lane edit"
    assert git(lane, "show", f"{commit}:fresh.txt") == "lane new file"


def test_failed_fast_forward_restores_lane_bytes(lane_env, monkeypatch):
    sessions, root, lane, base, _metadata = lane_env
    seeded = _seed(root, "notes.txt", TEN_LINES)
    git(lane, "fetch", "origin", "dev")
    git(lane, "merge", "--ff-only", seeded)
    lane_text = TEN_LINES.replace("line 2\n", "line 2 lane\n")
    _write(lane / "notes.txt", lane_text)
    _seed(root, "notes.txt", TEN_LINES.replace("line 9\n", "line 9 dev\n"))
    from scripts import worktree_fast_forward

    real_run = worktree_fast_forward._run

    def failing_merge(command, cwd, timeout=120):
        if command[:3] == ["git", "merge", "--ff-only"]:
            return 1, "", "simulated failure"
        return real_run(command, cwd, timeout)

    monkeypatch.setattr(worktree_fast_forward, "_run", failing_merge)
    with pytest.raises(RuntimeError, match="simulated failure.*Backup of all lane edits"):
        sessions.fast_forward_worktree_to_origin_dev(lane, merge_overlap=True)
    assert git(lane, "rev-parse", "HEAD") == seeded
    assert (lane / "notes.txt").read_text(encoding="utf-8") == lane_text


def test_refresh_base_rebase_raises_conflict_report(monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"sessions": {"abcd": {"worktree": {"path": "/tmp/lane"}}}})
    calls = []
    conflicted = {"status": "conflicted", "backup": "refs/openmates/rebase-backups/x@1",
                  "conflicts": [{"path": "a.py", "reason": "both sides changed the same lines",
                                 "hunks": [{"line": 3, "end_line": 9, "text": "<<<<<<< lane"}]}]}
    monkeypatch.setattr(sessions, "fast_forward_worktree_to_origin_dev",
                        lambda path, **kwargs: calls.append(kwargs) or conflicted)
    with pytest.raises(RuntimeError, match=r"(?s)a\.py: both sides changed.*merged lines 3-9"):
        sessions.refresh_session_worktree_base.__wrapped__("abcd", rebase=True)
    assert calls == [{"merge_overlap": True}]


# --- ci-source assertion index regeneration ---

INDEX_GENERATOR_STUB = """\
import sys
from pathlib import Path
root = Path(sys.argv[sys.argv.index("--repo-root") + 1])
lines = (root / "web/login.spec.ts").read_text(encoding="utf-8").splitlines()
line = next(number for number, text in enumerate(lines, start=1) if text.startswith("test("))
(root / "specifications/generated").mkdir(parents=True, exist_ok=True)
(root / "specifications/generated/assertion-index.yml").write_text(f"login: {line}\\n", encoding="utf-8")
"""


def test_moved_test_line_regenerates_assertion_index_for_candidate_then_restores(lane_env):
    _sessions, _root, lane, _base, _metadata = lane_env
    (lane / "scripts" / "specifications.py").write_text(INDEX_GENERATOR_STUB, encoding="utf-8")
    index = lane / "specifications/generated/assertion-index.yml"
    _write(index, "login: 1\n")
    _write(lane / "web/login.spec.ts", "// moved down\n\ntest('login', () => {});\n")

    with lane_ci_source.fresh_generated_artifacts(
        lane, ["web/login.spec.ts"], specification_governed=True
    ) as warnings:
        assert warnings == []
        assert index.read_text(encoding="utf-8") == "login: 3\n"
    assert index.read_text(encoding="utf-8") == "login: 1\n"


def test_failed_specification_generation_refuses_with_cause_and_restores(lane_env):
    _sessions, _root, lane, _base, _metadata = lane_env
    (lane / "scripts" / "specifications.py").write_text("raise SystemExit('evidence boom')\n", encoding="utf-8")
    index = lane / "specifications/generated/assertion-index.yml"
    _write(index, "login: 1\n")

    with pytest.raises(RuntimeError, match="never hand-edit.*evidence boom"):
        with lane_ci_source.fresh_generated_artifacts(lane, ["web/login.spec.ts"], specification_governed=True):
            pytest.fail("publication must not run on stale Specification artifacts")
    assert index.read_text(encoding="utf-8") == "login: 1\n"


# --- sessions.json lost-update race (lane_start KeyError: 'lifecycle') ---


@pytest.fixture
def state_env(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    state = tmp_path / "sessions.json"
    monkeypatch.setattr(sessions, "SESSIONS_FILE", state)
    monkeypatch.setattr(sessions, "WORKTREE_CHECKPOINT_LOCKS_DIR", tmp_path / "checkpoint-locks")
    monkeypatch.setattr(sessions, "_normalize_session_state_paths", lambda _data: None)
    state.write_text(json.dumps({"sessions": {"lane1": {"task": "one"}, "gone": {"task": "x"}}}), encoding="utf-8")
    return sessions, state


def test_stale_snapshot_save_during_transition_keeps_lifecycle(state_env):
    sessions, state = state_env
    stale = sessions._load_sessions()  # e.g. a concurrent `start` loaded before the transition began

    def operation():
        stale["sessions"]["lane1"]["task"] = "edited by the concurrent writer"
        sessions._save_sessions(stale)  # lands between begin() and finish()
        return {"ok": True}

    assert sessions._run_workspace_transition("lane1", "lane-open", operation) == {"ok": True}
    saved = json.loads(state.read_text(encoding="utf-8"))["sessions"]["lane1"]
    assert saved["task"] == "edited by the concurrent writer"
    assert saved["lifecycle"]["operations"][-1]["status"] == "completed"


def test_stale_snapshot_save_keeps_new_sessions_and_honours_deletions(state_env):
    sessions, state = state_env
    stale = sessions._load_sessions()
    sessions._mutate_sessions(lambda data: data["sessions"].update(lane2={"task": "two"}))
    del stale["sessions"]["gone"]

    sessions._save_sessions(stale)

    saved = json.loads(state.read_text(encoding="utf-8"))["sessions"]
    assert set(saved) == {"lane1", "lane2"}


def test_concurrent_lane_starts_never_lose_lifecycle(state_env):
    """Two processes alternate load/save while transitions run, as parallel lane_start does."""
    sessions, state = state_env
    script = f"""
import importlib.util, json, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("s", {str(Path(sessions.__file__))!r})
module = importlib.util.module_from_spec(spec); sys.modules["s"] = module; spec.loader.exec_module(module)
module.SESSIONS_FILE = Path({str(state)!r})
module._normalize_session_state_paths = lambda data: None
for number in range(40):
    data = module._load_sessions()
    data["sessions"]["lane1"]["touched"] = number
    module._save_sessions(data)
"""
    writer = subprocess.Popen([sys.executable, "-c", script])
    try:
        for _ in range(40):
            sessions._run_workspace_transition("lane1", "lane-open", lambda: {"ok": True})
    finally:
        assert writer.wait(timeout=120) == 0
    lifecycle = json.loads(state.read_text(encoding="utf-8"))["sessions"]["lane1"]["lifecycle"]
    assert lifecycle["generation"] == 40
    assert all(item["status"] == "completed" for item in lifecycle["operations"])
