#!/usr/bin/env python3
"""Parse shell commands for OpenMates hook safety checks.

This helper backs `.claude/hooks/bash-guard.sh` and intentionally checks only
actual command invocations. It does not scan quoted Python, SQL, docs, or search
strings, which prevents guard false positives during workflow research.
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path


SEPARATORS = {";", "&", "&&", "||", "|"}
INSTALL_SUBCOMMANDS = {"add", "install", "i"}
PACKAGE_MUTATION_SUBCOMMANDS = {
    "add",
    "install",
    "i",
    "remove",
    "rm",
    "uninstall",
    "update",
    "upgrade",
}
PINNED_OPENCODE_VERSION = "1.17.20"
GIT_OPTIONS_WITH_VALUES = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
ENV_OPTIONS_WITH_VALUES = {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}
TIMEOUT_OPTIONS_WITH_VALUES = {"-k", "--kill-after", "-s", "--signal"}


def block(reason: str) -> int:
    print(json.dumps({"decision": "block", "reason": reason}), file=sys.stderr)
    return 2


def tokenize(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        # Let malformed shell syntax fail in Bash instead of guessing.
        return []


def segments(tokens: list[str]) -> list[list[str]]:
    result: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in SEPARATORS:
            if current:
                result.append(current)
                current = []
            continue
        current.append(token)
    if current:
        result.append(current)
    return result


def basename(token: str) -> str:
    return Path(token).name


def is_assignment(token: str) -> bool:
    if "=" not in token or token.startswith("="):
        return False
    key = token.split("=", 1)[0]
    return key.replace("_", "a").isalnum() and not key[0].isdigit()


def unwrap_invocation(segment: list[str]) -> tuple[str, list[str]]:
    index = 0
    while index < len(segment) and is_assignment(segment[index]):
        index += 1

    if index >= len(segment):
        return "", []

    command = basename(segment[index])
    args = segment[index + 1 :]

    if command in {"command", "builtin"} and args:
        return basename(args[0]), args[1:]

    if command == "env":
        env_index = 0
        while env_index < len(args):
            arg = args[env_index]
            if arg == "--":
                env_index += 1
                break
            if is_assignment(arg):
                env_index += 1
                continue
            if arg.startswith("-"):
                env_index = skip_option(args, env_index, ENV_OPTIONS_WITH_VALUES)
                continue
            break
        if env_index < len(args):
            return basename(args[env_index]), args[env_index + 1 :]

    if command == "timeout" and args:
        timeout_index = 0
        while timeout_index < len(args) and args[timeout_index].startswith("-"):
            timeout_index = skip_option(args, timeout_index, TIMEOUT_OPTIONS_WITH_VALUES)
        if timeout_index < len(args):
            timeout_index += 1  # duration
        if timeout_index < len(args):
            return basename(args[timeout_index]), args[timeout_index + 1 :]

    return command, args


def next_non_option(args: list[str]) -> str:
    for arg in args:
        if arg == "--":
            continue
        if not arg.startswith("-"):
            return arg
    return ""


def skip_option(args: list[str], index: int, options_with_values: set[str]) -> int:
    arg = args[index]
    if arg in options_with_values:
        return min(index + 2, len(args))
    if any(arg.startswith(f"{option}=") for option in options_with_values if option.startswith("--")):
        return index + 1
    return index + 1


def is_opencode_package(arg: str) -> bool:
    return arg == "opencode-ai" or arg.startswith("opencode-ai@")


def package_manager_mutates_opencode(command: str, args: list[str]) -> bool:
    if command not in {"npm", "pnpm", "bun", "yarn"}:
        return False

    positional = [arg for arg in args if arg == "-" or not arg.startswith("-")]
    if not positional:
        return False

    if command == "yarn" and positional[:2] in (["global", "add"], ["global", "remove"]):
        return any(is_opencode_package(arg) for arg in positional[2:])

    subcommand = positional[0]
    if subcommand not in PACKAGE_MUTATION_SUBCOMMANDS:
        return False
    if any(is_opencode_package(arg) for arg in positional[1:]):
        return True

    # A package-less global update upgrades every installed global package,
    # including OpenCode.
    return subcommand in {"update", "upgrade"} and len(positional) == 1 and any(
        arg in {"-g", "--global"} for arg in args
    )


def check_invocation(command: str, args: list[str]) -> str | None:
    if package_manager_mutates_opencode(command, args) or (
        command == "opencode" and next_non_option(args) in {"update", "upgrade"}
    ):
        return (
            "BLOCKED: OpenCode is pinned to "
            f"{PINNED_OPENCODE_VERSION}. Agents may not install, uninstall, or upgrade OpenCode. "
            "The user must update it manually from their terminal when explicitly desired."
        )

    if command == "pnpm":
        subcommand = next_non_option(args)
        if subcommand in INSTALL_SUBCOMMANDS:
            return None
        return "BLOCKED: pnpm/npx build, dev, run, and test commands are not allowed locally. pnpm add/install is allowed; use sessions.py deploy for builds and python3 scripts/tests.py run for tests."

    if command == "npx":
        return "BLOCKED: npx build, dev, run, and test commands are not allowed locally. Use repo scripts such as python3 scripts/tests.py run instead."

    if command == "vitest":
        return "BLOCKED: Use python3 scripts/tests.py run --suite vitest instead of local Vitest."

    if command == "playwright" and next_non_option(args) == "test":
        return "BLOCKED: Use python3 scripts/tests.py run --spec <name>.spec.ts instead of local Playwright."

    if command != "git":
        return None

    subcommand, subcommand_args = git_subcommand(args)
    if subcommand == "commit":
        return "BLOCKED: Use sessions.py deploy instead of raw git commit. It handles linting, translation validation, and session tracking."
    if subcommand == "push":
        return "BLOCKED: Use sessions.py deploy instead of raw git push. It handles session tracking and deploy coordination."
    if subcommand == "stash":
        return "BLOCKED: git stash is forbidden. Commit your work via sessions.py deploy instead."
    if subcommand == "worktree":
        return "BLOCKED: raw git worktree is forbidden. Use python3 scripts/sessions.py worktree ensure --session <id> so metadata and cleanup stay consistent."
    if subcommand == "add" and any(arg in {"-A", "--all", "."} for arg in subcommand_args):
        return "BLOCKED: git add -A / git add . stages everything. Add specific files by name instead."
    return None


def git_subcommand(args: list[str]) -> tuple[str, list[str]]:
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            index += 1
            break
        if arg.startswith("-"):
            index = skip_option(args, index, GIT_OPTIONS_WITH_VALUES)
            continue
        return basename(arg), args[index + 1 :]
    if index < len(args):
        return basename(args[index]), args[index + 1 :]
    return "", []


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else ""
    for segment in segments(tokenize(command)):
        executable, args = unwrap_invocation(segment)
        reason = check_invocation(executable, args)
        if reason:
            return block(reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
