# contract-test-file: tooling
"""RawDownload keeps legacy mapping access and follows the shared filename contract."""

import dataclasses

import pytest

from openmates import RawDownload
from openmates.raw_download import filename_from_disposition


def test_raw_download_is_typed_and_keeps_read_only_mapping_access():
    download = RawDownload(content_type="application/pdf", filename="a.pdf", data=b"%PDF")
    assert download["data"] == b"%PDF" and download.get("filename") == "a.pdf"
    assert download.get("missing", 1) == 1 and "content_type" in download
    assert dict(download) == {"content_type": "application/pdf", "filename": "a.pdf", "data": b"%PDF"}
    with pytest.raises(dataclasses.FrozenInstanceError):
        download.data = b""  # type: ignore[misc]  # proving immutability on purpose


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ('attachment; filename="../../etc/invoice.pdf"', "invoice.pdf"),
        ("attachment; filename=\"x.pdf\"; filename*=UTF-8''Gutschrift%20%E2%82%AC.pdf", "Gutschrift €.pdf"),
        ('attachment; filename="C:\\\\Users\\\\a\\\\inv.pdf"', "inv.pdf"),
        ('attachment; filename=".."', None),
        ("attachment; filename=\"fallback.pdf\"; filename*=UTF-8''bad%ZZ.pdf", None),
    ],
)
def test_filename_matches_the_shared_contract(header, expected):
    assert filename_from_disposition(header) == expected
