#!/usr/bin/env python3
"""Enforce the repository's public text and naming policy.

Commit messages, pull request titles and descriptions, issues, comments and release notes are
public. They must never carry a link to an AI chat or coding session, nor a Claude Code session
id. OpenMates share links are the most sensitive: they can carry the chat key after `#key=`.

The check is a deterministic pattern match (CHAT_LINK_PATTERNS), used by:
  - scripts/sessions.py deploy (before every commit, also with --no-verify),
  - the git commit-msg hook (scripts/install-hooks.sh),
  - the Claude Bash hook (.claude/hooks/bash-guard.sh) for `git commit`, `gh pr|issue|release|api`,
  - the CI workflow .github/workflows/public-text-guard.yml on every pull request to dev and main.

CLI:
  public_link_guard.py check [FILE ...]   text from files or stdin; exit 1 with the findings
  public_link_guard.py commit-msg FILE    git commit-msg hook (comment lines ignored)
  public_link_guard.py bash COMMAND [CWD] Bash hook: checks commands and body files
  public_link_guard.py pr                 CI: PR_TITLE and PR_BODY from the environment
  public_link_guard.py tree [BASE]        Check staged blobs or blobs changed since BASE
  public_link_guard.py branch [REF ...]   Check branch names
  public_link_guard.py range BASE HEAD    Check each introduced commit and its changed blobs
  public_link_guard.py pre-push REMOTE    Check refs and commits from Git pre-push stdin
Tests: scripts/tests/test_public_link_guard.py
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

_SUB = r"(?:[a-z0-9-]+\.)*"
# Keep the forbidden spelling out of the repository itself.
RESERVED_NAME = "social" + "hub"
_RESERVED_EXPRESSION = r"[\s_-]*".join(("social", "hub"))
_RESERVED_TEXT = re.compile(_RESERVED_EXPRESSION, re.I)
_RESERVED_BYTES = re.compile(_RESERVED_EXPRESSION.encode(), re.I)
# Immutable commits already published on the two protected branches before
# their release reconciliation. This only grandfathers the reserved name.
LEGACY_RESERVED_COMMITS = frozenset({
    "0107427c276dc8560f508300c7ce23fafb76621d",
    "1285c0b3b9867b45ccaffd35fe117e3000616820",
    "1b9049c990af40469564fe75c394acd42b99e7f7",
    "1da224eca88e81d87b30c240ebf70aafa0224058",
    "2cb07290d9d5f83eb89ade384a440915cbc6ab84",
    "349304975b6c2df37353921f024acf0ffe408c08",
    "3e426694c54419f1099d015776166021f255849e",
    "4180c66a18ba0be90c0fb8be4a47328e1e8e21cc",
    "453ad86e82e8a3960c318eeb6d4a23c0751b7263",
    "521c26b8c0176c3c1454ab975b7ea15b99b5a964",
    "640805595c30d4789198d5dd0b1ae24bfbd7f7e1",
    "6a33c1cb6dac6e77e51ba498bbf34f1678a016a7",
    "783c310f3a1ead3f5d66eee0ba3cac35bb9a2619",
    "7ebc59b361d86ccc8526771185c8a641bda94f6b",
    "8ae8145170934ebd9ef466bbbdb45e901ec80025",
    "965e341d878e7205ee6ea250cc6ca623718f1eb2",
    "9cd7c2f6d87056d6bfb055ccfff61c586d1d9cce",
    "9f30b48af4e3bc3a77df2382c5fd9563540505d4",
    "a0025d2aff6558d8b8a7e4d421f56e680324607b",
    "a1f1e372862640f3017f68ca7929bd22a8945845",
    "b51881fef6d2bdeff6b107c016c69e415955ecc0",
    "b924b83df2126abe6f1e02aacf01fe69517ebe33",
    "c9ab19cc0dbdba9540dc7649aced2b92904fbaab",
    "cad4c5075b8fc032959d1d6acb70d87d92e536af",
    "cdfee910dd1da6e0cf682977496ec7280d5f0528",
    "e424462fc772366c89e333e9abffbd9eec728691",
    "e602024d9f3911e6cda74c15a872dd2243e1604a",
    "e6d1207ed2b1eeb3c6ecc30f640f1597643a2e5d",
    "e6d1a9865f6f50a7e060e27e0373267ca3c0cd3b",
    "ec36894175762b515800ea39a4e3646837f92b2c",
    "f7311ca4539b1e07e377a4ef5cf6090959d0955f",
    "f7ea1e0ee2265dd81d89112b325e1bd20f750d8a",
})
LEGACY_CLAUDE_COMMIT_MESSAGES = frozenset({
    "349304975b6c2df37353921f024acf0ffe408c08",
    "6c1ca97ea6e9501d155fceafc09a17aefd405868",
    "d15436f4d929b280ae44e245a80b941601d51669",
    "f36500ab10ca9f93999721201a5281000fa11f5c",
})
LEGACY_CLAUDE_FINDINGS = frozenset({
    "Claude chat, code session, artifact or share link",
    "Claude Code session id",
    "Claude-Session trailer",
})
REPHRASE = "Rephrase without referring to the other project, then retry."
CHAT_LINK_PATTERNS: dict[str, re.Pattern[str]] = {
    "Claude chat, code session, artifact or share link": re.compile(
        r"\bclaude\.ai/(?:chat|code|share|artifact|artifacts|public|project|projects)\b", re.I),
    "Claude Code session id": re.compile(r"\bsession_[0-9A-Za-z]{20,}\b"),
    "Claude-Session trailer": re.compile(r"^\s*Claude-Session\s*:", re.I | re.M),
    "Codex thread or task link": re.compile(
        r"\b(?:codex://threads?/|chatgpt\.com/codex/(?:tasks?|threads?)/)\S+", re.I),
    "ChatGPT chat or share link": re.compile(
        r"\b(?:chatgpt\.com|chat\.openai\.com)/(?:[^\s/]+/)*(?:c|share|chat|g)/", re.I),
    "Gemini chat or share link": re.compile(
        r"\b(?:gemini\.google\.com/(?:app|share|gem|u/\d+/app)\b|g\.co/gemini(?:/share)?\b)", re.I),
    # Share pages (/share/chat/<id>, /share/embed/<id>), short share links (/s/<token>) and app links
    # to one chat or message (#chat-id=, #message=), which can also carry the chat key (#key=).
    "OpenMates chat or share link": re.compile(
        rf"\b{_SUB}openmates\.org/(?:share/[a-z-]+/\S|s/\S)"
        rf"|\b{_SUB}openmates\.org/[^\s#]*#[^\s]*\b(?:key|chat-id|chat_id|message|new-message)=", re.I),
}
GH_WRITE = re.compile(r"\bgh\s+(?:pr\s+(?:create|edit|comment|review|merge)|issue\s+(?:create|edit|comment)"
                      r"|release\s+(?:create|edit)|api)\b")
GH_API = re.compile(r"\bgh\s+api\b")
GIT_COMMIT = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?commit\b")
GIT_BRANCH = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?(?:branch|switch|checkout|push)\b")
FILE_FLAGS = ("--body-file", "-F", "--file", "--notes-file", "--input")


class ChatLinkError(ValueError):
    """Public text contains a chat or session link."""


def findings(text: str, *, check_name: bool = True) -> list[str]:
    """Report categories without copying private links or keys into logs."""
    found = [kind for kind, pattern in CHAT_LINK_PATTERNS.items() if pattern.search(text)]
    if check_name and _RESERVED_TEXT.search(text):
        found.append("reserved external project name")
    return found


def refuse(
    text: str, where: str, *, check_name: bool = True,
    historical_findings: frozenset[str] = frozenset(),
) -> None:
    """Reject private links and, within this repository, the reserved name."""
    if hits := [item for item in findings(text, check_name=check_name) if item not in historical_findings]:
        raise ChatLinkError(f"{where} violates public text policy: {', '.join(hits)}. {REPHRASE}")


def _files_in(command: str, cwd: Path) -> list[Path]:
    try:
        words = shlex.split(command, posix=True)
    except ValueError:
        return []
    paths = []
    for index, word in enumerate(words):
        value = ""
        if word in FILE_FLAGS and index + 1 < len(words):
            value = words[index + 1]
        elif "=" in word and word.split("=", 1)[0] in FILE_FLAGS:
            value = word.split("=", 1)[1]
        elif index and words[index - 1] in {"--field", "-F"} and "=@" in word:
            value = word.split("=@", 1)[1]
        if word == "-F" and GH_API.search(command) and "=" in value:
            value = value.split("=@", 1)[1] if "=@" in value else ""
        if value:
            paths.append(cwd / value)
    return paths


def check_bash(command: str, cwd: Path = Path(".")) -> list[str]:
    """Findings for a Bash command that writes public GitHub text; [] for any other command."""
    if not (GH_WRITE.search(command) or GIT_COMMIT.search(command)):
        return ["reserved external project name in Git command"] if (
            GIT_BRANCH.search(command) and _RESERVED_TEXT.search(command)
        ) else []
    hits = findings(command)
    for path in _files_in(command, cwd):
        if path.name == "-":
            hits.append("public text from stdin must be supplied as a file")
            continue
        try:
            hits += findings(path.read_text(errors="replace"))
        except OSError:
            # A path created earlier in the same command is checked only on a
            # separate invocation. Reject opaque public text instead of guessing.
            hits.append("public text file could not be inspected")
    return hits


def check_tree(base: str | None = None) -> None:
    """Check names and blobs entering the index or the pull request."""
    diff = ["git", "diff", "--no-renames", "--name-only", "--diff-filter=ACMRT", "-z"]
    diff += [base, "HEAD", "--"] if base else ["--cached"]
    files = subprocess.check_output(diff).split(b"\0")
    for path in filter(None, files):
        revision = (b"HEAD:" if base else b":") + path
        check_blob(path, revision)


def check_blob(path: bytes, revision: bytes) -> None:
    if _RESERVED_BYTES.search(path):
        raise ChatLinkError(f"A changed file path contains the reserved external project name. {REPHRASE}")
    if subprocess.check_output(["git", "cat-file", "-t", revision]).strip() != b"blob":
        return
    blob = subprocess.check_output(["git", "cat-file", "blob", revision])
    if _RESERVED_BYTES.search(blob):
        raise ChatLinkError(f"{os.fsdecode(path)!r} contains the reserved external project name. {REPHRASE}")


def check_commits(*revisions: str) -> bool:
    """Check each introduced commit and its changed blobs, including intermediate versions."""
    commits = subprocess.check_output(["git", "rev-list", *revisions, "--"]).splitlines()
    seen = set()
    has_legacy_commits = False
    for commit in commits:
        oid = commit.decode("ascii")
        legacy = oid in LEGACY_RESERVED_COMMITS
        message = subprocess.check_output(["git", "show", "-s", "--format=%B", commit])
        historical_findings = LEGACY_CLAUDE_FINDINGS if oid in LEGACY_CLAUDE_COMMIT_MESSAGES else frozenset()
        refuse(
            message.decode(errors="replace"), f"commit {oid[:10]}",
            check_name=not legacy, historical_findings=historical_findings,
        )
        if legacy:
            has_legacy_commits = True
            continue
        changes = subprocess.check_output(["git", "diff-tree", "-m", "-r", "--root", "--no-commit-id",
                                           "--no-renames", "--diff-filter=ACMRT", "--raw", "--no-abbrev",
                                           "-z", commit]).split(b"\0")
        for metadata, path in zip(changes[::2], changes[1::2]):
            mode, blob = metadata.split()[1:4:2]
            if (path, blob) in seen:
                continue
            seen.add((path, blob))
            if _RESERVED_BYTES.search(path):
                raise ChatLinkError(f"A changed file path contains the reserved external project name. {REPHRASE}")
            if mode != b"160000":  # Gitlinks contain a referenced commit ID, not file bytes.
                check_blob(path, blob)
    return has_legacy_commits


def check_published_range(before: str, after: str, *excluded: str) -> None:
    """Allow known published history only when its target tree is clean."""
    revisions = [f"{before}..{after}"] if before.strip("0") else [after, *excluded]
    if not check_commits(*revisions):
        return
    paths = subprocess.check_output(
        ["git", "ls-tree", "-rz", "--name-only", after, "--"],
    ).split(b"\0")
    if any(_RESERVED_BYTES.search(path) for path in paths):
        raise ChatLinkError(f"A published path contains the reserved external project name. {REPHRASE}")
    pattern = _RESERVED_EXPRESSION.replace(r"\s", "[:space:]")
    result = subprocess.run(
        ["git", "grep", "-ilI", "-E", "-e", pattern, after, "--"],
        stdout=subprocess.DEVNULL, check=False,
    )
    if result.returncode == 0:
        raise ChatLinkError(f"The published tree contains the reserved external project name. {REPHRASE}")
    if result.returncode != 1:
        raise subprocess.CalledProcessError(result.returncode, result.args)


def check_push(remote: str, lines: str) -> None:
    for line in lines.splitlines():
        local_ref, local_oid, remote_ref, remote_oid = line.split()
        if _RESERVED_TEXT.search(local_ref) or _RESERVED_TEXT.search(remote_ref):
            raise ChatLinkError(f"A pushed ref contains the reserved external project name. {REPHRASE}")
        if not local_oid.strip("0"):  # A deleted ref introduces no commits.
            continue
        check_published_range(remote_oid, local_oid, "--not", f"--remotes={remote}")


def main(argv: list[str]) -> int:
    verb, rest = (argv[0], argv[1:]) if argv else ("check", [])
    if verb == "check":
        text = "\n".join(Path(p).read_text(errors="replace") for p in rest) if rest else sys.stdin.read()
        where = "text"
    elif verb == "commit-msg" and rest:
        text, where = Path(rest[0]).read_text(errors="replace"), "commit message"
    elif verb == "bash" and rest:
        hits = check_bash(rest[0], Path(rest[1]) if len(rest) > 1 else Path("."))
        if hits:
            print("BLOCKED by public text policy: " + ", ".join(hits) + ". " + REPHRASE, file=sys.stderr)
            return 2
        return 0
    elif verb == "pr":
        text = f"{os.environ.get('PR_TITLE', '')}\n{os.environ.get('PR_BODY', '')}"
        where = "pull request title or description"
    elif verb == "branch":
        if any(_RESERVED_TEXT.search(ref) for ref in rest):
            print(f"public_link_guard: branch name contains the reserved external project name. {REPHRASE}", file=sys.stderr)
            return 1
        return 0
    elif verb in {"tree", "range", "pre-push"}:
        try:
            if verb == "tree":
                check_tree(rest[0] if rest else None)
            elif verb == "range" and len(rest) == 2:
                before, after = rest
                check_published_range(before, after)
            elif verb == "pre-push" and rest:
                check_push(rest[0], sys.stdin.read())
            else:
                return 64
        except (ValueError, subprocess.CalledProcessError) as error:
            print(f"public_link_guard: {error}", file=sys.stderr)
            return 1
        return 0
    else:
        print(__doc__, file=sys.stderr)
        return 64
    try:
        refuse(text, where)
    except ChatLinkError as error:
        print(f"public_link_guard: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
