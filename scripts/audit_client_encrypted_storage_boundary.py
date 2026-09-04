#!/usr/bin/env python3
"""Audit client encrypted-storage boundaries and storage-safe logging.

Purpose: ensure local SDK boundary tests assert cleartext public output and
encrypted durable write payloads together.
Architecture: deterministic source audit over focused SDK tests and S3 services.
Security: checks durable ciphertext assertions and rejects raw object or physical
bucket identifiers in storage log calls.
Spec: docs/specs/sdk-cleartext-encryption-boundary/spec.yml.
"""

from __future__ import annotations

import ast
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
NPM_TEST = ROOT / "frontend/packages/openmates-cli/tests/sdk-cleartext-boundary.test.ts"
PIP_TEST = ROOT / "packages/openmates-python/tests/test_cleartext_boundary.py"
STORAGE_LOG_FILES = [
    ROOT / "backend/core/api/app/services/s3/service.py",
    ROOT / "backend/core/api/app/services/s3/lifecycle.py",
    ROOT / "backend/core/api/app/services/s3/cors.py",
]
PRIVATE_LOG_NAMES = {"bucket_name", "regional_bucket", "file_key", "object_key"}

REQUIRED_MARKERS = {
    NPM_TEST: [
        "CLEAR_PUBLIC_TASK",
        "CLEAR_PUBLIC_PLAN",
        "CLEAR_PUBLIC_PROJECT",
        "encrypted_title",
        "assertNoPlaintextMarker",
    ],
    PIP_TEST: [
        "CLEAR_PUBLIC_TASK",
        "CLEAR_PUBLIC_PLAN",
        "CLEAR_PUBLIC_PROJECT",
        "encrypted_title",
        "_assert_no_plaintext_marker",
    ],
}


def main() -> int:
    failures: list[str] = []
    for path, markers in REQUIRED_MARKERS.items():
        if not path.is_file():
            failures.append(f"Missing boundary test {path.relative_to(ROOT)}")
            continue
        source = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in source:
                failures.append(f"{path.relative_to(ROOT)} missing marker/assertion {marker}")
    for path in STORAGE_LOG_FILES:
        failures.extend(_storage_log_failures(path))
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("PASS client encrypted storage boundary")
    return 0


def _storage_log_failures(path: Path) -> list[str]:
    """Return logger calls that interpolate private bucket or object identifiers."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    failures = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"debug", "info", "warning", "error", "exception", "critical"}:
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id != "logger":
            continue
        interpolated_names = {
            child.id
            for argument in node.args
            for child in ast.walk(argument)
            if isinstance(child, ast.Name) and child.id in PRIVATE_LOG_NAMES
        }
        if interpolated_names:
            failures.append(
                f"{path.relative_to(ROOT)}:{node.lineno} logs private storage identifiers: "
                + ", ".join(sorted(interpolated_names))
            )
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
