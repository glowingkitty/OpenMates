# Guardrails for the structured admin log-query composer.
# These tests cover stream/field whitelisting only; they do not contact
# OpenObserve or require admin credentials. The goal is to keep issue-report
# diagnostics searchable without reopening raw SQL access or broad streams.

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

pytest.importorskip("redis.asyncio")

from backend.core.api.app.routes.admin_debug import LogQueryRequest, _compose_log_query_sql


def test_log_query_allows_client_issue_report_stream_defaults() -> None:
    req = LogQueryRequest(
        stream="client_issue_report",
        filters=[{"field": "issue_id", "op": "eq", "value": "issue-123"}],
        limit=25,
    )

    sql = _compose_log_query_sql(req)

    assert 'FROM "client_issue_report"' in sql
    assert '"issue_id" = \'issue-123\'' in sql
    assert 'SELECT "_timestamp", "message", "issue_id", "source"' in sql


def test_log_query_allows_counting_issue_reports_by_source() -> None:
    req = LogQueryRequest(
        stream="client_issue_report",
        mode="count_by",
        group_by=["source"],
        filters=[{"field": "message", "op": "like", "value": "%native_sync_perf%"}],
    )

    sql = _compose_log_query_sql(req)

    assert 'FROM "client_issue_report"' in sql
    assert 'GROUP BY "source"' in sql
    assert '"message" LIKE \'%native_sync_perf%\'' in sql


def test_log_query_rejects_non_issue_report_fields_on_issue_stream() -> None:
    req = LogQueryRequest(
        stream="client_issue_report",
        filters=[{"field": "user_email", "op": "like", "value": "%example.org%"}],
    )

    with pytest.raises(HTTPException) as exc_info:
        _compose_log_query_sql(req)

    assert exc_info.value.status_code == 400
    assert "not queryable" in str(exc_info.value.detail)


def test_log_query_rejects_unapproved_stream_names() -> None:
    with pytest.raises(ValidationError):
        LogQueryRequest(stream="audit_logs", filters=[])
