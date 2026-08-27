"""Real CLI image-chat regional verification helper tests.

The live verifier must parse bounded CLI JSON, require an image-grounded answer,
and expose only aggregate regional evidence. Runtime S3 and Directus calls remain
covered by the deployed TASK-6 verification rather than mocked as proof.
Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

import importlib

import pytest


def _module():
    try:
        return importlib.import_module("scripts.verify_storage_replication_cli_chat")
    except ModuleNotFoundError as exc:
        pytest.fail(f"CLI regional replication verifier is not implemented: {exc}")


# contract-test: supporting surface=cli assertions=storage.replication.active-write-durable-outbox,storage.privacy.ciphertext-boundary
def test_cli_verifier_parses_final_json_and_requires_grounded_marker() -> None:
    module = _module()
    payload = module.parse_cli_json(
        'progress {"status":"streaming"}\n{"status":"completed","chat_id":"chat-1","assistant":"BRANDENBURG_GATE"}\n'
    )

    assert payload["chat_id"] == "chat-1"
    module.require_grounded_answer(payload, "BRANDENBURG_GATE")
    with pytest.raises(RuntimeError, match="image_grounding_failed"):
        module.require_grounded_answer({"assistant": "I cannot inspect it"}, "BRANDENBURG_GATE")


# contract-test: supporting surface=cli assertions=storage.integrity.observable-reconcilable,storage.privacy.ciphertext-boundary
def test_cli_verifier_sanitizes_runtime_replica_evidence() -> None:
    module = _module()
    report = module.sanitize_runtime_report(
        {
            "status": "passed",
            "variant_count": 2,
            "verified_region_count": 3,
            "deleted_region_count": 0,
            "object_key": "private/key.bin",
            "checksum": "a" * 64,
        }
    )

    assert report == {
        "status": "passed",
        "variant_count": 2,
        "verified_region_count": 3,
        "deleted_region_count": 0,
    }


# contract-test: supporting surface=cli assertions=storage.replication.active-write-durable-outbox,storage.privacy.ciphertext-boundary
def test_cli_verifier_accepts_installed_cli_and_runtime_script(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    monkeypatch.setenv("OPENMATES_CLI", "/usr/local/bin/openmates")
    monkeypatch.setenv("OPENMATES_STORAGE_RUNTIME_VERIFIER", "/tmp/storage-verifier.py")

    assert module._cli_command("chats", "new") == ["/usr/local/bin/openmates", "chats", "new"]
    command = module._runtime_command(
        content_hash="a" * 64,
        regions=("nbg1", "fsn1", "hel1"),
        expect_deleted=False,
        timeout=180,
        wait_for_cleanup=True,
    )
    assert command[4] == "/tmp/storage-verifier.py"
    assert command[-1] == "--wait-for-cleanup"


# contract-test: supporting surface=cli assertions=storage.replication.active-write-durable-outbox,storage.privacy.ciphertext-boundary
def test_cli_verifier_streams_durable_runtime_source_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    monkeypatch.delenv("OPENMATES_STORAGE_RUNTIME_VERIFIER", raising=False)

    command = module._runtime_command(
        content_hash="a" * 64,
        regions=("nbg1", "fsn1", "hel1"),
        expect_deleted=False,
        timeout=180,
        wait_for_cleanup=True,
    )

    assert command[:6] == ["docker", "exec", "-i", "api", "python", "-"]
    assert command[-1] == "--wait-for-cleanup"
