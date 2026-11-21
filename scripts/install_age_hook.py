#!/usr/bin/env python3
"""Bash PreToolUse helper: refuse package installs that are not age-checked.

Called by .claude/hooks/bash-guard.sh as `install_age_hook.py <command>` after a
cheap regex pre-filter. Exit 0 = allowed, 2 = refused (message on stderr).

Pass-through (re-verified here by re-running the check, so it cannot be faked):
    OPENMATES_AGE_CHECKED=<ecosystem>:<name>@<version>[,...] [OPENMATES_AGE_KEV=CVE-...] <install command>
"""

from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import install_age_guard as guard  # noqa: E402 - path insert above

WRAPPERS = {"sudo", "env", "command", "time", "nohup", "exec"}
VALUE_FLAGS = {
    "node": {"--filter", "-F", "-C", "--dir", "--prefix", "--workspace", "-w", "--cwd", "--registry", "--tag"},
    "pip": {"-r", "--requirement", "-c", "--constraint", "-e", "--editable", "-i", "--index-url", "--extra-index-url",
            "-f", "--find-links", "-t", "--target", "--prefix", "--root", "--python", "--no-binary", "--only-binary",
            "--platform", "--python-version", "--implementation", "--abi", "--group", "--dev-group"},
    "cargo": {"--version", "--vers", "--path", "--git", "--branch", "--tag", "--rev", "--root", "--features", "-F",
              "--registry", "--index", "--target", "--package", "-p", "--manifest-path", "--bin", "--example",
              "--rename", "--target-dir", "--profile", "--jobs", "-j", "--color", "--config"},
}
KEV_RE = re.compile(r"^CVE-\d{4}-\d{4,}$", re.I)
CHECKED_RE = re.compile(r"^(npm|PyPI|crates\.io):(.+)@([^@]+)$")
LOCAL_PREFIXES = (".", "/", "~", "file:", "link:", "workspace:")
UNHASHED_REQUIREMENTS = "-r <requirements file without --require-hashes>"


