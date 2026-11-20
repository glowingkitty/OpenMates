"""Several screenshots per issue report: request limits, decoding, readers, deletion."""

import base64
import json

import pytest
from pydantic import ValidationError

from backend.core.api.app.routes.settings import IssueReportRequest
from backend.core.api.app.services.issue_report_screenshots import (
    MAX_SCREENSHOT_BYTES,
    combine_screenshot_inputs,
    decode_screenshots,
    decrypt_screenshot_keys,
    issue_has_screenshots,
)
from backend.core.api.app.tasks.auto_delete_tasks import _delete_issue_s3_files


def _b64(size: int = 10) -> str:
    return base64.b64encode(b"x" * size).decode()


class _Encryption:
    async def encrypt_issue_report_data(self, value):
        return f"enc:{value}"

    async def decrypt_issue_report_data(self, value):
        return value[4:]


class _S3:
    def __init__(self):
        self.deleted = []

    async def check_availability(self):
        from backend.shared.python_utils.storage_availability import STORAGE_AVAILABLE

        return STORAGE_AVAILABLE

    async def delete_file(self, bucket_key, file_key):
        self.deleted.append(file_key)


def _request(**extra):
    return IssueReportRequest(title="Broken page", **extra)


# contract-test: direct surface=rest_api assertions=issue-reporting.submission.confirmed-and-durable
def test_five_screenshots_are_accepted_and_six_rejected():
    assert len(_request(screenshots_png_base64=[_b64()] * 5).screenshots_png_base64) == 5
    with pytest.raises(ValidationError):
        _request(screenshots_png_base64=[_b64()] * 6)


# contract-test: direct surface=rest_api assertions=issue-reporting.submission.confirmed-and-durable
def test_legacy_counts_as_first_item_in_the_total():
    assert _request(screenshot_png_base64=_b64()).screenshot_png_base64
    _request(screenshot_png_base64=_b64(), screenshots_png_base64=[_b64()] * 4)
    with pytest.raises(ValidationError):
        _request(screenshot_png_base64=_b64(), screenshots_png_base64=[_b64()] * 5)
    assert combine_screenshot_inputs("a", ["b", "c"]) == ["a", "b", "c"]


# contract-test: direct surface=rest_api assertions=issue-reporting.submission.confirmed-and-durable
def test_oversize_and_invalid_items_are_counted_as_skipped():
    big = _b64(MAX_SCREENSHOT_BYTES + 1)
    images, skipped = decode_screenshots(
        [_b64(), "data:image/png;base64," + _b64(5), big, "%%%not-base64%%%"]
    )
    assert [len(i) for i in images] == [10, 5]
    assert skipped == 2


# contract-test: direct surface=rest_api assertions=issue-reporting.submission.confirmed-and-durable
@pytest.mark.asyncio
async def test_readers_return_all_keys_and_fall_back_to_legacy_field():
    enc = _Encryption()
    keys = ["issue-screenshots/a.png", "issue-screenshots/b.png"]
    new_row = {
        "encrypted_screenshot_s3_key": "enc:" + keys[0],
        "encrypted_screenshot_s3_keys": "enc:" + json.dumps(keys),
    }
    assert await decrypt_screenshot_keys(new_row, enc) == keys
    legacy_row = {"encrypted_screenshot_s3_key": "enc:" + keys[0]}
    assert await decrypt_screenshot_keys(legacy_row, enc) == [keys[0]]
    assert issue_has_screenshots(legacy_row) and not issue_has_screenshots({})
    assert await decrypt_screenshot_keys({}, enc) == []


# contract-test: direct surface=rest_api assertions=issue-reporting.submission.confirmed-and-durable
@pytest.mark.asyncio
async def test_retention_delete_removes_every_screenshot():
    keys = ["issue-screenshots/a.png", "issue-screenshots/b.png", "issue-screenshots/c.png"]
    issue = {
        "encrypted_screenshot_s3_key": "enc:" + keys[0],
        "encrypted_screenshot_s3_keys": "enc:" + json.dumps(keys),
    }
    s3 = _S3()
    deleted = await _delete_issue_s3_files(issue, _Encryption(), s3)
    assert s3.deleted == keys
    assert deleted == 3
