#!/usr/bin/env python3
"""Audit generated SDK documentation coverage.

Purpose: fail when the developer SDK reference omits a public npm/pip method.
Architecture: delegates rendering and exact-file comparison to the generated SDK
reference script, which shares the parity parser source of truth.
Security: guarantees public docs describe cleartext SDK calls, not raw encrypted
payload builders or internal crypto transport details.
Spec: docs/specs/sdk-cleartext-encryption-boundary/spec.yml.
"""

from __future__ import annotations

from generate_sdk_reference import REFERENCE_DOC, build_reference_doc, _check


def main() -> int:
    if _check(REFERENCE_DOC, build_reference_doc()):
        print("PASS sdk docs coverage")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
