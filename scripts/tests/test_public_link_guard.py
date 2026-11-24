"""Chat and session links never reach public GitHub text (scripts/public_link_guard.py, owner rule 23 Nov)."""
# contract-test-file: tooling
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import public_link_guard as guard  # noqa: E402  (scripts/ is not a package)

SCRIPT = Path(__file__).resolve().parents[1] / "public_link_guard.py"
REPO = SCRIPT.parents[1]
RESERVED = "Social" + "Hub"
SID = "session_" + "019AkzE1SB4rGEvC3fai9bz3"  # built here so this file's own text is no live example

BLOCKED = {
    "claude code session": f"see https://claude.ai/code/{SID}",
    "claude chat": "https://claude.ai/chat/3f2a9c1e-1111-2222-3333-444455556666",
    "claude share": "https://claude.ai/share/abc123def",
    "claude artifact": "https://claude.ai/artifact/abc123",
    "claude public artifact": "https://claude.ai/public/artifacts/abc123",
    "claude project": "https://claude.ai/project/abc123",
    "bare session id": f"from {SID}",
    "session trailer": "fix: x\n\nClaude-Session: anything",
    "chatgpt chat": "https://chatgpt.com/c/6750a1b2-0000-1111-2222-333344445555",
    "chatgpt share": "https://chatgpt.com/share/6750a1b2-0000",
    "codex desktop thread": "codex://threads/99999999-2222-4333-8444-555555555555",
    "codex web task": "https://chatgpt.com/codex/tasks/task_example",
    "chatgpt gpt chat": "https://chatgpt.com/g/g-abc-helper/c/6750a1b2",
    "openai chat": "https://chat.openai.com/c/6750a1b2",
    "openai share": "https://chat.openai.com/share/6750a1b2",
    "gemini app": "https://gemini.google.com/app/1a2b3c4d5e",
    "gemini share": "https://gemini.google.com/share/1a2b3c4d5e",
    "gemini short share": "https://g.co/gemini/share/1a2b3c4d5e",
    "openmates share chat": "https://app.openmates.org/share/chat/9f8e7d6c#key=c2VjcmV0",
    "openmates share embed": "https://openmates.org/share/embed/9f8e7d6c",
    "openmates short share": "https://openmates.org/s/Ab12Cd34",
    "openmates dev share": "https://app.dev.openmates.org/share/chat/9f8e7d6c",
    "openmates chat link": "https://app.openmates.org/#chat-id=9f8e7d6c-1111-2222-3333-444455556666",
    "openmates dev chat link": "https://dev.openmates.org/#chat-id=9f8e7d6c",
    "openmates key in hash": "https://openmates.org/#key=c2VjcmV0",
    "openmates message link": "https://app.openmates.org/#message=9f8e7d6c",
}
ALLOWED = [
    "fix(chat): the chat list keeps its order after a refresh",
    "Docs: https://openmates.org/docs/apps/chat and https://claude.ai/ and https://chatgpt.com/",
    "Task 681e6023-cf6f-4bab-aab9-75786193df06, session 413c, chat 227f6cb7",
    "Gemini 3 Pro via https://ai.google.dev/gemini-api/docs",
    "a session_id field and session_token handling",
    "https://github.com/glowingkitty/OpenMates/pull/538",
]


@pytest.mark.parametrize("name", sorted(BLOCKED))
def test_each_chat_or_session_link_is_refused(name):
    assert guard.findings(BLOCKED[name]), name
    with pytest.raises(guard.ChatLinkError, match="violates public text policy"):
        guard.refuse(BLOCKED[name], "commit message")


@pytest.mark.parametrize("text", ALLOWED)
def test_ordinary_text_passes(text):
    assert guard.findings(text) == []


def test_commit_msg_hook_refuses_links_even_on_lines_starting_with_hash(tmp_path):
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("fix: thing\n# ordinary text\n")
    assert subprocess.run([sys.executable, str(SCRIPT), "commit-msg", str(msg)]).returncode == 0
    msg.write_text(f"fix: thing\n\n# https://claude.ai/code/{SID}\n")
    run = subprocess.run([sys.executable, str(SCRIPT), "commit-msg", str(msg)], capture_output=True, text=True)
    assert run.returncode == 1 and "violates public text policy" in run.stderr
    assert SID not in run.stderr


def test_bash_hook_checks_gh_writes_git_commits_and_body_files(tmp_path):
    body = tmp_path / "body.md"
    body.write_text(f"Summary\n\nhttps://claude.ai/code/{SID}\n")
    assert guard.check_bash(f"gh pr create --base main --title t --body-file {body}")
    assert guard.check_bash("gh pr edit 538 --body 'x https://chatgpt.com/share/abc'")
    assert guard.check_bash("gh issue comment 5 --body 'https://gemini.google.com/app/abc'")
    assert guard.check_bash("gh api repos/o/r/issues/5/comments -f body='https://openmates.org/s/Ab12'")
    assert guard.check_bash(f"git -C /x commit -m 'fix' -m 'Claude-Session: https://claude.ai/code/{SID}'")
    assert guard.check_bash("gh pr create --title 'fix: x' --body 'clean text'") == []
    assert guard.check_bash("gh api graphql -F number=3") == []
    assert guard.check_bash("gh api repos/o/r/issues/5/comments -F body=@body.md", tmp_path)
    assert guard.check_bash("gh issue comment 5 --body-file -", tmp_path)
    assert guard.check_bash("gh pr view 538 --json body") == []
    assert guard.check_bash(f"grep {SID} notes.txt") == []  # not a public write
    run = subprocess.run([sys.executable, str(SCRIPT), "bash", f"gh pr create --body-file {body}"],
                         capture_output=True, text=True)
    assert run.returncode == 2 and "BLOCKED" in run.stderr


