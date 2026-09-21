# contract-test-file: tooling
"""Validate CI candidate artifact boundaries without Docker or network access."""

import datetime as dt
import hashlib

import pytest

from scripts import ci_candidate_artifact as artifact


def test_upload_is_private_expiring_and_digest_bound(tmp_path, monkeypatch):
    patch = tmp_path / "candidate.patch"
    patch.write_bytes(b"synthetic patch")
    digest = hashlib.sha256(patch.read_bytes()).hexdigest()
    commands = []

    def run(command, *, env=None):
        commands.append((command, env))
        if command[:2] == ["docker", "cp"] or "mkdir" in command or "rm" in command:
            return artifact.subprocess.CompletedProcess(command, 0, "", "")
        return artifact.subprocess.CompletedProcess(
            command,
            0,
            '{"bucket":"dev-openmates-ci-candidates","key":"candidates/test.patch","url":"https://nbg1.your-objectstorage.com/dev-openmates-ci-candidates/candidates/test.patch?X-Amz-Signature=test"}\n',
            "",
        )

    monkeypatch.setattr(artifact, "_run", run)
    result = artifact.upload_patch(
        patch,
        source="a" * 40,
        sha256=digest,
        now=dt.datetime(2026, 9, 19, tzinfo=dt.timezone.utc),
    )
    assert result["expires_at"] == "2026-09-21T00:00:00+00:00"
    assert any("OPENMATES_CI_CANDIDATE_REQUEST" in (env or {}) for _, env in commands)
    assert commands[-1][0][-2:] == ["-f", commands[-1][0][-1]]


def test_rejects_tampering_and_non_presigned_hosts(tmp_path):
    patch = tmp_path / "candidate.patch"
    patch.write_bytes(b"synthetic patch")
    with pytest.raises(ValueError, match="digest changed"):
        artifact.upload_patch(patch, source="a" * 40, sha256="0" * 64)
    with pytest.raises(ValueError, match="Hetzner HTTPS"):
        artifact.validate_url("https://example.com/public.patch")
