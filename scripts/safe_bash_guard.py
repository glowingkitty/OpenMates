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


SEPARATORS = {";", "&", "&&", "||", "|", "(", ")"}
INSTALL_SUBCOMMANDS = {"add", "install", "i"}
GIT_OPTIONS_WITH_VALUES = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
ENV_OPTIONS_WITH_VALUES = {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}
TIMEOUT_OPTIONS_WITH_VALUES = {"-k", "--kill-after", "-s", "--signal"}
PNPM_OPTIONS_WITH_VALUES = {
    "-C",
    "--dir",
    "--prefix",
    "-w",
    "--workspace-root",
    "--filter",
    "-F",
}
NPX_OPTIONS_WITH_VALUES = {"-c", "--call", "-p", "--package", "--cache", "--userconfig"}
STATIC_BINARIES = {"eslint", "svelte-check", "svelte-kit", "tsc", "tsup", "vite", "vitest"}
WATCH_FLAGS = {"-w", "--watch", "--watchAll", "--watch-all"}
SHELL_EXECUTABLES = {"bash", "dash", "ksh", "sh", "zsh"}
REPO_ROOT = Path(__file__).resolve().parents[1]
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
    lexer = shlex.shlex(_normalise_shell_newlines(command), posix=True, punctuation_chars=";&|()")
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        # Let malformed shell syntax fail in Bash instead of guessing.
        return []


def _normalise_shell_newlines(command: str) -> str:
    """Treat unquoted newlines as shell separators without scanning quoted data."""
    result: list[str] = []
    quote = ""
    escaped = False
    for char in command:
        if escaped:
            result.append(char)
            escaped = False
            continue
        if char == "\\" and quote != "'":
            result.append(char)
            escaped = True
            continue
        if char in {"'", '"'}:
            if not quote:
                quote = char
            elif quote == char:
                quote = ""
            result.append(char)
            continue
        result.append(";" if char == "\n" and not quote else char)
    return "".join(result)


