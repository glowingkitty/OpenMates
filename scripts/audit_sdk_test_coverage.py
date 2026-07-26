#!/usr/bin/env python3
"""Audit public SDK test coverage mapping.

Purpose: fail when a public npm/pip SDK method has no direct test mention and no
namespace-level smoke coverage mapping.
Architecture: uses the generated coverage matrix from generate_sdk_reference.py
so test coverage expectations are deterministic and reviewable.
Security: keeps cleartext SDK boundary coverage visible for deploy gates.
Spec: docs/specs/sdk-cleartext-encryption-boundary/spec.yml.
"""

from __future__ import annotations

from generate_sdk_reference import TEST_COVERAGE_DOC, build_test_coverage_doc, _check


def main() -> int:
    coverage_doc, failures = build_test_coverage_doc()
    if failures:
        for failure in failures:
            print(f"FAIL SDK method lacks test coverage mapping: {failure}")
        return 1
    if _check(TEST_COVERAGE_DOC, coverage_doc):
        print("PASS sdk test coverage")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
