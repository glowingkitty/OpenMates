# contract-test-file: tooling
"""Run old-worktree dispatch forwarders in isolated temporary repositories.

The historical dispatcher would touch a sentinel standing for shared dev.
Execution must reach the canonical entry or fail before touching that sentinel.
This covers executable invocation, not just matching a source-code string.
See docs/plans/isolated-github-tests/plan.yml.
"""

from pathlib import Path
import subprocess
import sys
from scripts.ci_entrypoint import install


def checkout(tmp_path: Path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    root = tmp_path / ".openmates-agent-worktrees/agent-abcd"
    (root / "scripts").mkdir(parents=True)
    for name in ("tests.py", "run_tests.py"):
        (root / "scripts" / name).write_text(
            'from __future__ import annotations\nfrom pathlib import Path\nPath("SHARED_DEV_TOUCHED").touch()\n'
        )
    (tmp_path / "scripts").mkdir()
    return root


def test_old_worktree_routes_without_shared_preflight(tmp_path):
    root = checkout(tmp_path)
    (tmp_path / "scripts/ci_dispatch.py").write_text(
        'import sys\nprint("CANONICAL", sys.argv)\n'
    )
    install(root)
    before = (root / "scripts/tests.py").read_bytes()
    install(root)
    assert (root / "scripts/tests.py").read_bytes() == before
    result = subprocess.run(
        [sys.executable, str(root / "scripts/tests.py"), "run", "--spec", "a.spec.ts"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "CANONICAL" in result.stdout and "--worktree" in result.stdout
    assert not (root / "SHARED_DEV_TOUCHED").exists()


def test_missing_canonical_dispatcher_fails_closed(tmp_path):
    root = checkout(tmp_path)
    install(root)
    result = subprocess.run(
        [sys.executable, str(root / "scripts/run_tests.py"), "--daily"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "fallback is forbidden" in result.stderr
    assert not (root / "SHARED_DEV_TOUCHED").exists()


def test_shell_launchers_use_canonical_dispatch_and_fail_closed(tmp_path):
    root = checkout(tmp_path)
    canonical = tmp_path / "scripts/ci_dispatch.py"
    canonical.write_text('import sys\nprint("CANONICAL", sys.argv)\n')
    source = Path(__file__).resolve().parents[2]
    launchers = {
        "scripts/run-tests.sh": None,
        "scripts/run-tests-daily.sh": "--daily",
        "scripts/ci/trigger_parallel_specs.sh": "--suite",
    }
    for name, expected in launchers.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((source / name).read_bytes())
        result = subprocess.run(
            ["bash", str(target), "--detach"], cwd=root,
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "CANONICAL" in result.stdout and str(root) in result.stdout
        assert "--detach" in result.stdout
        if expected:
            assert expected in result.stdout
    canonical.unlink()
    for name in launchers:
        result = subprocess.run(
            ["bash", str(root / name)], cwd=root, capture_output=True, text=True,
        )
        assert result.returncode == 2
        assert "fallback is forbidden" in result.stderr


def test_adopted_old_shells_never_reach_shared_preflight(tmp_path):
    from scripts.ci_entrypoint import SHELL_ENTRIES

    root = checkout(tmp_path)
    canonical = tmp_path / "scripts/ci_dispatch.py"
    canonical.write_text('import sys\nprint("CANONICAL", sys.argv)\n')
    for name in SHELL_ENTRIES:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('#!/usr/bin/env bash\ntouch SHARED_DEV_TOUCHED\n')
    install(root)
    before = {name: (root / name).read_bytes() for name in SHELL_ENTRIES}
    install(root)
    assert before == {name: (root / name).read_bytes() for name in SHELL_ENTRIES}
    for name in SHELL_ENTRIES:
        result = subprocess.run(["bash", str(root / name)], cwd=root, capture_output=True, text=True)
        assert result.returncode == 0 and "CANONICAL" in result.stdout
    canonical.unlink()
    for name in SHELL_ENTRIES:
        result = subprocess.run(["bash", str(root / name)], cwd=root, capture_output=True, text=True)
        assert result.returncode == 2 and "fallback is forbidden" in result.stderr
    assert not (root / "SHARED_DEV_TOUCHED").exists()
