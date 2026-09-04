"""File-mapped regional storage CLI verifier tests.

The live CLI verifier is executable proof for encrypted regional replicas. This
file keeps the script filename mapped to unit coverage while checking that local
helpers emit only aggregate, non-secret evidence.
Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

import importlib


def _module():
    return importlib.import_module("scripts.verify_storage_replication_cli_chat")


# contract-test: supporting surface=cli assertions=storage.integrity.observable-reconcilable,storage.privacy.ciphertext-boundary
def test_verify_storage_replication_cli_chat_sanitizes_reports_and_safe_failures() -> None:
    module = _module()

    report = module.sanitize_runtime_report(
        {
            "status": "passed",
            "variant_count": 2,
            "verified_region_count": 3,
            "checksum": "secret",
            "object_key": "private/object.enc",
        }
    )

    assert report == {"status": "passed", "variant_count": 2, "verified_region_count": 3}
    assert module.classify_cli_failure("Unknown mention @missing", "cli_chat_create_failed") == "cli_mention_resolution_failed"
