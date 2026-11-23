# contract-test-file: tooling
"""Hooks run their scripts from the main checkout and never block when one is missing.

TASK-1338 (2026-11-23): hooks called `$(git rev-parse --show-toplevel)/scripts/...`, which
is the worktree a chat's shell has cd'ed into. Chats sitting in worktrees based before
scripts/chat_mailbox.py landed had every prompt blocked ("can't open file", exit 2).

Run: python3 -m pytest scripts/tests/test_hook_runner.py
"""

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / ".claude" / "hooks" / "run.sh"


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.email=t@example.org", "-c", "user.name=t", *args], cwd=cwd,
                   check=True, capture_output=True)


def repo_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    main = tmp_path / "main"
    (main / ".claude" / "hooks").mkdir(parents=True)
    shutil.copy(RUNNER, main / ".claude" / "hooks" / "run.sh")
    git(main.parent, "init", "-q", str(main))
    git(main, "add", "-A")
    git(main, "commit", "-qm", "base")
    worktree = tmp_path / "old-worktree"
    git(main, "worktree", "add", "-q", "--detach", str(worktree))
    (main / "scripts").mkdir()
    (main / "scripts" / "hook.py").write_text("import sys\nprint('main checkout', sys.argv[1:])\nsys.exit(2)\n")
    return main, worktree


def run(runner: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(runner), *args], cwd=cwd, capture_output=True, text=True, timeout=30)


def test_runner_in_an_old_worktree_runs_the_main_checkout_script_and_keeps_its_exit_code(tmp_path):
    main, worktree = repo_with_worktree(tmp_path)
    result = run(worktree / ".claude" / "hooks" / "run.sh", "scripts/hook.py", "hook-prompt", cwd=worktree)
    assert result.returncode == 2 and "main checkout ['hook-prompt']" in result.stdout


def test_missing_script_is_skipped_logged_and_never_blocks(tmp_path):
    main, worktree = repo_with_worktree(tmp_path)
    (main / "logs" / "claude-chat-lifecycle").mkdir(parents=True)
    result = run(main / ".claude" / "hooks" / "run.sh", "scripts/gone.py", "hook-pre", cwd=worktree)
    assert result.returncode == 0 and "missing" in result.stderr
    event = json.loads((main / "logs" / "claude-chat-lifecycle" / "events.jsonl").read_text().splitlines()[-1])
    assert event["event"] == "hook_script_missing" and event["path"].endswith("scripts/gone.py")


def test_every_settings_hook_goes_through_the_runner_and_names_an_existing_script():
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text())
    commands = [hook["command"] for groups in settings["hooks"].values() for group in groups
                for hook in group["hooks"] if hook.get("type") == "command"]
    assert commands
    prefix = '"$CLAUDE_PROJECT_DIR"/.claude/hooks/run.sh '
    for command in commands:
        assert command.startswith(prefix), command
        target = command[len(prefix):].split()[0]
        assert (ROOT / target).is_file(), target
