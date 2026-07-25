#!/usr/bin/env python3
"""Audit client encrypted-storage boundary test coverage.

Purpose: ensure local SDK boundary tests assert cleartext public output and
encrypted durable write payloads together.
Architecture: deterministic source audit over the focused npm and pip tests.
Security: prevents tests from only checking ergonomics while missing storage
ciphertext assertions.
Spec: docs/specs/sdk-cleartext-encryption-boundary/spec.yml.
"""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
NPM_TEST = ROOT / "frontend/packages/openmates-cli/tests/sdk-cleartext-boundary.test.ts"
PIP_TEST = ROOT / "packages/openmates-python/tests/test_cleartext_boundary.py"

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
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("PASS client encrypted storage boundary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
