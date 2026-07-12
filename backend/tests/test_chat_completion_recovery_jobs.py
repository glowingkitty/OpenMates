"""
Contract tests for sealing assistant completion before terminal delivery.

Successful epoch-1 inference must create one deterministic sealed job using the
registered recovery public key. The transaction receives no assistant plaintext
and retries preserve job and assistant identities.
"""

import json

from backend.shared.python_utils.chat_completion_recovery import (
    derive_recovery_keypair,
    open_recovery_envelope,
)
from backend.shared.python_utils.chat_completion_recovery_job import (
    build_sealed_recovery_job_data,
)


def test_successful_completion_is_sealed_before_transaction() -> None:
    chat_key = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
    chat_id = "22222222-2222-4222-8222-222222222222"
    private_key, public_key = derive_recovery_keypair(chat_key, chat_id, 7)
    task_id = "66666666-6666-4666-8666-666666666666"
    data = build_sealed_recovery_job_data(
        owner_id="11111111-1111-4111-8111-111111111111",
        owner_hash="owner-hash",
        chat_id=chat_id,
        turn_id="33333333-3333-4333-8333-333333333333",
        preflight_id="77777777-7777-4777-8777-777777777777",
        task_id=task_id,
        recovery_public_key=public_key,
        chat_key_version=7,
        content="Recovered hello",
        category="general_knowledge",
        model_name="model-a",
    )

    assert "Recovered hello" not in json.dumps(data)
    assert data["assistant_message_id"] == task_id
    envelope = json.loads(data["sealed_payload"])
    plaintext = open_recovery_envelope(
        envelope,
        recovery_private_key=private_key,
        owner_id="11111111-1111-4111-8111-111111111111",
        chat_id=chat_id,
        turn_id="33333333-3333-4333-8333-333333333333",
        job_id=data["job_id"],
        assistant_message_id=task_id,
        key_version=7,
    )
    payload = json.loads(plaintext)
    assert payload["content"] == "Recovered hello"
    assert payload["assistant_message_id"] == task_id


def test_recovery_job_identity_is_stable_across_retries() -> None:
    kwargs = {
        "owner_id": "11111111-1111-4111-8111-111111111111",
        "owner_hash": "owner-hash",
        "chat_id": "22222222-2222-4222-8222-222222222222",
        "turn_id": "33333333-3333-4333-8333-333333333333",
        "preflight_id": "77777777-7777-4777-8777-777777777777",
        "task_id": "66666666-6666-4666-8666-666666666666",
        "recovery_public_key": derive_recovery_keypair(
            "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
            "22222222-2222-4222-8222-222222222222",
            7,
        )[1],
        "chat_key_version": 7,
        "content": "Recovered hello",
        "category": None,
        "model_name": None,
    }
    assert build_sealed_recovery_job_data(**kwargs)["job_id"] == build_sealed_recovery_job_data(**kwargs)["job_id"]
