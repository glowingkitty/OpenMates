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
GIT_OPTIONS_WITH_VALUES = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
ENV_OPTIONS_WITH_VALUES = {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}
TIMEOUT_OPTIONS_WITH_VALUES = {"-k", "--kill-after", "-s", "--signal"}
DOCKER_COMPOSE_MUTATIONS = {"build", "down", "kill", "restart", "rm", "start", "stop", "up"}
COMPOSE_OPTIONS_WITH_VALUES = {
    "-f",
    "--file",
    "--env-file",
    "-p",
    "--project-name",
    "--profile",
    "--project-directory",
}


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


def check_invocation(command: str, args: list[str]) -> str | None:
    compose_action = docker_compose_action(command, args)
    if compose_action in DOCKER_COMPOSE_MUTATIONS:
        return (
            "BLOCKED: Direct Docker Compose lifecycle mutations bypass the registered "
            "OpenMates source and service policy. Use openmates server start, stop, "
            "restart, or update instead; for rebuilds use "
            "openmates server restart --rebuild [--services <service>]."
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


def docker_compose_action(command: str, args: list[str]) -> str:
    if command == "docker-compose":
        return compose_action_from_args(args, 0)
    if command != "docker":
        return ""
    try:
        compose_index = next(
            index for index, arg in enumerate(args) if basename(arg) == "compose"
        )
    except StopIteration:
        return ""
    return compose_action_from_args(args, compose_index + 1)


def compose_action_from_args(args: list[str], start_index: int) -> str:
    index = start_index
    while index < len(args):
        arg = args[index]
        if arg == "--":
            index += 1
            continue
        if arg.startswith("-"):
            index = skip_option(args, index, COMPOSE_OPTIONS_WITH_VALUES)
            continue
        return basename(arg)
    return ""


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
