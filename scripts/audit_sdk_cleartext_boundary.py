#!/usr/bin/env python3
"""Audit public SDK cleartext encryption boundaries.

Purpose: fail when public npm or pip SDK methods expose encrypted storage
payload construction to callers.
Architecture: source-level guard scoped to SDK facade classes, not internal CLI
or backend transport code.
Security: encrypted storage names may exist internally, but public signatures and
barrel exports must stay cleartext-only.
Spec: docs/specs/sdk-cleartext-encryption-boundary/spec.yml.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
SDK_TS = ROOT / "frontend/packages/openmates-cli/src/sdk.ts"
INDEX_TS = ROOT / "frontend/packages/openmates-cli/src/index.ts"
SDK_PY = ROOT / "packages/openmates-python/openmates/sdk.py"

FORBIDDEN_PUBLIC_TOKENS = (
    "listDecrypted",
    "list_decrypted",
    "persistEncryptedImport",
    "persist_encrypted_import",
    "encryptedRecordCounts",
    "encrypted_record_counts",
    "encryptedCreate",
    "encryptedCreates",
    "encryptedUpdate",
    "encryptedUpdates",
    "encrypted_create",
    "encrypted_creates",
    "encrypted_update",
    "encrypted_updates",
    "key_wrappers",
)

PUBLIC_NPM_CLASSES = ()
PUBLIC_PIP_CLASSES = ()


def class_body(source: str, class_name: str, *, language: str) -> str:
    if language == "ts":
        start = source.index(f"export class {class_name}")
        next_class = source.find("\nexport class ", start + 1)
        return source[start:] if next_class == -1 else source[start:next_class]
    start = source.index(f"class {class_name}:")
    next_class = source.find("\nclass ", start + 1)
    return source[start:] if next_class == -1 else source[start:next_class]


def public_method_signatures(body: str, *, language: str) -> list[str]:
    signatures: list[str] = []
    if language == "ts":
        pattern = re.compile(r"\n\s{2}(?!private\b)(?:async\s+)?[A-Za-z_][A-Za-z0-9_]*\s*\([^)]*\)", re.MULTILINE | re.DOTALL)
    else:
        pattern = re.compile(r"\n\s{4}def\s+(?!_)[A-Za-z_][A-Za-z0-9_]*\s*\([^)]*\)", re.MULTILINE | re.DOTALL)
    for match in pattern.finditer(body):
        signatures.append(" ".join(match.group(0).split()))
    return signatures


def public_classes(source: str, *, language: str) -> list[str]:
    if language == "ts":
        return [
            match.group(1)
            for match in re.finditer(r"\nexport class (OpenMates[A-Za-z0-9_]*)\b", source)
            if match.group(1) not in {"OpenMatesApiError", "OpenMatesConfigError"}
        ]
    return [
        match.group(1)
        for match in re.finditer(r"\nclass (OpenMates[A-Za-z0-9_]*):", source)
        if match.group(1) not in {"OpenMatesApiError", "OpenMatesConfigError"}
    ]


def main() -> int:
    failures: list[str] = []
    sdk_ts = SDK_TS.read_text(encoding="utf-8")
    index_ts = INDEX_TS.read_text(encoding="utf-8")
    sdk_py = SDK_PY.read_text(encoding="utf-8")

    for class_name in public_classes(sdk_ts, language="ts"):
        for signature in public_method_signatures(class_body(sdk_ts, class_name, language="ts"), language="ts"):
            for token in FORBIDDEN_PUBLIC_TOKENS:
                if token in signature:
                    failures.append(f"npm {class_name} public signature exposes {token}: {signature}")

    for class_name in public_classes(sdk_py, language="py"):
        for signature in public_method_signatures(class_body(sdk_py, class_name, language="py"), language="py"):
            for token in FORBIDDEN_PUBLIC_TOKENS:
                if token in signature:
                    failures.append(f"pip {class_name} public signature exposes {token}: {signature}")

    exported_lines = [line.strip() for line in index_ts.splitlines() if line.strip() and not line.strip().startswith("//")]
    for line in exported_lines:
        for token in FORBIDDEN_PUBLIC_TOKENS:
            if token in line:
                failures.append(f"npm public barrel export exposes {token}: {line}")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("PASS sdk cleartext boundary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
