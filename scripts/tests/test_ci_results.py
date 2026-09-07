# contract-test-file: tooling
"""Verify bounded CI evidence retrieval without remote services.

Malicious or accidental archive paths must not escape the evidence directory.
Downloads must terminate even when a child stalls or floods its stderr pipe.
These tests use disposable files and processes, never shared runtime state.
See docs/plans/isolated-github-tests/plan.yml.
"""

import io
import stat
import sys
import zipfile

import pytest
from scripts import ci_results


@pytest.mark.parametrize(
    "name",
    ["../escape", "/absolute", "ci-private/account.env", ".auth/session.json", ".env"],
)
def test_private_or_escaping_archive_rejected(tmp_path, name):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(name, "private")
    with pytest.raises(RuntimeError):
        ci_results.extract(archive, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_symlink_archive_rejected(tmp_path):
    archive = tmp_path / "bad.zip"
    entry = zipfile.ZipInfo("link")
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(entry, "/tmp/outside")
    with pytest.raises(RuntimeError, match="Unsafe"):
        ci_results.extract(archive, tmp_path / "out")


def test_download_drains_stderr_and_bounds_stdout(tmp_path, monkeypatch):
    output = io.BytesIO()
    ci_results.download(
        [
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('x'*200000); sys.stdout.write('ok')",
        ],
        tmp_path,
        output,
    )
    assert output.getvalue() == b"ok"
    monkeypatch.setattr(ci_results, "MAX_ARCHIVE", 10)
    with pytest.raises(RuntimeError, match="exceeded"):
        ci_results.download(
            [sys.executable, "-c", "print('x'*100)"], tmp_path, io.BytesIO()
        )


def test_download_stall_has_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(ci_results, "DOWNLOAD_SECONDS", 0.1)
    with pytest.raises(RuntimeError, match="timed out"):
        ci_results.download(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            tmp_path,
            io.BytesIO(),
        )
