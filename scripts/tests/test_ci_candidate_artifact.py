# contract-test-file: tooling
"""Validate CI candidate artifact boundaries without Docker or network access."""

import datetime as dt
import hashlib
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from scripts import ci_candidate_artifact as artifact


@pytest.mark.parametrize("bucket_access", ["owner", "public_acl", "policy", "missing_expiry"])
def test_container_checks_privacy_without_rewriting_acl(tmp_path, monkeypatch, bucket_access, capsys):
    class StorageError(Exception):
        response = {"Error": {"Code": "NoSuchBucketPolicy"}}

    patch = tmp_path / "candidate.patch"
    patch.write_bytes(b"synthetic patch")
    client = Mock()
    grants = [{"Grantee": {"Type": "CanonicalUser", "ID": "owner"}, "Permission": "FULL_CONTROL"}]
    if bucket_access == "public_acl":
        grants.append({"Grantee": {"Type": "Group"}, "Permission": "READ"})
    client.get_bucket_acl.return_value = {"Owner": {"ID": "owner"}, "Grants": grants}
    if bucket_access != "policy":
        client.get_bucket_policy.side_effect = StorageError()
    client.get_bucket_lifecycle_configuration.return_value = {
        "Rules": [] if bucket_access == "missing_expiry" else [{
            "ID": "ExpireCiCandidatesAfterTwoDays",
            "Status": "Enabled",
            "Filter": {"Prefix": "candidates/"},
            "Expiration": {"Days": 2},
        }],
    }
    client.generate_presigned_url.return_value = "https://nbg1.your-objectstorage.com/?X-Amz-Signature=test"
    manager = SimpleNamespace(initialize=AsyncMock(), get_secret=AsyncMock(return_value="test"))
    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=Mock(return_value=client)))
    monkeypatch.setitem(sys.modules, "botocore.config", SimpleNamespace(Config=Mock()))
    monkeypatch.setitem(sys.modules, "botocore.exceptions", SimpleNamespace(ClientError=StorageError))
    monkeypatch.setitem(
        sys.modules, "backend.core.api.app.utils.secrets_manager",
        SimpleNamespace(SecretsManager=lambda: manager),
    )
    monkeypatch.setenv("OPENMATES_CI_CANDIDATE_REQUEST", json.dumps({
        "bucket": artifact.BUCKET_NAME, "container_path": str(patch), "key": "candidates/test.patch",
        "source": "a" * 40, "sha256": "b" * 64, "lifecycle_days": 2, "expires_in": 3600,
    }))
    if bucket_access == "owner":
        exec(artifact.INNER_UPLOAD_CODE, {})
        assert client.put_object.call_args.kwargs["ACL"] == "private"
        assert "X-Amz-Signature" in capsys.readouterr().out
    else:
        with pytest.raises(RuntimeError, match="CI candidate bucket"):
            exec(artifact.INNER_UPLOAD_CODE, {})
        client.put_object.assert_not_called()
    client.put_bucket_acl.assert_not_called()
    client.put_bucket_lifecycle_configuration.assert_not_called()


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
