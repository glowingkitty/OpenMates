"""Media writer rollout manifest contracts.

R2 writers must remain disabled until every pinned R1 reader proof is present.
The checked-in audit validates activation metadata and the rollback floor without
performing network access or mutating rollout state.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.audit_media_encryption_rollout import validate_rollout_manifest


def _manifest() -> dict:
    return {
        "schema_version": 1,
        "write_version": 1,
        "v2_format": "aes-gcm-nonce-prefixed-v1",
        "minimum_r1_commit": None,
        "activated_at": None,
        "r1_evidence": {
            "required": ["V-REST-MEDIA-READER", "V-WEB-DEPLOYED", "V-APPLE"],
            "passed": [],
        },
    }


def test_legacy_writer_manifest_remains_valid_before_activation() -> None:
    validate_rollout_manifest(_manifest())


def test_r2_activation_requires_all_reader_evidence_and_rollback_floor() -> None:
    manifest = _manifest()
    manifest["write_version"] = 2

    with pytest.raises(ValueError, match="minimum_r1_commit"):
        validate_rollout_manifest(manifest)

    manifest["minimum_r1_commit"] = "f5a9bde33"
    manifest["activated_at"] = "2026-08-04T10:30:00Z"
    with pytest.raises(ValueError, match="R1 evidence"):
        validate_rollout_manifest(manifest)

    manifest["r1_evidence"]["passed"] = list(manifest["r1_evidence"]["required"])
    validate_rollout_manifest(manifest)


def test_checked_in_rollout_manifest_is_valid() -> None:
    path = Path(__file__).resolve().parents[2] / "config/media_encryption_rollout.yml"
    validate_rollout_manifest(yaml.safe_load(path.read_text(encoding="utf-8")))
