"""Issue report YAML read-back names the failing step (TASK-1164).

Covers backend/core/api/app/services/issue_report_yaml.py and the debug.py
label: ``--no-logs`` must read as "not loaded", never as a retrieval failure.
The real-stack proof is frontend/apps/web_app/tests/report-issue-flow.spec.ts,
which requires ``yaml_report_readable`` from the issue status endpoint.
"""

from __future__ import annotations

import asyncio

import pytest
import yaml
from fastapi import HTTPException

from backend.core.api.app.services.issue_report_yaml import (
    IssueReportYamlUnreadable,
    issue_report_yaml_unreadable_step,
    read_issue_report_yaml,
)

ISSUE_ID = "00000000-0000-4000-8000-000000000001"
OBJECT_KEY = "issue-reports/20260101_000000_abcdef12.yaml.encrypted"


class FakeTransit:
    """Reversible stand-in for the Vault transit key: 'vault:v1:' + plaintext."""

    async def decrypt_issue_report_data(self, encrypted_data: str) -> str | None:
        if not encrypted_data.startswith("vault:v1:"):
            return None
        return encrypted_data.removeprefix("vault:v1:")


class FakeStorage:
    def __init__(self, objects: dict[str, bytes] | None = None, error: Exception | None = None):
        self.objects = objects or {}
        self.error = error
        self.calls: list[tuple[str, str]] = []

    async def get_file(self, bucket_name: str, object_key: str) -> bytes | None:
        self.calls.append((bucket_name, object_key))
        if self.error:
            raise self.error
        return self.objects.get(object_key)


def _report(issue_id: str = ISSUE_ID) -> str:
    return yaml.safe_dump({"issue_report": {"metadata": {"issue_id": issue_id}, "console_logs": "ok"}})


def _issue() -> dict:
    return {"id": ISSUE_ID, "encrypted_issue_report_yaml_s3_key": f"vault:v1:{OBJECT_KEY}"}


def _storage_with(plaintext_yaml: str) -> FakeStorage:
    return FakeStorage({OBJECT_KEY: f"vault:v1:{plaintext_yaml}".encode()})


# contract-test: supporting surface=rest_api assertions=issue-reporting.logs.debug-report-readable
def test_reads_report_from_dev_issue_logs_bucket():
    storage = _storage_with(_report())
    report = asyncio.run(
        read_issue_report_yaml(FakeTransit(), storage, f"vault:v1:{OBJECT_KEY}", environment="development")
    )
    assert report["issue_report"]["metadata"]["issue_id"] == ISSUE_ID
    assert storage.calls == [("dev-openmates-issue-logs", OBJECT_KEY)]


@pytest.mark.parametrize(
    ("encrypted_key", "storage", "step"),
    [
        ("not-vault", _storage_with(_report()), "key_decrypt"),
        (f"vault:v1:{OBJECT_KEY}", FakeStorage(), "object_missing"),
        (f"vault:v1:{OBJECT_KEY}", FakeStorage(error=HTTPException(status_code=503)), "download"),
        (f"vault:v1:{OBJECT_KEY}", FakeStorage({OBJECT_KEY: b"plain-not-ciphertext"}), "content_decrypt"),
        (f"vault:v1:{OBJECT_KEY}", _storage_with("key: [unclosed"), "parse"),
        (f"vault:v1:{OBJECT_KEY}", _storage_with("- just\n- a list\n"), "parse"),
    ],
)
# contract-test: supporting surface=rest_api assertions=issue-reporting.logs.debug-report-readable
def test_each_failure_names_its_step(encrypted_key, storage, step):
    with pytest.raises(IssueReportYamlUnreadable) as caught:
        asyncio.run(read_issue_report_yaml(FakeTransit(), storage, encrypted_key, environment="development"))
    assert caught.value.step == step


# contract-test: supporting surface=rest_api assertions=issue-reporting.logs.debug-report-readable
def test_status_check_is_readable_only_for_the_matching_issue():
    assert asyncio.run(issue_report_yaml_unreadable_step(FakeTransit(), _storage_with(_report()), _issue())) is None
    other = _storage_with(_report("00000000-0000-4000-8000-000000000002"))
    assert asyncio.run(issue_report_yaml_unreadable_step(FakeTransit(), other, _issue())) == "parse"
    assert asyncio.run(issue_report_yaml_unreadable_step(FakeTransit(), FakeStorage(), _issue())) == "object_missing"


# contract-test: supporting surface=rest_api assertions=issue-reporting.logs.debug-report-readable
def test_debug_output_never_calls_skipped_logs_a_failure():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    debug_issue = pytest.importorskip("debug_issue")
    issue = {"id": ISSUE_ID, "title": "t", "encrypted_issue_report_yaml_s3_key": "vault:v1:x"}

    skipped = debug_issue.format_detail_output(
        ISSUE_ID, issue, {}, None, s3_report_note=debug_issue.S3_REPORT_SKIPPED_NOTE
    )
    assert "YAML report not loaded (--no-logs)" in skipped
    assert "could not be read" not in skipped

    failed = debug_issue.format_detail_output(
        ISSUE_ID, issue, {}, None, s3_report_note="object_missing: no object at bucket=b key=k"
    )
    assert "YAML report exists but could not be read: object_missing" in failed
