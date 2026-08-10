#!/usr/bin/env python3
"""Deterministically backfill nullable root usage attribution.

The script reads metadata-only usage, orchestration, and chat ancestry fields.
Dry-run is the default; writes require both --apply and --confirm. Ambiguous,
malformed, cross-owner, and unprovable rows remain untouched and are counted.
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class Attribution:
    root_chat_id: str
    actual_chat_id: str
    root_turn_id: str | None
    orchestration_id: str | None
    depth: int
    source: str
    owner_hash: str | None = None


def resolve_chat_chain(row: dict[str, Any], chats: dict[str, dict[str, Any]]) -> Attribution | None:
    actual_chat_id = row.get("actual_chat_id") or row.get("chat_id")
    if not actual_chat_id or actual_chat_id not in chats:
        return None
    owner = row.get("user_id_hash")
    if not owner:
        return None
    current_id = actual_chat_id
    visited: set[str] = set()
    depth = 0
    while True:
        if current_id in visited or depth > 2:
            return None
        visited.add(current_id)
        chat = chats.get(current_id)
        if not chat or not chat.get("hashed_user_id") or chat.get("hashed_user_id") != owner:
            return None
        parent_id = chat.get("parent_id")
        if not parent_id:
            if depth > 0 and not chat.get("is_sub_chat"):
                return Attribution(current_id, actual_chat_id, None, None, depth, "chat_chain")
            if depth == 0 and not chat.get("is_sub_chat"):
                return Attribution(current_id, actual_chat_id, None, None, 0, "chat_chain")
            return None
        if not chat.get("is_sub_chat"):
            return None
        current_id = str(parent_id)
        depth += 1


def resolve_usage_row(
    row: dict[str, Any],
    *,
    operations: dict[str, Attribution],
    children: dict[str, Attribution],
    chats: dict[str, dict[str, Any]],
    mappings: dict[str, Attribution],
) -> tuple[Attribution | None, str]:
    if row.get("root_chat_id"):
        return None, "already_attributed"
    owner = row.get("user_id_hash")

    def has_valid_root(attribution: Attribution) -> bool:
        root = chats.get(attribution.root_chat_id)
        return bool(
            owner
            and root
            and root.get("hashed_user_id") == owner
            and not root.get("parent_id")
            and not root.get("is_sub_chat")
        )

    candidates: list[Attribution] = []
    operation = operations.get(str(row.get("operation_id") or ""))
    if (
        operation
        and operation.owner_hash == row.get("user_id_hash")
        and operation.actual_chat_id == (row.get("actual_chat_id") or row.get("chat_id"))
        and has_valid_root(operation)
    ):
        candidates.append(operation)
    actual_chat_id = str(row.get("actual_chat_id") or row.get("chat_id") or "")
    child = children.get(actual_chat_id)
    if child and child.owner_hash == row.get("user_id_hash") and has_valid_root(child):
        candidates.append(child)
    chain = resolve_chat_chain(row, chats)
    if chain:
        candidates.append(chain)
    mapping = mappings.get(str(row.get("id") or ""))
    if (
        mapping
        and mapping.owner_hash == row.get("user_id_hash")
        and mapping.actual_chat_id == (row.get("actual_chat_id") or row.get("chat_id"))
        and has_valid_root(mapping)
    ):
        candidates.append(mapping)
    if not candidates:
        return None, "unmatched"
    identities = {
        (
            candidate.root_chat_id,
            candidate.actual_chat_id,
            candidate.depth,
            candidate.root_turn_id,
            candidate.orchestration_id,
        )
        for candidate in candidates
    }
    if len(identities) != 1:
        return None, "conflict"
    selected = candidates[0]
    expected_fields = {
        "root_chat_id": selected.root_chat_id,
        "actual_chat_id": selected.actual_chat_id,
        "root_turn_id": selected.root_turn_id,
        "orchestration_id": selected.orchestration_id,
        "depth": selected.depth,
    }
    if any(
        row.get(field) is not None
        and (value is None or str(row.get(field)) != str(value))
        for field, value in expected_fields.items()
    ):
        return None, "conflict"
    return selected, selected.source


def load_mappings(path: str | None) -> dict[str, Attribution]:
    if not path:
        return {}
    payload = json.loads(open(path, encoding="utf-8").read())
    if payload.get("version") != 1 or not isinstance(payload.get("mappings"), list):
        raise ValueError("Mapping file must contain version 1 and a mappings array")
    result: dict[str, Attribution] = {}
    for item in payload["mappings"]:
        usage_id = str(item.get("usage_id") or "")
        depth = item.get("depth")
        identifier_fields = [usage_id, str(item.get("root_chat_id") or ""), str(item.get("actual_chat_id") or "")]
        try:
            for identifier in identifier_fields:
                uuid.UUID(identifier)
            if item.get("root_turn_id"):
                uuid.UUID(str(item["root_turn_id"]))
            if item.get("orchestration_id"):
                uuid.UUID(str(item["orchestration_id"]))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Mapping identifiers must be valid UUIDs") from exc
        if not item.get("user_id_hash") or usage_id in result or depth not in {0, 1, 2}:
            raise ValueError("Mappings require unique usage_id values and depth 0, 1, or 2")
        result[usage_id] = Attribution(
            root_chat_id=str(item["root_chat_id"]),
            actual_chat_id=str(item["actual_chat_id"]),
            root_turn_id=item.get("root_turn_id"),
            orchestration_id=item.get("orchestration_id"),
            depth=depth,
            source="operator_mapping",
            owner_hash=str(item.get("user_id_hash") or ""),
        )
    return result


def connect_database():
    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(
        host=os.getenv("DB_HOST", "cms-database"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_DATABASE") or os.environ["DATABASE_NAME"],
        user=os.getenv("DB_USER") or os.environ["DATABASE_USERNAME"],
        password=os.getenv("DB_PASSWORD") or os.environ["DATABASE_PASSWORD"],
        row_factory=dict_row,
    )


def fetch_rows(cursor, query: str) -> list[dict[str, Any]]:
    cursor.execute(query)
    return [dict(row) for row in cursor.fetchall()]


def run(*, apply: bool, confirm: bool, mapping_path: str | None, limit: int | None) -> dict[str, Any]:
    if apply and not confirm:
        raise ValueError("--apply requires --confirm")
    if limit is not None and limit <= 0:
        raise ValueError("--limit must be positive")
    mappings = load_mappings(mapping_path)
    with connect_database() as connection, connection.cursor() as cursor:
        usage_limit = f" LIMIT {int(limit)}" if limit else ""
        usage_rows = fetch_rows(cursor, """
            SELECT id, user_id_hash, chat_id, actual_chat_id, root_chat_id, root_turn_id,
                   orchestration_id, depth, operation_id
            FROM usage WHERE root_chat_id IS NULL ORDER BY created_at, id
        """ + usage_limit)
        chat_rows = fetch_rows(cursor, "SELECT id, parent_id, is_sub_chat, hashed_user_id FROM chats")
        operation_rows = fetch_rows(cursor, """
            SELECT o.operation_id, o.root_chat_id, o.actual_chat_id, o.depth,
                    o.orchestration_id, r.root_turn_id, r.hashed_user_id
            FROM sub_chat_orchestration_operations o
            JOIN sub_chat_orchestrations r ON r.id = o.orchestration_id
                AND r.root_chat_id = o.root_chat_id
        """)
        child_rows = fetch_rows(cursor, """
            SELECT c.child_chat_id, c.depth, c.orchestration_id,
                   r.root_chat_id, r.root_turn_id, r.hashed_user_id
            FROM sub_chat_orchestration_children c
            JOIN sub_chat_orchestrations r ON r.id = c.orchestration_id
        """)

        chats = {str(row["id"]): row for row in chat_rows}
        operations = {
            str(row["operation_id"]): Attribution(
                str(row["root_chat_id"]), str(row["actual_chat_id"]), row.get("root_turn_id"),
                str(row["orchestration_id"]), int(row["depth"]), "operation", str(row["hashed_user_id"]),
            )
            for row in operation_rows
        }
        children = {
            str(row["child_chat_id"]): Attribution(
                str(row["root_chat_id"]), str(row["child_chat_id"]), row.get("root_turn_id"),
                str(row["orchestration_id"]), int(row["depth"]), "orchestration_child", str(row["hashed_user_id"]),
            )
            for row in child_rows
        }
        counts: Counter[str] = Counter()
        planned: list[tuple[str, Attribution]] = []
        for row in usage_rows:
            attribution, reason = resolve_usage_row(
                row,
                operations=operations,
                children=children,
                chats=chats,
                mappings=mappings,
            )
            counts[reason] += 1
            if attribution:
                planned.append((str(row["id"]), attribution))

        updated = 0
        if apply:
            for usage_id, attribution in planned:
                cursor.execute("""
                    UPDATE usage
                    SET root_chat_id = %s, actual_chat_id = COALESCE(actual_chat_id, %s),
                        root_turn_id = COALESCE(root_turn_id, %s),
                        orchestration_id = COALESCE(orchestration_id, %s),
                        depth = COALESCE(depth, %s)
                    WHERE id = %s AND root_chat_id IS NULL
                """, (
                    attribution.root_chat_id, attribution.actual_chat_id, attribution.root_turn_id,
                    attribution.orchestration_id, attribution.depth, usage_id,
                ))
                updated += cursor.rowcount
            connection.commit()

    return {
        "dry_run": not apply,
        "usage_rows_scanned": len(usage_rows),
        "planned_updates": len(planned),
        "updated": updated,
        "resolved_by": dict(sorted(counts.items())),
        "unmatched_rows_preserved": counts["unmatched"] + counts["conflict"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill deterministic root usage attribution")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--mapping")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    print(json.dumps(run(apply=args.apply, confirm=args.confirm, mapping_path=args.mapping, limit=args.limit), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
