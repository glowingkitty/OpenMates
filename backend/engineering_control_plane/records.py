"""Allowlisted PostgreSQL record repository for engineering test state.

The repository intentionally exposes no arbitrary table or column access.
All writes use stable natural keys and execute inside caller-owned transactions
when imported in bulk, preserving idempotency and current-state consistency.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from backend.engineering_control_plane.database import connect


@dataclass(frozen=True, slots=True)
class RecordSchema:
    key: str
    fields: frozenset[str]
    json_fields: frozenset[str] = frozenset()
    default_sort: str | None = None


SCHEMAS: dict[str, RecordSchema] = {
    "test_catalog": RecordSchema("test_key", frozenset({"test_key", "suite", "test_name", "file_path", "verification_command", "metadata"}), frozenset({"metadata"}), "test_key"),
    "test_runs": RecordSchema("run_key", frozenset({"run_key", "source", "external_run_id", "workflow", "status", "git_sha", "git_branch", "environment", "requested_tests", "campaign_key", "debug_group_key", "summary", "record_json", "updated_at", "updated_at_unix"}), frozenset({"requested_tests", "summary", "record_json"}), "-updated_at_unix"),
    "test_results": RecordSchema("result_key", frozenset({"result_key", "run_key", "test_key", "suite", "test_name", "status", "error_summary", "metadata", "created_at", "created_at_unix"}), frozenset({"metadata"}), "created_at_unix"),
    "test_current_state": RecordSchema("test_key", frozenset({"test_key", "suite", "test_name", "stable_status", "stable_result_key", "stable_run_key", "active_status", "active_run_key", "triage_group_id", "error_summary", "metadata", "updated_at", "updated_at_unix"}), frozenset({"metadata"}), "test_key"),
    "test_claims": RecordSchema("claim_key", frozenset({"claim_key", "lease_id", "group_id", "campaign_key", "debug_group_key", "status", "session_id", "worker_id", "leased_at", "expires_at", "expires_at_unix", "updated_at", "completed_at", "completed_commit", "commit", "released_at", "release_reason", "entry_json"}), frozenset({"entry_json"}), "leased_at"),
    "test_debug_campaigns": RecordSchema("campaign_key", frozenset({"campaign_key", "title", "status", "session_id", "source_run_keys", "selected_test_keys", "selected_group_keys", "current_group_key", "completion_policy", "blocker", "metadata", "created_at", "updated_at", "completed_at"}), frozenset({"source_run_keys", "selected_test_keys", "selected_group_keys", "completion_policy", "blocker", "metadata"}), "created_at"),
    "test_debug_groups": RecordSchema("group_key", frozenset({"group_key", "campaign_key", "triage_group_id", "parent_group_key", "status", "member_test_keys", "observed_failure", "expected_behavior", "acceptance_criteria", "root_cause", "attempts", "red_evidence", "green_evidence", "blocker", "metadata", "verification_command", "fixing_commit", "selected_at", "selected_at_unix", "updated_at"}), frozenset({"member_test_keys", "acceptance_criteria", "root_cause", "attempts", "red_evidence", "green_evidence", "blocker", "metadata"}), "selected_at_unix"),
}


class UnknownRecordType(ValueError):
    """Raised when a request attempts access outside the fixed schema map."""


def schema_for(collection: str) -> RecordSchema:
    try:
        return SCHEMAS[collection]
    except KeyError as exc:
        raise UnknownRecordType(f"unsupported record type: {collection}") from exc


def sanitize_record(collection: str, record: Mapping[str, Any]) -> dict[str, Any]:
    schema = schema_for(collection)
    unknown = set(record) - schema.fields
    if unknown:
        raise ValueError(f"unsupported {collection} fields: {', '.join(sorted(unknown))}")
    clean = {key: value for key, value in record.items() if key in schema.fields}
    if not str(clean.get(schema.key) or "").strip():
        raise ValueError(f"{collection}.{schema.key} is required")
    return clean


class PostgresRecordRepository:
    """Natural-key CRUD and atomic import against dedicated PostgreSQL."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def list_records(
        self,
        collection: str,
        *,
        filters: Mapping[str, Any] | None = None,
        sort: str | None = None,
        limit: int = -1,
    ) -> list[dict[str, Any]]:
        schema = schema_for(collection)
        where_sql, parameters = self._where_clause(schema, filters or {})
        sort_value = sort or schema.default_sort
        order_sql = self._order_clause(schema, sort_value)
        limit_sql = "" if limit < 0 else " LIMIT %s"
        if limit >= 0:
            parameters.append(limit)
        with connect(self.database_url) as connection:
            from psycopg.rows import dict_row

            connection.row_factory = dict_row
            rows = connection.execute(
                f"SELECT * FROM {collection}{where_sql}{order_sql}{limit_sql}",
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_record(self, collection: str, record: Mapping[str, Any]) -> dict[str, Any]:
        with connect(self.database_url) as connection:
            return self._upsert(connection, collection, record)

    def import_records(
        self,
        collections: Mapping[str, Sequence[Mapping[str, Any]]],
        *,
        replace_current_state: bool = False,
    ) -> dict[str, int]:
        unknown = set(collections) - set(SCHEMAS)
        if unknown:
            raise UnknownRecordType(f"unsupported record types: {', '.join(sorted(unknown))}")
        counts: dict[str, int] = {}
        with connect(self.database_url) as connection:
            if replace_current_state:
                state_records = collections.get("test_current_state", ())
                state_keys = [sanitize_record("test_current_state", record)["test_key"] for record in state_records]
                if state_keys:
                    connection.execute("DELETE FROM test_current_state WHERE NOT (test_key = ANY(%s))", (state_keys,))
                else:
                    connection.execute("DELETE FROM test_current_state")
            for collection, records in collections.items():
                self._bulk_upsert(connection, collection, records)
                counts[collection] = len(records)
        return counts

    def _bulk_upsert(self, connection: Any, collection: str, records: Sequence[Mapping[str, Any]]) -> None:
        if not records:
            return
        schema = schema_for(collection)
        grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            clean = sanitize_record(collection, record)
            grouped[tuple(clean)].append(clean)
        from psycopg.types.json import Jsonb

        with connection.cursor() as cursor:
            for columns, clean_records in grouped.items():
                assignments = [column for column in columns if column != schema.key]
                updates = ", ".join(f"{column} = EXCLUDED.{column}" for column in assignments)
                conflict_sql = f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
                query = (
                    f"INSERT INTO {collection} ({', '.join(columns)}) VALUES ({', '.join('%s' for _ in columns)}) "
                    f"ON CONFLICT ({schema.key}) {conflict_sql}"
                )
                parameters = [
                    [Jsonb(record[column]) if column in schema.json_fields else record[column] for column in columns]
                    for record in clean_records
                ]
                cursor.executemany(query, parameters)

    def _upsert(self, connection: Any, collection: str, record: Mapping[str, Any]) -> dict[str, Any]:
        schema = schema_for(collection)
        clean = sanitize_record(collection, record)
        columns = list(clean)
        assignments = [column for column in columns if column != schema.key]
        placeholders = ["%s" for _ in columns]
        updates = ", ".join(f"{column} = EXCLUDED.{column}" for column in assignments)
        conflict_sql = f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
        from psycopg.types.json import Jsonb

        values = [Jsonb(clean[column]) if column in schema.json_fields else clean[column] for column in columns]
        from psycopg.rows import dict_row

        previous_factory = connection.row_factory
        connection.row_factory = dict_row
        try:
            row = connection.execute(
                f"INSERT INTO {collection} ({', '.join(columns)}) VALUES ({', '.join(placeholders)}) "
                f"ON CONFLICT ({schema.key}) {conflict_sql} RETURNING *",
                values,
            ).fetchone()
        finally:
            connection.row_factory = previous_factory
        return dict(row)

    def _where_clause(self, schema: RecordSchema, filters: Mapping[str, Any]) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        for field, condition in filters.items():
            if field not in schema.fields:
                raise ValueError(f"unsupported filter field: {field}")
            if not isinstance(condition, Mapping) or len(condition) != 1:
                raise ValueError(f"invalid filter for {field}")
            operator, value = next(iter(condition.items()))
            if operator == "eq":
                clauses.append(f"{field} = %s")
                parameters.append(value)
            elif operator == "in" and isinstance(value, list):
                clauses.append(f"{field} = ANY(%s)")
                parameters.append(value)
            elif operator == "gte":
                clauses.append(f"{field} >= %s")
                parameters.append(value)
            else:
                raise ValueError(f"unsupported filter operator: {operator}")
        return (f" WHERE {' AND '.join(clauses)}" if clauses else ""), parameters

    def _order_clause(self, schema: RecordSchema, sort: str | None) -> str:
        if not sort:
            return ""
        descending = sort.startswith("-")
        field = sort[1:] if descending else sort
        if field not in schema.fields:
            raise ValueError(f"unsupported sort field: {field}")
        return f" ORDER BY {field} {'DESC' if descending else 'ASC'}"
