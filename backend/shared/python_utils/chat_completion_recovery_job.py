"""
Build sealed recovery-job payloads after successful AI inference.

This helper fixes stable job and assistant identities before persistence and
keeps plaintext out of the Directus transaction request. It is intentionally
pure so byte-level behavior is testable without Celery or service containers.
"""

from __future__ import annotations

import json
import uuid

from backend.shared.python_utils.chat_completion_recovery import seal_recovery_payload


def build_sealed_recovery_job_data(
    *,
    owner_id: str,
    owner_hash: str,
    chat_id: str,
    turn_id: str,
    preflight_id: str,
    task_id: str,
    recovery_public_key: str,
    chat_key_version: int,
    content: str,
    category: str | None,
    model_name: str | None,
) -> dict[str, object]:
    task_namespace = uuid.UUID(task_id)
    job_id = str(uuid.uuid5(task_namespace, "recovery-job"))
    assistant_message_id = task_id
    plaintext = json.dumps(
        {
            "assistant_message_id": assistant_message_id,
            "category": category,
            "chat_id": chat_id,
            "content": content,
            "job_id": job_id,
            "key_version": chat_key_version,
            "model_name": model_name,
            "turn_id": turn_id,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    envelope = seal_recovery_payload(
        plaintext,
        recovery_public_key=recovery_public_key,
        owner_id=owner_id,
        chat_id=chat_id,
        turn_id=turn_id,
        job_id=job_id,
        assistant_message_id=assistant_message_id,
        key_version=chat_key_version,
    )
    return {
        "protocol_version": 1,
        "job_id": job_id,
        "hashed_user_id": owner_hash,
        "chat_id": chat_id,
        "turn_id": turn_id,
        "preflight_id": preflight_id,
        "inference_task_id": task_id,
        "assistant_message_id": assistant_message_id,
        "chat_key_version": chat_key_version,
        "sealed_payload": json.dumps(envelope, sort_keys=True, separators=(",", ":")),
    }
