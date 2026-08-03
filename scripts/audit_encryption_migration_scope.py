#!/usr/bin/env python3
"""Reject historical encryption rewrites and legacy-reader removal.

Inspects checked-in source and fixture metadata, protects legacy schema fields,
rejects mutation of immutable encryption fields, and forbids write-on-read CLI
migration. This deterministic audit performs no network calls or writes.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "backend/tests/fixtures/encryption_compatibility/manifest.json"
INVOICE_FIELDS = {"aes_nonce", "encrypted_aes_key", "encrypted_s3_object_key", "encrypted_filename"}
MEDIA_FIELDS = {"aes_key", "aes_nonce", "files_metadata", "vault_wrapped_aes_key"}
SCHEMAS = {
    "backend/core/directus/schemas/upload_files.yml": ("aes_key:", "aes_nonce:", "files_metadata:", "vault_wrapped_aes_key:"),
    "backend/core/directus/schemas/invoices.yml": ("encrypted_aes_key:", "encrypted_s3_object_key:", "encrypted_filename:", "aes_nonce:"),
    "backend/core/directus/schemas/share_short_links.yml": ("encrypted_url:",),
}
MIGRATION_NAME = re.compile(r"(?:migrat|backfill|re.?encrypt|rewrite).*(?:cipher|encrypt)|(?:cipher|encrypt).*(?:migrat|backfill|rewrite)", re.I)


def readers_and_schemas() -> list[str]:
    errors: list[str] = []
    manifest: dict[str, Any] = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for entry in manifest.get("immutable_files", []):
        actual = hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest()
        if actual != entry.get("sha256"):
            errors.append(f"legacy fixture changed or disappeared: {entry['path']}")
    for guard in manifest.get("reader_guards", []):
        source = (ROOT / guard["path"]).read_text(encoding="utf-8")
        for fragment in guard["required"]:
            if fragment not in source:
                errors.append(f"legacy reader removed from {guard['path']}: {fragment!r}")
    for path, fields in SCHEMAS.items():
        source = (ROOT / path).read_text(encoding="utf-8")
        for field in fields:
            if field not in source:
                errors.append(f"legacy schema field removed from {path}: {field[:-1]}")
    return errors


def legacy_cli_writes() -> list[str]:
    path = "frontend/packages/openmates-cli/src/storage.ts"
    source = (ROOT / path).read_text(encoding="utf-8")
    start, end = "if (!onDisk.masterKeyStorage) {", "// Retrieve key from the appropriate tier"
    if start not in source or end not in source:
        return [f"cannot identify protected legacy-session reader block in {path}"]
    block = source.split(start, 1)[1].split(end, 1)[0]
    calls = ("saveSession(", "writeJsonFile(", "rmSync(", "storeMasterKey(", "deleteMasterKey(")
    return [f"legacy CLI load mutates durable state via {call[:-1]} in {path}" for call in calls if call in block]


def literal(node: ast.AST, assignments: dict[str, ast.AST] | None = None) -> str | None:
    if isinstance(node, ast.Name) and assignments and node.id in assignments:
        node = assignments[node.id]
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def dict_keys(node: ast.AST, assignments: dict[str, ast.AST], mutations: dict[str, set[str]]) -> set[str]:
    variable = node.id if isinstance(node, ast.Name) else None
    if variable and variable in assignments:
        node = assignments[variable]
    if not isinstance(node, ast.Dict):
        return mutations.get(variable, set()) if variable else set()
    keys = {value for key in node.keys if key is not None and (value := literal(key)) is not None}
    for key, value_node in zip(node.keys, node.values):
        if key is None:
            keys.update(dict_keys(value_node, assignments, mutations))
    if variable:
        keys.update(mutations.get(variable, set()))
    return keys


def protected_updates(path: str) -> list[str]:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)
    assignments = {node.targets[0].id: node.value for node in ast.walk(tree) if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)}
    mutations: dict[str, set[str]] = {}
    for mutation in ast.walk(tree):
        if isinstance(mutation, ast.Assign):
            for target in mutation.targets:
                if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
                    if key := literal(target.slice):
                        mutations.setdefault(target.value.id, set()).add(key)
        if isinstance(mutation, ast.Call) and isinstance(mutation.func, ast.Attribute) and mutation.func.attr == "update" and isinstance(mutation.func.value, ast.Name) and mutation.args:
            mutations.setdefault(mutation.func.value.id, set()).update(dict_keys(mutation.args[0], assignments, mutations))
    errors: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr not in {"update_item", "update_items", "update_many"}:
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
        collection_node = node.args[0] if node.args else keywords.get("collection")
        payload_node = node.args[2] if len(node.args) >= 3 else keywords.get("data") or keywords.get("payload")
        if collection_node is None or payload_node is None:
            continue
        collection = literal(collection_node, assignments)
        protected = INVOICE_FIELDS if collection == "invoices" else MEDIA_FIELDS if collection == "upload_files" else set()
        rewritten = sorted(dict_keys(payload_node, assignments, mutations) & protected)
        if rewritten:
            errors.append(f"historical {collection} encryption rewrite in {path}:{node.lineno}: {', '.join(rewritten)}")
    return errors


def migration_entry_points() -> list[str]:
    errors: list[str] = []
    for root in (ROOT / "scripts", ROOT / "backend"):
        for path in sorted(root.rglob("*.py")):
            relative = path.relative_to(ROOT)
            if "tests" in relative.parts or path.name == Path(__file__).name:
                continue
            if MIGRATION_NAME.search(path.stem):
                errors.append(f"historical encryption migration entry point present: {relative}")
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and MIGRATION_NAME.search(node.name):
                    errors.append(f"historical encryption migration function present: {relative}:{node.lineno} {node.name}")
    return errors


def main() -> int:
    errors: list[str] = []
    try:
        errors.extend(readers_and_schemas())
        errors.extend(legacy_cli_writes())
        for root in (ROOT / "scripts", ROOT / "backend"):
            for source_path in sorted(root.rglob("*.py")):
                relative = source_path.relative_to(ROOT)
                if "tests" not in relative.parts and source_path.name != Path(__file__).name:
                    errors.extend(protected_updates(str(relative)))
        errors.extend(migration_entry_points())
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, SyntaxError) as exc:
        errors.append(str(exc))
    if errors:
        print("Encryption migration scope audit failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Encryption migration scope audit passed (legacy readers/schemas immutable; no rewrite entry points).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