def embedded_shell_commands(command: str) -> list[str]:
    """Return command/process substitutions while ignoring single-quoted data."""
    found: list[str] = []
    quote = ""
    escaped = False
    index = 0
    while index < len(command):
        char = command[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\" and quote != "'":
            escaped = True
            index += 1
            continue
        if char == "'":
            quote = "" if quote == "'" else ("'" if not quote else quote)
            index += 1
            continue
        if char == '"':
            quote = "" if quote == '"' else ('"' if not quote else quote)
            index += 1
            continue
        if quote != "'" and char == "`":
            end = index + 1
            while end < len(command) and command[end] != "`":
                end += 2 if command[end] == "\\" else 1
            if end < len(command):
                found.append(command[index + 1 : end])
                index = end + 1
                continue
        if quote != "'" and (
            command.startswith("$(", index)
            or command.startswith("<(", index)
            or command.startswith(">(", index)
        ):
            start = index + 2
            depth = 1
            inner_quote = ""
            inner_escaped = False
            end = start
            while end < len(command) and depth:
                current = command[end]
                if inner_escaped:
                    inner_escaped = False
                elif current == "\\" and inner_quote != "'":
                    inner_escaped = True
                elif current in {"'", '"'}:
                    if not inner_quote:
                        inner_quote = current
                    elif inner_quote == current:
                        inner_quote = ""
                elif not inner_quote:
                    if current == "(":
                        depth += 1
                    elif current == ")":
                        depth -= 1
                end += 1
            if depth == 0:
                found.append(command[start : end - 1])
                index = end
                continue
        index += 1
    return found


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


def check_invocation(command: str, args: list[str], *, cwd: Path = REPO_ROOT) -> str | None:
    compose_action = docker_compose_action(command, args)
    if compose_action in DOCKER_COMPOSE_MUTATIONS:
        return (
            "BLOCKED: Direct Docker Compose lifecycle mutations bypass the registered "
            "OpenMates source and service policy. Use openmates server start, stop, "
            "restart, or update instead; for rebuilds use "
            "openmates server restart --rebuild [--services <service>]."
        )

    if command == "pnpm":
        return check_pnpm(args, cwd=cwd)

    if command == "npx":
        return check_npx(args)

    if command == "vitest":
        return check_static_binary(command, args)

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
    if subcommand == "reset" and "--hard" in subcommand_args:
        return "BLOCKED: git reset --hard can destroy uncommitted work and is forbidden."
    if subcommand == "clean" and any(
        arg == "--force" or (arg.startswith("-") and not arg.startswith("--") and "f" in arg[1:])
        for arg in subcommand_args
    ):
        return "BLOCKED: forced git clean can destroy untracked work and is forbidden."
    if subcommand == "worktree":
        return "BLOCKED: raw git worktree is forbidden. Use python3 scripts/sessions.py worktree ensure --session <id> so metadata and cleanup stay consistent."
    if subcommand in {"switch", "checkout"} and any(
        arg in {"-c", "-C", "-b", "-B", "--create", "--orphan"}
        or arg.startswith(("--create=", "--orphan="))
        for arg in subcommand_args
    ):
        return "BLOCKED: OpenMates permits only dev and main branches. Use a detached sessions.py worktree instead of creating a branch."
    if subcommand == "branch":
        mutation_flags = {"-c", "-C", "-d", "-D", "-m", "-M", "--copy", "--delete", "--move"}
        if any(arg in mutation_flags for arg in subcommand_args):
            return "BLOCKED: OpenMates branch mutations must use the two-branch invariant tooling; only dev and main may exist."
        if subcommand_args and not any(arg.startswith("-") for arg in subcommand_args):
            return "BLOCKED: OpenMates permits only dev and main branches. Use a detached sessions.py worktree instead of creating a branch."
    if subcommand == "update-ref" and any(arg.startswith("refs/heads/") for arg in subcommand_args):
        return "BLOCKED: Direct branch-ref mutation is forbidden; OpenMates permits only dev and main branches."
    if subcommand == "add" and any(arg in {"-A", "--all", "."} for arg in subcommand_args):
        return "BLOCKED: git add -A / git add . stages everything. Add specific files by name instead."
    return None


def _unsafe_local_check_reason(detail: str) -> str:
    return (
        "BLOCKED: local pnpm/npx commands are limited to parsed, repository-scoped "
        "lint, typecheck, unit-test, and compile checks. Product/browser E2E, dev "
        f"servers, watch mode, package download, and unknown scripts stay in isolated CI ({detail})."
    )


def _parse_options(
    args: list[str], options_with_values: set[str]
) -> tuple[list[str], dict[str, str], str | None]:
    remaining: list[str] = []
    values: dict[str, str] = {}
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            remaining.extend(args[index + 1 :])
            break
        matched = next(
            (option for option in options_with_values if option.startswith("--") and arg.startswith(f"{option}=")),
            None,
        )
        if matched:
            values[matched] = arg.split("=", 1)[1]
            index += 1
            continue
        if arg in options_with_values:
            if arg in {"-w", "--workspace-root"}:
                values[arg] = "true"
                index += 1
                continue
            if index + 1 >= len(args):
                return [], {}, f"{arg} is missing its value"
            values[arg] = args[index + 1]
            index += 2
            continue
        if arg.startswith("-"):
            # Preserve action-specific flags for the binary/script classifier.
            remaining.append(arg)
            index += 1
            continue
        remaining.extend(args[index:])
        break
    return remaining, values, None


def check_pnpm(
    args: list[str], *, cwd: Path, visited: set[tuple[Path, str]] | None = None
) -> str | None:
    remaining, options, error = _parse_options(args, PNPM_OPTIONS_WITH_VALUES)
    if error:
        return _unsafe_local_check_reason(error)
    if any(option in options for option in {"--filter", "-F"}):
        return _unsafe_local_check_reason("workspace filters are not a single inspected package")
    if not remaining:
        return _unsafe_local_check_reason("missing pnpm action")

    package_cwd = cwd
    directory = options.get("--dir") or options.get("-C") or options.get("--prefix")
    if directory:
        package_cwd = _resolved_repo_path(cwd, directory)
        if package_cwd is None:
            return _unsafe_local_check_reason("package directory is outside the repository")
    elif any(option in options for option in {"-w", "--workspace-root"}):
        package_cwd = REPO_ROOT

    action = remaining[0]
    action_args = remaining[1:]
    if action in INSTALL_SUBCOMMANDS:
        return None
    if action in {"dev", "start", "serve", "preview", "dlx"}:
        return _unsafe_local_check_reason(f"pnpm {action} is runtime or package execution")
    if action in {"exec", "x"}:
        executable = next_non_option(action_args)
        if not executable:
            return _unsafe_local_check_reason("pnpm exec is missing a binary")
        if not is_unqualified_executable(executable):
            return _unsafe_local_check_reason("pnpm exec binary must be an unqualified allowlisted name")
        executable_index = action_args.index(executable)
        return check_static_binary(executable, action_args[executable_index + 1 :])

    if action == "run":
        script = next_non_option(action_args)
    elif action.startswith("-"):
        return _unsafe_local_check_reason(f"unsupported pnpm option {action}")
    else:
        script = action
    if not script:
        return _unsafe_local_check_reason("missing package script")
    return check_package_script(package_cwd, script, visited=visited)


def check_npx(args: list[str]) -> str | None:
    remaining, options, error = _parse_options(args, NPX_OPTIONS_WITH_VALUES)
    if error:
        return _unsafe_local_check_reason(error)
    if options:
        return _unsafe_local_check_reason("npx package/call options can execute uninspected code")
    executable = next_non_option(remaining)
    if not executable:
        return _unsafe_local_check_reason("npx is missing a binary")
    if not is_unqualified_executable(executable):
        return _unsafe_local_check_reason("npx binary must be an unqualified allowlisted name")
    executable_index = remaining.index(executable)
    return check_static_binary(executable, remaining[executable_index + 1 :])


def is_unqualified_executable(executable: str) -> bool:
    return bool(executable) and "/" not in executable and "\\" not in executable


def _watch_mode_requested(args: list[str]) -> bool:
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in WATCH_FLAGS:
            if index + 1 < len(args) and args[index + 1].lower() == "false":
                index += 2
                continue
            return True
        if any(arg.startswith(f"{flag}=") for flag in WATCH_FLAGS):
            if arg.split("=", 1)[1].lower() != "false":
                return True
        index += 1
    return False


def check_static_binary(command: str, args: list[str]) -> str | None:
    if command not in STATIC_BINARIES:
        return _unsafe_local_check_reason(f"{command or 'unknown binary'} is not an approved check binary")
    if _watch_mode_requested(args):
        return _unsafe_local_check_reason(f"{command} watch mode")
    if command == "eslint" and any(arg == "--fix" or arg.startswith("--fix=") for arg in args):
        return _unsafe_local_check_reason("eslint --fix is a mutation, not a static check")
    if command == "svelte-check":
        return None
    if command == "svelte-kit":
        action = next_non_option(args)
        return None if action == "sync" else _unsafe_local_check_reason("svelte-kit is allowed only for sync")
    if command == "tsc":
        return None
    if command == "tsup":
        return None
    if command == "eslint":
        return None
    if command == "vite":
        action = next_non_option(args)
        return None if action == "build" else _unsafe_local_check_reason("vite is allowed only for compile/build")
    if command == "vitest":
        action = next_non_option(args)
        if action != "run":
            return _unsafe_local_check_reason("vitest must use non-watching 'run' mode")
        if any(arg == "--browser" or arg.startswith("--browser=") or arg == "--ui" for arg in args):
            return _unsafe_local_check_reason("Vitest browser/UI mode is not a local unit check")
        return None
    return _unsafe_local_check_reason(f"unsupported check binary {command}")


def _resolved_repo_path(cwd: Path, value: str) -> Path | None:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = cwd / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(REPO_ROOT)
    except ValueError:
        return None
    return candidate


def _nearest_package_json(cwd: Path) -> Path | None:
    current = cwd.resolve()
    while True:
        try:
            current.relative_to(REPO_ROOT)
        except ValueError:
            return None
        candidate = current / "package.json"
        if candidate.is_file():
            return candidate
        if current == REPO_ROOT:
            return None
        current = current.parent


def check_package_script(cwd: Path, script: str, *, visited: set[tuple[Path, str]] | None = None) -> str | None:
    package_json = _nearest_package_json(cwd)
    if package_json is None:
        return _unsafe_local_check_reason(f"cannot resolve package script {script!r}")
    try:
        scripts = json.loads(package_json.read_text(encoding="utf-8")).get("scripts", {})
    except (OSError, json.JSONDecodeError):
        return _unsafe_local_check_reason(f"cannot inspect {package_json.relative_to(REPO_ROOT)}")
    body = scripts.get(script) if isinstance(scripts, dict) else None
    if not isinstance(body, str) or not body.strip():
        return _unsafe_local_check_reason(f"unknown package script {script!r}")
    if script.startswith("test:real"):
        return _unsafe_local_check_reason(f"{script!r} is a live/product test, not a local unit check")

    key = (package_json, script)
    seen = set() if visited is None else set(visited)
    if key in seen:
        return _unsafe_local_check_reason(f"recursive package script {script!r}")
    seen.add(key)
    script_cwd = package_json.parent
    for segment in segments(tokenize(body)):
        executable, command_args = unwrap_invocation(segment)
        if executable in {"npm", "pnpm"}:
            nested = check_package_manager_script(executable, command_args, cwd=script_cwd, visited=seen)
            if nested:
                return nested
            continue
        if executable == "node" and "--test" in command_args:
            continue
        if executable == "turbo":
            nested = check_turbo_script(command_args, current=key, visited=seen)
            if nested:
                return nested
            continue
        failure = check_static_binary(executable, command_args)
        if failure:
            return _unsafe_local_check_reason(
                f"script {package_json.relative_to(REPO_ROOT)}:{script} contains unapproved command {executable}"
            )
    return None


def check_package_manager_script(
    command: str, args: list[str], *, cwd: Path, visited: set[tuple[Path, str]]
) -> str | None:
    if command == "pnpm":
        return check_pnpm(args, cwd=cwd, visited=visited)
    if not args or args[0] != "run":
        return _unsafe_local_check_reason("npm package scripts must use an inspected 'npm run <script>'")
    script = next_non_option(args[1:])
    return check_package_script(cwd, script, visited=visited) if script else _unsafe_local_check_reason("npm run is missing a script")


def check_turbo_script(
    args: list[str], *, current: tuple[Path, str], visited: set[tuple[Path, str]]
) -> str | None:
    if not args or args[0] != "run" or len(args) < 2 or args[1].startswith("-"):
        return _unsafe_local_check_reason("turbo is allowed only for an inspected 'turbo run <task>'")
    task = args[1]
    if _watch_mode_requested(args[2:]):
        return _unsafe_local_check_reason("turbo watch mode")
    matched = False
    for package_json in REPO_ROOT.rglob("package.json"):
        if "node_modules" in package_json.parts:
            continue
        try:
            scripts = json.loads(package_json.read_text(encoding="utf-8")).get("scripts", {})
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(scripts, dict) or task not in scripts or package_json == current[0]:
            continue
        matched = True
        failure = check_package_script(package_json.parent, task, visited=visited)
        if failure:
            return failure
    return None if matched else _unsafe_local_check_reason(f"turbo task {task!r} has no inspected package scripts")


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


def shell_command_payload(args: list[str]) -> str | None:
    for index, arg in enumerate(args):
        if arg.startswith("-") and not arg.startswith("--") and "c" in arg[1:]:
            if index + 1 < len(args):
                return args[index + 1]
            return None
    return None


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else ""
    cwd = Path.cwd().resolve()
    try:
        cwd.relative_to(REPO_ROOT)
    except ValueError:
        cwd = REPO_ROOT
    pending = [(command, cwd)]
    while pending:
        candidate, candidate_cwd = pending.pop()
        pending.extend((embedded, candidate_cwd) for embedded in embedded_shell_commands(candidate))
        for segment in segments(tokenize(candidate)):
            executable, args = unwrap_invocation(segment)
            if executable == "cd":
                destination = next_non_option(args)
                resolved = _resolved_repo_path(candidate_cwd, destination) if destination else None
                if resolved is None:
                    return block("BLOCKED: local command changes directory outside the OpenMates repository.")
                candidate_cwd = resolved
                continue
            if executable in SHELL_EXECUTABLES:
                payload = shell_command_payload(args)
                if payload is None:
                    return block(
                        "BLOCKED: nested shell execution must use an inspectable shell -c payload."
                    )
                pending.append((payload, candidate_cwd))
                continue
            reason = check_invocation(executable, args, cwd=candidate_cwd)
            if reason:
                return block(reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
