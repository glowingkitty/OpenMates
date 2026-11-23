"""Read an issue report's encrypted YAML (browser console logs, app state, timeline) back.

The report-issue Celery task encrypts the YAML with the server-side Vault
transit key ``issue_report_emails``, stores it under ``issue-reports/...`` in the
``issue_logs`` bucket and saves the Vault-encrypted object key on the Directus
``issues`` row (``encrypted_issue_report_yaml_s3_key``). This module is the one
reader of that contract. When the YAML cannot be read it names the exact step
(key decrypt, object missing, download, content decrypt, parse), so a broken
pipeline is never reported as a vague "retrieval failed" (TASK-1164).

Used by: backend/scripts/debug_issue.py (debug.py issue),
backend/core/api/app/routes/settings.py (issue status ``verify_yaml``).
Tests: backend/tests/test_issue_report_yaml.py,
frontend/apps/web_app/tests/report-issue-flow.spec.ts.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

import yaml
from fastapi import HTTPException

from backend.core.api.app.services.s3.config import get_bucket_name

ISSUE_REPORT_YAML_STEPS = (
    "key_decrypt",
    "object_missing",
    "download",
    "content_decrypt",
    "parse",
)


class _IssueReportDecryptor(Protocol):
    async def decrypt_issue_report_data(self, encrypted_data: str) -> str | None: ...


class _IssueReportObjectReader(Protocol):
    async def get_file(self, bucket_name: str, object_key: str) -> bytes | None: ...


class IssueReportYamlUnreadable(Exception):
    """The stored YAML report could not be read; ``step`` names where it failed."""

    def __init__(self, step: str, detail: str):
        if step not in ISSUE_REPORT_YAML_STEPS:
            raise ValueError(f"unknown issue report YAML step: {step}")
        self.step = step
        self.detail = detail
        super().__init__(f"{step}: {detail}")


async def read_issue_report_yaml(
    encryption_service: _IssueReportDecryptor,
    s3_service: _IssueReportObjectReader,
    encrypted_s3_key: str,
    *,
    environment: str | None = None,
) -> dict[str, Any]:
    """Return the parsed YAML report or raise ``IssueReportYamlUnreadable``."""
    s3_object_key = await encryption_service.decrypt_issue_report_data(encrypted_s3_key)
    if not s3_object_key:
        raise IssueReportYamlUnreadable("key_decrypt", "Vault returned no object key")

    bucket_name = get_bucket_name(
        "issue_logs", environment or os.getenv("SERVER_ENVIRONMENT", "development")
    )
    try:
        encrypted_bytes = await s3_service.get_file(bucket_name=bucket_name, object_key=s3_object_key)
    except HTTPException as exc:  # get_file maps every storage failure to a sanitized 503
        raise IssueReportYamlUnreadable(
            "download", f"{type(exc).__name__} for bucket={bucket_name} key={s3_object_key}"
        ) from exc
    if not encrypted_bytes:
        raise IssueReportYamlUnreadable(
            "object_missing", f"no object at bucket={bucket_name} key={s3_object_key}"
        )

    try:
        ciphertext = encrypted_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IssueReportYamlUnreadable("content_decrypt", "stored object is not Vault ciphertext text") from exc
    plaintext = await encryption_service.decrypt_issue_report_data(ciphertext)
    if not plaintext:
        raise IssueReportYamlUnreadable(
            "content_decrypt", f"Vault could not decrypt {len(encrypted_bytes)} stored bytes"
        )

    try:
        report = yaml.safe_load(plaintext)
    except yaml.YAMLError as exc:
        raise IssueReportYamlUnreadable("parse", f"{type(exc).__name__}: {exc}") from exc
    if not isinstance(report, dict):
        raise IssueReportYamlUnreadable("parse", f"report is {type(report).__name__}, not a mapping")
    return report


def issue_report_yaml_issue_id(report: dict[str, Any]) -> str | None:
    """Return the issue id recorded inside the report's metadata, if any."""
    inner = report.get("issue_report", report)
    metadata = inner.get("metadata") if isinstance(inner, dict) else None
    issue_id = metadata.get("issue_id") if isinstance(metadata, dict) else None
    return str(issue_id) if issue_id else None


async def issue_report_yaml_unreadable_step(
    encryption_service: _IssueReportDecryptor,
    s3_service: _IssueReportObjectReader,
    issue: dict[str, Any],
) -> str | None:
    """Read the issue's YAML back; return ``None`` if it is readable, else the failing step.

    A report whose metadata names a different issue id counts as ``parse``.
    Only step names leave this function, never bucket names, object keys or content.
    """
    encrypted_key = issue.get("encrypted_issue_report_yaml_s3_key")
    if not encrypted_key:
        return "object_missing"
    try:
        report = await read_issue_report_yaml(encryption_service, s3_service, encrypted_key)
    except IssueReportYamlUnreadable as exc:
        return exc.step
    if issue_report_yaml_issue_id(report) != str(issue.get("id")):
        return "parse"
    return None
