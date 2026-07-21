#!/usr/bin/env python3
"""
Print cross-surface readiness for durable OpenMates features.

This is a static matrix for planning and handoff. It does not prove behavior;
it shows whether the expected CLI, SDK, web, Apple, docs, and test surfaces are
present so agents stop re-discovering the same implementation map.

Architecture: docs/contributing/guides/testing.md
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ReadinessRow:
    surface: str
    status: str
    evidence: str
    next_step: str = ""


def _contains(path: str, needles: tuple[str, ...]) -> bool:
    file_path = REPO_ROOT / path
    candidates = [file_path] if file_path.is_file() else []
    if file_path.is_dir():
        candidates = [candidate for candidate in file_path.rglob("*") if candidate.suffix in {".swift", ".ts", ".py", ".svelte", ".md"}]
    for candidate in candidates:
        text = candidate.read_text(encoding="utf-8", errors="ignore").lower()
        if all(needle.lower() in text for needle in needles):
            return True
    return False


def _exists(path: str) -> bool:
    return (REPO_ROOT / path).exists()


def _row(surface: str, ok: bool, evidence: str, next_step: str) -> ReadinessRow:
    return ReadinessRow(surface, "present" if ok else "missing", evidence, "" if ok else next_step)


def workflows_readiness() -> list[ReadinessRow]:
    return [
        _row(
            "backend API",
            _exists("backend/core/api/app/routes/workflows.py") and _exists("backend/core/api/app/services/workflow_runner.py"),
            "backend/core/api/app/routes/workflows.py + workflow_runner.py",
            "Implement or restore workflow backend route/runtime services.",
        ),
        _row(
            "CLI",
            _contains("frontend/packages/openmates-cli/src/cli.ts", ("workflow",)),
            "frontend/packages/openmates-cli/src/cli.ts contains workflow commands",
            "Add workflow commands to the OpenMates CLI.",
        ),
        _row(
            "npm SDK",
            _contains("frontend/packages/openmates-cli/src/sdk.ts", ("workflow",)),
            "frontend/packages/openmates-cli/src/sdk.ts contains workflow facade",
            "Expose workflow runtime APIs in the npm SDK facade.",
        ),
        _row(
            "pip SDK",
            _contains("packages/openmates-python/openmates/sdk.py", ("workflow",)),
            "packages/openmates-python/openmates/sdk.py contains workflow facade",
            "Expose workflow runtime APIs in the Python SDK.",
        ),
        _row(
            "web UI",
            _exists("frontend/apps/web_app/src/routes/workflows/+page.svelte"),
            "frontend/apps/web_app/src/routes/workflows/+page.svelte",
            "Add or restore the web workflow route.",
        ),
        _row(
            "web E2E",
            _exists("frontend/apps/web_app/tests/workflows-editor.spec.ts") or _exists("frontend/apps/web_app/tests/cli-workflows-rain-real.spec.ts"),
            "workflow Playwright specs under frontend/apps/web_app/tests",
            "Add deployed Playwright coverage for the workflow user path.",
        ),
        _row(
            "Apple parity",
            _contains("apple/OpenMates", ("workflow",)) if _exists("apple/OpenMates") else False,
            "apple/OpenMates contains workflow references",
            "Record Apple not affected or add native workflow parity evidence.",
        ),
        _row(
            "spec evidence",
            _exists("docs/specs/workflows-v1/spec.yml") or _exists("docs/specs/workflows-cli-runtime/spec.yml"),
            "docs/specs/workflows-*/spec.yml",
            "Create or update executable workflow spec evidence.",
        ),
    ]


FEATURES = {"workflows": workflows_readiness}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print feature readiness across product surfaces")
    parser.add_argument("feature", choices=sorted(FEATURES))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    rows = FEATURES[args.feature]()
    if args.json:
        print(json.dumps([asdict(row) for row in rows], indent=2, sort_keys=True))
    else:
        for row in rows:
            suffix = f" | next: {row.next_step}" if row.next_step else ""
            print(f"{row.surface}: {row.status} | {row.evidence}{suffix}")
    return 1 if any(row.status == "missing" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
