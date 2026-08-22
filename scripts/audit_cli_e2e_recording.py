#!/usr/bin/env python3
"""Audit real Playwright CLI entry points for recorder coverage.

Non-interactive OpenMates CLI commands must use cli-test-helpers.ts, which can
route the first E2E command through the graphical terminal recorder. Direct
spawns are limited to classified interactive pair login and that helper's
normal, non-recording fallback.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent.parent
TEST_ROOT = ROOT / "frontend" / "apps" / "web_app" / "tests"
CLASSIFICATION_RE = re.compile(r"^\s*//\s*cli-e2e-recording:\s*([a-z0-9-]+)\s*$")
DIRECT_CLI_SPAWN_RE = re.compile(
    r"\bspawn\(\s*['\"]node['\"]\s*,\s*\[\s*CLI_DIST\s*,\s*(?P<argument>[^,\]]+)"
)
SUPPORTED_CLASSIFICATIONS = {
    "interactive-pair-login": "login",
    "shared-recorder-fallback": "...allArgs",
}
LEGACY_ENTRY_POINTS: dict[str, dict[str, str]] = {
    "cli-embed-diff-versions.spec.ts": {"login": "interactive-pair-login", "...args": "legacy-direct-command"},
    "cli-file-upload.spec.ts": {"login": "interactive-pair-login", "...args": "legacy-direct-command"},
    "cli-images.spec.ts": {"login": "interactive-pair-login", "...args": "legacy-direct-command"},
    "cli-memories.spec.ts": {"login": "interactive-pair-login", "...args": "legacy-direct-command"},
    "cli-pair-login.spec.ts": {"login": "interactive-pair-login", "...args": "legacy-direct-command"},
    "cli-skills-pdf.spec.ts": {"login": "interactive-pair-login", "...args": "legacy-direct-command"},
    "cross-client-draft-sync.spec.ts": {"login": "interactive-pair-login", "...args": "legacy-direct-command"},
    "shared-chat-embed-assets.spec.ts": {"login": "interactive-pair-login", "...args": "legacy-direct-command"},
    "skill-images-generate-safety.spec.ts": {"login": "interactive-pair-login"},
}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    message: str


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def scan_path(path: Path) -> list[Finding]:
    lines = path.read_text(encoding="utf-8").splitlines()
    findings: list[Finding] = []
    for index, line in enumerate(lines):
        match = DIRECT_CLI_SPAWN_RE.search(line)
        if not match:
            continue
        marker = CLASSIFICATION_RE.match(lines[index - 1]) if index else None
        argument = match.group("argument").strip(" '\"")
        if not marker and argument in LEGACY_ENTRY_POINTS.get(path.name, {}):
            continue
        if not marker:
            findings.append(
                Finding(
                    _display(path),
                    index + 1,
                    "unclassified-direct-spawn",
                    "Route non-interactive CLI execution through cli-test-helpers.ts or classify the direct spawn.",
                )
            )
            continue
        classification = marker.group(1)
        expected_argument = SUPPORTED_CLASSIFICATIONS.get(classification)
        if expected_argument is None or argument != expected_argument:
            findings.append(
                Finding(
                    _display(path),
                    index + 1,
                    "classification-mismatch",
                    f"Classification {classification!r} does not apply to CLI argument {argument!r}.",
                )
            )
    return findings


def build_report() -> dict[str, object]:
    paths = sorted(TEST_ROOT.rglob("*.ts"))
    findings = [finding for path in paths for finding in scan_path(path)]
    return {
        "ok": not findings,
        "scanned_files": len(paths),
        "findings": [asdict(finding) for finding in findings],
        "classifications": sorted(SUPPORTED_CLASSIFICATIONS),
        "legacy_entry_points": LEGACY_ENTRY_POINTS,
    }


def main() -> int:
    report = build_report()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
