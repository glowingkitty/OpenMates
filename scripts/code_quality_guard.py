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

import audit_embed_structure
import audit_app_provider_contracts
import audit_opencode_automation_budget
import audit_playwright_determinism
import audit_sensitive_logging


REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_EXTENSIONS = {".py", ".ts", ".tsx", ".svelte", ".js", ".mjs", ".css", ".swift"}
NEW_FILE_LINE_LIMIT = 800
TOUCHED_FILE_WARNING_LIMIT = 2500
PUBLIC_COMPOSE_PORTS = {"80", "443"}
EMBED_STRUCTURE_PATH_RE = re.compile(
    r"^(frontend/packages/ui/src/(components/embeds/|data/embedRegistry\.generated\.ts)|scripts/audit_embed_structure\.py)"
)
PLAYWRIGHT_SPEC_PATH_RE = re.compile(r"^frontend/apps/web_app/tests/.*\.(spec|test)\.ts$")
APP_PROVIDER_PATH_RE = re.compile(r"^(backend/apps/[^/]+/app\.yml|backend/providers/.*\.ya?ml)$")
OPENCODE_AUTOMATION_PATH_RE = re.compile(
    r"^(scripts/.*\.(py|sh|js|mjs)|scripts/prompts/.*\.md|\.agents/skills/.*/SKILL\.md|opencode\.json)$"
)

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


def _added_lines_with_numbers() -> list[tuple[str, int, str]]:
    result = _git(["diff", "--cached", "--unified=0"], check=False)
    current_file = ""
    current_line = 0
    added: list[tuple[str, int, str]] = []
    hunk_re = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
    for line in result.stdout.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
            current_line = 0
            continue
        if line.startswith("@@"):
            match = hunk_re.search(line)
            current_line = int(match.group(1)) if match else 0
            continue
        if line.startswith("+") and not line.startswith("+++") and current_file:
            added.append((current_file, current_line, line[1:]))
            current_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue
        elif current_line:
            current_line += 1

    if added:
        return added

    return [(path, 0, line) for path, line in _added_lines()]


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


def _should_run_embed_structure_audit(staged_files: list[str]) -> bool:
    return any(EMBED_STRUCTURE_PATH_RE.search(path) for path in staged_files)


def _paths_matching(staged_files: list[str], pattern: re.Pattern[str]) -> list[Path]:
    return [REPO_ROOT / path for path in staged_files if pattern.search(path)]


def main() -> int:
    strict = os.environ.get("CODE_QUALITY_GUARD_STRICT", "").lower() in {"1", "true", "yes"}
    blocks: list[str] = []
    warnings: list[str] = []

    staged_files = _staged_files()

    if _should_run_embed_structure_audit(staged_files):
        audit_result = audit_embed_structure.audit_embed_structure()
        for issue in audit_result.issues:
            blocks.append(f"embed structure: {issue}")
        for warning in audit_result.warnings:
            blocks.append(f"embed structure: {warning}")

    added_lines_with_numbers = _added_lines_with_numbers()

    for issue in audit_playwright_determinism.audit_added_lines(added_lines_with_numbers):
        blocks.append(f"playwright determinism: {issue.path}:{issue.line}: {issue.message}")

    for issue in audit_playwright_determinism.audit_reserved_account_specs(_paths_matching(staged_files, PLAYWRIGHT_SPEC_PATH_RE)):
        blocks.append(f"playwright determinism: {issue.path}:{issue.line}: {issue.message}")

    for issue in audit_app_provider_contracts.audit_paths(_paths_matching(staged_files, APP_PROVIDER_PATH_RE)):
        blocks.append(f"app/provider contract: {issue.path}: {issue.message}")

    for issue in audit_opencode_automation_budget.audit_paths(_paths_matching(staged_files, OPENCODE_AUTOMATION_PATH_RE)):
        blocks.append(f"opencode automation budget: {issue.path}: {issue.message}")

    for path in staged_files:
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

    for issue in audit_sensitive_logging.audit_added_lines(added_lines_with_numbers):
        line_label = f":{issue.line}" if issue.line else ""
        blocks.append(f"sensitive logging: {issue.path}{line_label}: {issue.message}")

    added_lines = [(path, line) for path, _line_no, line in added_lines_with_numbers]
    for path, line in added_lines:
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
