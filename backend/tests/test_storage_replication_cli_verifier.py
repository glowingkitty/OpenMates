"""Real CLI image-chat regional verification helper tests.

The live verifier must parse bounded CLI JSON, require an image-grounded answer,
and expose only aggregate regional evidence. Runtime S3 and Directus calls remain
covered by the deployed TASK-6 verification rather than mocked as proof.
Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

import importlib
import sys

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


# contract-test: supporting surface=cli assertions=storage.integrity.observable-reconcilable,storage.privacy.ciphertext-boundary
def test_cli_verifier_parses_runtime_report_from_noisy_output() -> None:
    module = _module()

    report = module.parse_runtime_report(
        "Secret key missing from optional legacy path\n"
        '{"status":"passed","variant_count":1,"object_key":"private.bin"}\n'
    )

    assert module.sanitize_runtime_report(report) == {
        "status": "passed",
        "variant_count": 1,
    }


# contract-test: supporting surface=cli assertions=storage.integrity.observable-reconcilable,storage.privacy.ciphertext-boundary
def test_cli_verifier_reports_safe_stage_failure_labels() -> None:
    module = _module()

    assert module.classify_cli_failure("Upload failed: image.svg — 500", "cli_chat_create_failed") == "cli_file_upload_failed"
    assert module.classify_cli_failure("Response timed out waiting for AI", "cli_chat_create_failed") == "cli_chat_response_timeout"
    assert module.classify_cli_failure(
        "Encrypted chat preflight was rejected.",
        "cli_chat_create_failed",
    ) == "cli_chat_preflight_rejected"

    with pytest.raises(RuntimeError, match="cli_login_failed"):
        module._run(
            [sys.executable, "-c", "import sys; sys.exit(7)"],
            failure_class="cli_login_failed",
        )


# contract-test: supporting surface=cli assertions=storage.integrity.observable-reconcilable
def test_cli_verifier_uses_unique_proof_slug_from_content_hash() -> None:
    module = _module()

    assert module._proof_slug("abcdef0123456789" * 4) == "regional-storage-abcdef0123456789"


# contract-test: supporting surface=cli assertions=storage.integrity.observable-reconcilable,storage.privacy.ciphertext-boundary
def test_cli_verifier_final_host_report_overrides_runtime_ready_status() -> None:
    module = _module()

    report = module.build_host_report(
        "image-question",
        {
            "status": "replicas_ready",
            "variant_count": 3,
            "verified_region_count": 3,
            "deleted_region_count": 3,
        },
    )

    assert report == {
        "status": "passed",
        "scenario": "image-question",
        "chat_completed": True,
        "image_grounded": True,
        "variant_count": 3,
        "verified_region_count": 3,
        "deleted_region_count": 3,
        "object_keys_in_output": False,
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
    cleanup_command = module._runtime_upload_cleanup_command(
        content_hash="b" * 64,
        regions=("nbg1", "fsn1", "hel1"),
        timeout=60,
    )
    assert cleanup_command[4] == "/tmp/storage-verifier.py"
    assert "--runtime-cleanup-content-hash" in cleanup_command
    assert cleanup_command[-1] == "60"


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


# contract-test: supporting surface=cli assertions=storage.deletion.global-authoritative,storage.privacy.ciphertext-boundary
def test_cli_verifier_treats_missing_orphan_upload_as_cleaned(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()

    class Completed:
        stdout = '{"status":"not_found","upload_record_found":false,"object_keys_in_output":false}'
        stderr = ""

    monkeypatch.setattr(module, "_run_runtime", lambda _command, *, timeout: Completed())

    assert module._run_runtime_upload_cleanup(["unused"], timeout=1)["status"] == "not_found"