def test_ci_pr_check_reads_title_and_body_without_printing_the_share_key():
    env = {"PR_TITLE": "fix: thing", "PR_BODY": "Summary only"}
    assert subprocess.run([sys.executable, str(SCRIPT), "pr"], env={**env, "PATH": "/usr/bin"}).returncode == 0
    env["PR_BODY"] = "Summary\n\nhttps://app.openmates.org/share/chat/9f8e#key=abc"
    run = subprocess.run([sys.executable, str(SCRIPT), "pr"], env={**env, "PATH": "/usr/bin"},
                         capture_output=True, text=True)
    assert run.returncode == 1 and "OpenMates chat or share link" in run.stderr
    assert "#key=" not in run.stderr


@pytest.mark.parametrize(("command", "kind"), [
    ("gh pr create --body-file body.md", "Codex thread or task link"),
    ("gh issue create --title 'See https://claude.ai/chat/example'", "Claude chat"),
    ("gh issue comment 5 --body 'https://gemini.google.com/app/example'", "Gemini chat"),
    ("gh api repos/o/r/issues/5/comments -f body=https://openmates.org/s/example", "OpenMates chat"),
    ("git commit -m 'See https://chatgpt.com/c/example'", "ChatGPT chat"),
    (f"git switch -c test/{RESERVED}", "reserved external project name"),
])
def test_codex_routes_github_writes_through_the_shared_bash_hook(tmp_path, command, kind):
    (tmp_path / "body.md").write_text(BLOCKED["codex desktop thread"])
    (tmp_path / ".claude").mkdir()
    settings = json.loads((REPO / ".claude/settings.json").read_text())
    bash_hooks = next(group for group in settings["hooks"]["PreToolUse"] if group.get("matcher") == "Bash")
    hook = next(item for item in bash_hooks["hooks"] if ".claude/hooks/bash-guard.sh" in item["command"])
    hook["command"] = f'"{REPO}/.claude/hooks/bash-guard.sh"'
    (tmp_path / ".claude/settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [bash_hooks]}}))
    payload = {"tool_name": "Bash", "cwd": str(tmp_path), "tool_input": {"command": command}}
    run = subprocess.run(
        [sys.executable, str(REPO / "scripts/codex_hook_adapter.py"), "--event", "PreToolUse", "--root", str(tmp_path)],
        input=json.dumps(payload), env={**os.environ, "OPENMATES_PROJECT_ROOT": str(REPO)},
        capture_output=True, text=True,
    )
    assert run.returncode == 2 and kind in run.stderr


@pytest.mark.parametrize("in_path", [True, False])
def test_reserved_name_is_refused_in_staged_path_or_blob(tmp_path, in_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    name = f"{RESERVED.lower()}.txt" if in_path else "ordinary.txt"
    (tmp_path / name).write_text("clean text" if in_path else RESERVED)
    subprocess.run(["git", "add", "--", name], cwd=tmp_path, check=True)
    # Inspect the Git index even if the working copy changes afterwards.
    (tmp_path / name).write_text("clean working copy")
    run = subprocess.run([sys.executable, str(SCRIPT), "tree"], cwd=tmp_path, capture_output=True, text=True)
    assert run.returncode == 1 and "reserved external project name" in run.stderr


def test_reserved_name_is_refused_in_commit_pr_and_branch(tmp_path):
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(f"fix: {RESERVED.upper()}")
    for args in (["commit-msg", str(msg)], ["pr"], ["branch", f"refs/heads/{RESERVED}"]):
        run = subprocess.run(
            [sys.executable, str(SCRIPT), *args], env={**os.environ, "PR_TITLE": RESERVED},
            capture_output=True, text=True,
        )
        assert run.returncode == 1 and "reserved external project name" in run.stderr


@pytest.mark.parametrize("separator", ["", " ", "-", "_", "\t"])
def test_reserved_name_spelling_variants(separator):
    name = separator.join(("SoCiAl", "HuB"))
    assert guard.findings(name) == ["reserved external project name"]
    assert guard.main(["branch", f"refs/heads/{name}"]) == 1


def test_range_and_pre_push_reject_an_intermediate_blob(tmp_path):
    def git(*args, data=None):
        return subprocess.check_output(["git", *args], input=data, cwd=tmp_path).strip().decode()

    git("init", "-q")
    empty = git("mktree", data=b"")
    env = {**os.environ, "GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@example.org",
           "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@example.org"}

    def commit(tree, *parents):
        return subprocess.check_output(["git", "commit-tree", tree, *parents], input=b"clean message\n",
                                       cwd=tmp_path, env=env).strip().decode()

    base = commit(empty)
    blob = git("hash-object", "-w", "--stdin", data=b"SoCiAl" + b"-" + b"HuB")
    dirty = git("mktree", data=f"100644 blob {blob}\tsettings.txt\n".encode())
    middle = commit(dirty, "-p", base)
    head = commit(empty, "-p", middle)
    push = f"refs/heads/dev {head} refs/heads/dev {base}\n"
    for args in (["range", base, head], ["pre-push", "origin"]):
        run = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=tmp_path, input=push,
                             capture_output=True, text=True)
        assert run.returncode == 1 and "Rephrase" in run.stderr
