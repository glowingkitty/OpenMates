#!/usr/bin/env python3
"""Generate public SDK reference and test coverage matrix docs.

Purpose: keep developer-facing SDK docs synchronized with the public npm/pip SDK
surface that the parity audit enforces.
Architecture: renders Markdown from scripts/sdk_reference_common.py and can run
in check mode for deploy/CI gates.
Security: documents cleartext SDK calls only; encryption details remain internal.
Spec: docs/specs/sdk-cleartext-encryption-boundary/spec.yml.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys

from sdk_reference_common import SdkMethodReference, collect_sdk_method_references, references_by_namespace


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DOC = ROOT / "docs" / "user-guide" / "developers" / "sdk-reference.md"
TEST_COVERAGE_DOC = ROOT / "docs" / "user-guide" / "developers" / "sdk-test-coverage.md"
NPM_TEST_DIR = ROOT / "frontend" / "packages" / "openmates-cli" / "tests"
PIP_TEST_DIR = ROOT / "packages" / "openmates-python" / "tests"

NAMESPACE_TEST_FILES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "account": (("sdk.test.ts", "account-export-sdk.test.ts", "account-import-sdk.test.ts"), ("test_sdk.py", "test_account_export.py", "test_account_import.py")),
    "api_keys": (("sdk.test.ts",), ("test_sdk.py",)),
    "benchmark": (("client.test.ts",), ("test_sdk.py",)),
    "billing": (("sdk.test.ts", "billing.test.ts"), ("test_sdk.py",)),
    "chats": (("sdk.test.ts", "sdk-cleartext-boundary.test.ts"), ("test_sdk.py", "test_cleartext_boundary.py")),
    "connected_accounts": (("connectedAccountImport.test.ts", "sdk.test.ts"), ("test_sdk.py",)),
    "design": (("sdkGenerator.test.ts",), ("test_sdk_generator.py",)),
    "docs": (("sdk.test.ts",), ("test_sdk.py",)),
    "drafts": (("sdk-draft-sync.test.ts", "draft-sync.test.ts"), ("test_draft_sync.py",)),
    "embeds": (("embedRenderers.test.ts", "shareEncryption.test.ts"), ("test_sdk.py",)),
    "feedback": (("sdk.test.ts",), ("test_sdk.py",)),
    "finance": (("sdk.test.ts",), ("test_sdk.py",)),
    "history": (("sdk-workspace-history.test.ts",), ("test_sdk.py",)),
    "ideabucket": (("ideabucket.test.ts", "sdk.test.ts"), ("test_sdk.py",)),
    "inspirations": (("sdk.test.ts",), ("test_sdk.py",)),
    "learning_mode": (("client.test.ts",), ("test_sdk.py",)),
    "memories": (("sdk.test.ts",), ("test_sdk.py",)),
    "new_chat_suggestions": (("client.test.ts",), ("test_sdk.py",)),
    "notifications": (("sdk.test.ts",), ("test_sdk.py",)),
    "plans": (("sdk-plans.test.ts",), ("test_plans.py",)),
    "projects": (("sdk-projects.test.ts",), ("test_projects.py",)),
    "reminders": (("sdk.test.ts",), ("test_sdk.py",)),
    "settings": (("sdk.test.ts",), ("test_sdk.py",)),
    "tasks": (("sdk-tasks.test.ts",), ("test_tasks.py",)),
    "teams": (("sdk-teams.test.ts",), ("test_teams.py",)),
    "workflows": (("sdk-workflows.test.ts", "workflows.test.ts"), ("test_workflows.py",)),
}


@dataclass(frozen=True)
class CoverageRow:
    reference: SdkMethodReference
    npm_status: str
    pip_status: str


def _fmt_inputs(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "none"


def _read_many(paths: list[Path]) -> str:
    chunks: list[str] = []
    for path in paths:
        if path.exists():
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks).lower()


def _method_mentioned(text: str, namespace: str, method: str) -> bool:
    lowered = method.lower()
    return lowered in text or f".{lowered}(" in text or f"{namespace}.{lowered}" in text


def _coverage_status(reference: SdkMethodReference, *, npm_text: str, pip_text: str) -> CoverageRow:
    npm_direct = _method_mentioned(npm_text, reference.npm_namespace, reference.npm_method)
    pip_direct = _method_mentioned(pip_text, reference.pip_namespace, reference.pip_method)
    npm_files, pip_files = NAMESPACE_TEST_FILES.get(reference.namespace, ((), ()))
    npm_status = "direct" if npm_direct else f"namespace smoke: {', '.join(npm_files)}" if npm_files else "missing"
    pip_status = "direct" if pip_direct else f"namespace smoke: {', '.join(pip_files)}" if pip_files else "missing"
    return CoverageRow(reference, npm_status, pip_status)


def build_reference_doc() -> str:
    lines = [
        "---",
        "status: generated",
        "last_verified: 2026-07-26",
        "source: scripts/generate_sdk_reference.py",
        "---",
        "",
        "# OpenMates SDK Reference",
        "",
        "This generated reference lists every public npm and pip SDK method that must stay in parity.",
        "Public SDK methods accept cleartext inputs and return cleartext outputs; encryption and decryption happen inside the SDKs.",
        "",
        "Run `python3 scripts/generate_sdk_reference.py --check` to verify this file is current.",
        "",
    ]
    for namespace, methods in references_by_namespace().items():
        lines.extend([
            f"## `{namespace}`",
            "",
            "| npm | pip | npm inputs | pip inputs | Return |",
            "| --- | --- | --- | --- | --- |",
        ])
        for method in methods:
            lines.append(
                f"| `{method.npm_call}` | `{method.pip_call}` | `{_fmt_inputs(method.npm_inputs)}` | "
                f"`{_fmt_inputs(method.pip_inputs)}` | `{method.output_category}` |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_test_coverage_doc() -> tuple[str, list[str]]:
    references = collect_sdk_method_references()
    npm_text = _read_many(list(NPM_TEST_DIR.glob("*.test.ts")))
    pip_text = _read_many(list(PIP_TEST_DIR.glob("test_*.py")))
    rows = [_coverage_status(reference, npm_text=npm_text, pip_text=pip_text) for reference in references]
    failures = [row.reference.key for row in rows if "missing" in {row.npm_status, row.pip_status}]
    lines = [
        "---",
        "status: generated",
        "last_verified: 2026-07-26",
        "source: scripts/generate_sdk_reference.py",
        "---",
        "",
        "# OpenMates SDK Test Coverage Matrix",
        "",
        "This generated matrix maps every public SDK method to direct test mentions or namespace-level smoke coverage.",
        "The deploy gate fails when a method has neither direct nor namespace coverage in either package.",
        "",
        "Run `python3 scripts/audit_sdk_test_coverage.py` to verify this file is current and complete.",
        "",
        "| Namespace | npm | pip | npm coverage | pip coverage |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row.reference.namespace}` | `{row.reference.npm_call}` | `{row.reference.pip_call}` | "
            f"{row.npm_status} | {row.pip_status} |"
        )
    return "\n".join(lines).rstrip() + "\n", failures


def _check(path: Path, expected: str) -> bool:
    if not path.exists():
        print(f"FAIL missing generated file: {path}", file=sys.stderr)
        return False
    actual = path.read_text(encoding="utf-8")
    if actual != expected:
        print(f"FAIL generated file is stale: {path}", file=sys.stderr)
        print("Run: python3 scripts/generate_sdk_reference.py --write", file=sys.stderr)
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or check SDK reference docs")
    parser.add_argument("--write", action="store_true", help="Write generated docs")
    parser.add_argument("--check", action="store_true", help="Check generated docs without writing")
    args = parser.parse_args()
    reference_doc = build_reference_doc()
    coverage_doc, failures = build_test_coverage_doc()

    if failures:
        for failure in failures:
            print(f"FAIL SDK method lacks test coverage mapping: {failure}", file=sys.stderr)
        return 1

    if args.write:
        REFERENCE_DOC.write_text(reference_doc, encoding="utf-8")
        TEST_COVERAGE_DOC.write_text(coverage_doc, encoding="utf-8")
        print(f"Wrote {REFERENCE_DOC}")
        print(f"Wrote {TEST_COVERAGE_DOC}")
        return 0

    if not args.check:
        print(reference_doc)
        return 0
    ok = _check(REFERENCE_DOC, reference_doc)
    ok = _check(TEST_COVERAGE_DOC, coverage_doc) and ok
    if ok:
        print("PASS sdk generated reference docs")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