def _segments(command: str) -> list[list[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    segments: list[list[str]] = [[]]
    for token in lexer:
        if set(token) <= set("();&|<>"):
            if token in (";", "&&", "||", "|", "&", "(", ")", ";;"):
                segments.append([])
            continue
        segments[-1].append(token)
    return [s for s in segments if s]


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _split_spec(kind: str, spec: str) -> tuple[str, str | None] | None:
    """Return (name, exact version or None); None for local paths (not registry installs)."""
    if spec.startswith(LOCAL_PREFIXES) or spec.endswith((".whl", ".tgz", ".tar.gz")):
        return None
    if kind == "pip":
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?(?:==([^\s;,*]+))?$", spec)
        return (match.group(1), match.group(3)) if match else (spec, None)
    body = spec[1:] if spec.startswith("@") else spec
    name, sep, version = body.partition("@")
    name = "@" + name if spec.startswith("@") else name
    version = version.lstrip("=")
    exact = bool(sep) and re.match(r"^v?\d+(\.\d+)*([-+][0-9A-Za-z.+-]+)?$", version) is not None
    return name, (version if exact else None)


def _parse(tokens: list[str]) -> tuple[dict[str, str], str, str, list[str]] | None:
    """Return (env, ecosystem, kind, package specs) for an install command, else None."""
    env: dict[str, str] = {}
    i = 0
    while i < len(tokens):
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[i]):
            key, _, value = tokens[i].partition("=")
            env[key] = value
        elif tokens[i] not in WRAPPERS and not tokens[i].startswith("-"):
            break
        i += 1
    if i >= len(tokens):
        return None
    tool, args = Path(tokens[i]).name, tokens[i + 1:]
    if re.match(r"^python[0-9.]*$", tool) and args[:2] == ["-m", "pip"]:
        tool, args = "pip", args[2:]
    elif tool == "uv":
        sub = next((a for a in args if not a.startswith("-")), "")
        if sub == "pip":
            tool, args = "pip", args[args.index("pip") + 1:]
        elif sub == "add":
            tool, args = "uvadd", args[args.index("add"):]
        else:
            return None
    if tool in ("npm", "pnpm", "yarn"):
        kind, eco = "node", "npm"
        adders = {"add"} if tool == "yarn" else {"install", "i", "add", "install-test", "it"}
    elif tool == "pip" or re.match(r"^pip[0-9.]*$", tool):
        kind, eco, adders = "pip", "PyPI", {"install"}
    elif tool == "uvadd":
        kind, eco, adders = "pip", "PyPI", {"add"}
    elif tool == "cargo":
        kind, eco, adders = "cargo", "crates.io", {"add", "install"}
    else:
        return None
    positional: list[str] = []
    flags: dict[str, str] = {}
    pending = ""
    for arg in args:
        if pending:
            flags[pending] = arg
            pending = ""
        elif arg.startswith("-"):
            flag, _, value = arg.partition("=")
            flags[flag] = value
            if not value and flag in VALUE_FLAGS[kind]:
                pending = flag
        else:
            positional.append(arg)
    if not positional or positional[0] not in adders:
        return None
    specs = positional[1:]
    if kind == "pip":
        if "--require-hashes" in flags:
            return env, eco, kind, []
        if flags.keys() & {"-r", "--requirement"} and tool != "uvadd":
            specs.append(UNHASHED_REQUIREMENTS)
    elif kind == "cargo":
        if positional[0] == "install" and flags.keys() & {"--path", "--git"}:
            return env, eco, kind, []
        version = flags.get("--version") or flags.get("--vers")
        if version:
            specs = [s if "@" in s else f"{s}@{version.lstrip('=')}" for s in specs]
    return env, eco, kind, specs


def _refuse(message: str) -> int:
    sys.stderr.write(
        "BLOCKED: " + message + "\nPolicy: a package version may be installed only after 7 days of public release "
        "(unless it fixes a CISA-KEV exploited flaw; pip installs use --require-hashes).\n"
        "Run: python3 scripts/install_age_guard.py check --ecosystem <npm|PyPI|crates.io> --name <pkg> "
        "[--version <v>] [--kev <CVE-id>]\nThen re-run with the exact checked version as a prefix, e.g. "
        "OPENMATES_AGE_CHECKED=npm:<pkg>@<version> [OPENMATES_AGE_KEV=CVE-...] <install command using <pkg>@<version>> "
        "(the hook re-runs the check). Lockfile installs (frozen-lockfile, pip -r X --require-hashes) stay allowed.\n")
    return 2


def check_command(command: str) -> int:
    try:
        segments = _segments(command)
    except ValueError:
        return 0  # unparsable quoting: nothing attributable to an install; other guards apply
    for tokens in segments:
        parsed = _parse(tokens)
        if parsed is None:
            continue
        env, eco, kind, specs = parsed
        checked = {}
        for entry in filter(None, env.get("OPENMATES_AGE_CHECKED", "").split(",")):
            match = CHECKED_RE.match(entry)
            if match:
                checked[(match.group(1), _norm(match.group(2)))] = match.group(3)
        kev = env.get("OPENMATES_AGE_KEV") or None
        if kev and not KEV_RE.match(kev):
            return _refuse(f"OPENMATES_AGE_KEV must be a CVE id, got {kev!r}")
        for spec in specs:
            if spec == UNHASHED_REQUIREMENTS:
                return _refuse("pip install -r requires --require-hashes")
            split = _split_spec(kind, spec)
            if split is None:
                continue
            name, version = split
            if version is None or checked.get((eco, _norm(name))) != version:
                form = "name==version" if kind == "pip" else "name@version"
                return _refuse(f"{eco} package {spec!r} is not age-checked; use an exact {form} that matches OPENMATES_AGE_CHECKED.")
            result = guard.decide(eco, name, version, kev)
            if not result["allowed"]:
                hint = f" Newest allowed older version: {result['suggested_version']}." if result.get("suggested_version") else ""
                return _refuse(f"{eco}:{name}@{version} refused: {result.get('reason')}.{hint}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    return check_command(argv[0]) if argv else 0


if __name__ == "__main__":
    sys.exit(main())
