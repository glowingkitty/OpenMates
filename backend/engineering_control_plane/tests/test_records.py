"""Unit checks for the allowlisted record repository boundary.

These tests validate table, field, filter, and sort rejection without requiring
a database. PostgreSQL integration tests cover transactions and constraints.
"""

# contract-test-file: infrastructure

import pytest

from backend.engineering_control_plane.records import (
    PostgresRecordRepository,
    UnknownRecordType,
    sanitize_record,
    schema_for,
)


def test_record_boundary_rejects_unknown_tables_and_fields() -> None:
    with pytest.raises(UnknownRecordType, match="product_users"):
        sanitize_record("product_users", {"id": "one"})
    with pytest.raises(ValueError, match="unsupported test_catalog fields"):
        sanitize_record("test_catalog", {"test_key": "pytest::one", "email": "private@example.com"})


def test_record_boundary_requires_natural_key() -> None:
    with pytest.raises(ValueError, match="test_results.result_key is required"):
        sanitize_record("test_results", {"status": "passed"})


def test_filters_and_sorts_are_allowlisted() -> None:
    repository = PostgresRecordRepository("postgresql://unused")
    schema = schema_for("test_results")

    where_sql, values = repository._where_clause(
        schema,
        {"test_key": {"in": ["pytest::one"]}, "created_at_unix": {"gte": 1}},
    )
    assert where_sql == " WHERE test_key = ANY(%s) AND created_at_unix >= %s"
    assert values == [["pytest::one"], 1]
    assert repository._order_clause(schema, "-created_at_unix") == " ORDER BY created_at_unix DESC"
    with pytest.raises(ValueError, match="unsupported sort field"):
        repository._order_clause(schema, "email")
