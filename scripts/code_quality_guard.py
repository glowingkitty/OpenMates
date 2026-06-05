#!/usr/bin/env python3
"""Staged-change maintainability guard for OpenMates commits.

The guard checks only staged changes and is intentionally conservative. It
blocks high-confidence debt such as editing generated locale JSON, likely
hardcoded secrets, and new large source files. Other maintainability signals are
reported as warnings unless CODE_QUALITY_GUARD_STRICT=1 is set.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_EXTENSIONS = {".py", ".ts", ".tsx", ".svelte", ".js", ".mjs", ".css", ".swift"}
NEW_FILE_LINE_LIMIT = 800
TOUCHED_FILE_WARNING_LIMIT = 2500
PUBLIC_COMPOSE_PORTS = {"80", "443"}

BLOCK_PATTERNS = {
    "hardcoded secret-like assignment": re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{8,}"),
}

WARN_PATTERNS = {
    "new lint/type suppression": re.compile(r"@ts-ignore|@ts-expect-error|eslint-disable|noqa|type:\s*ignore|svelte-ignore"),
    "new broad exception/catch": re.compile(r"except\s+Exception|except\s*:\s*$|catch\s*\([^)]*\)"),
    "new TODO/FIXME/HACK marker": re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE),
    "new store-internal import": re.compile(r"from\s+['\"][^'\"]*stores/[^'\"]+['\"]"),
    "new backend cross-skill import": re.compile(r"from\s+backend\.apps\.([^\.]+)\.skills|import\s+backend\.apps\.([^\.]+)\.skills"),
}


def _git(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=check)


def _staged_files() -> list[str]:
    result = _git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _added_lines() -> list[tuple[str, str]]:
    result = _git(["diff", "--cached", "--unified=0"], check=False)
    current_file = ""
    added: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
            continue
        if line.startswith("+") and not line.startswith("+++") and current_file:
            added.append((current_file, line[1:]))
    return added


def _is_new_file(path: str) -> bool:
    result = _git(["diff", "--cached", "--name-status", "--", path], check=False)
    return any(line.startswith("A\t") for line in result.stdout.splitlines())


def _staged_file_line_count(path: str) -> int:
    result = _git(["show", f":{path}"], check=False)
    if result.returncode != 0:
        return 0
    return len(result.stdout.splitlines())


def _is_compose_file(path: str) -> bool:
    name = Path(path).name
    return name.startswith("docker-compose") and Path(path).suffix in {".yml", ".yaml"}


def _unsafe_compose_port_publish(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("-"):
        if re.match(r"published\s*:", stripped):
            return "long-form published ports must include host_ip: 127.0.0.1 unless explicitly reviewed"
        return None

    value = stripped[1:].strip().strip('"\'')
    value = value.split(" #", 1)[0].strip()
    if ":" not in value:
        return None
    if value.startswith(("127.0.0.1:", "localhost:", "[::1]:")):
        return None
    if value.startswith(("0.0.0.0:", "[::]:")):
        return "binds to all interfaces"
    if value.split(":", 1)[0] not in PUBLIC_COMPOSE_PORTS:
        return "host port is not allowlisted for public exposure"
    return None


def main() -> int:
    strict = os.environ.get("CODE_QUALITY_GUARD_STRICT", "").lower() in {"1", "true", "yes"}
    blocks: list[str] = []
    warnings: list[str] = []

    for path in _staged_files():
        suffix = Path(path).suffix
        if re.search(r"frontend/packages/ui/src/i18n/locales/.*\.json$", path):
            blocks.append(f"{path}: generated translation JSON must not be committed directly; edit YAML sources instead")
            continue
        if suffix not in SOURCE_EXTENSIONS:
            continue
        line_count = _staged_file_line_count(path)
        if _is_new_file(path) and line_count > NEW_FILE_LINE_LIMIT:
            blocks.append(f"{path}: new source file has {line_count} lines; split before committing (limit {NEW_FILE_LINE_LIMIT})")
        elif line_count > TOUCHED_FILE_WARNING_LIMIT:
            warnings.append(f"{path}: touched source file is {line_count} lines; prefer extraction over adding more responsibilities")

    for path, line in _added_lines():
        if _is_compose_file(path):
            reason = _unsafe_compose_port_publish(line)
            if reason:
                blocks.append(
                    f"{path}: unsafe Docker Compose port publish ({reason}); bind to 127.0.0.1 or add an explicit reviewed exception: {line.strip()[:160]}"
                )
            continue
        if Path(path).suffix not in SOURCE_EXTENSIONS:
            continue
        for label, pattern in BLOCK_PATTERNS.items():
            if pattern.search(line):
                blocks.append(f"{path}: added {label}: {line.strip()[:160]}")
        for label, pattern in WARN_PATTERNS.items():
            if pattern.search(line):
                warnings.append(f"{path}: {label}: {line.strip()[:160]}")

    if warnings:
        print("[code-quality] Maintainability warnings:", file=sys.stderr)
        for warning in warnings[:40]:
            print(f"  - {warning}", file=sys.stderr)
        if len(warnings) > 40:
            print(f"  - ... {len(warnings) - 40} more warning(s)", file=sys.stderr)

    if blocks or (strict and warnings):
        print("[code-quality] Commit blocked:", file=sys.stderr)
        for block in blocks[:40]:
            print(f"  - {block}", file=sys.stderr)
        if strict and warnings:
            print("  - CODE_QUALITY_GUARD_STRICT=1 turns warnings into blocking errors", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
