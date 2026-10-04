"""
Build sealed recovery-job payloads after successful AI inference.

This helper fixes stable job and assistant identities before persistence and
keeps plaintext out of the Directus transaction request. It is intentionally
pure so byte-level behavior is testable without Celery or service containers.
"""

from __future__ import annotations

import json
import uuid

from backend.shared.python_utils.chat_completion_recovery import seal_recovery_output, seal_recovery_payload


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
    inference_task_id: str | None = None,
    assistant_message_id: str | None = None,
) -> dict[str, object]:
    durable_inference_task_id = inference_task_id or task_id
    durable_assistant_message_id = assistant_message_id or task_id
    task_namespace = uuid.UUID(durable_assistant_message_id)
    job_id = str(uuid.uuid5(task_namespace, "recovery-job"))
    plaintext = json.dumps(
        {
            "assistant_message_id": durable_assistant_message_id,
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
        assistant_message_id=durable_assistant_message_id,
        key_version=chat_key_version,
    )
    return {
        "protocol_version": 1,
        "job_id": job_id,
        "hashed_user_id": owner_hash,
        "chat_id": chat_id,
        "turn_id": turn_id,
        "preflight_id": preflight_id,
        "inference_task_id": durable_inference_task_id,
        "assistant_message_id": durable_assistant_message_id,
        "chat_key_version": chat_key_version,
        "sealed_payload": json.dumps(envelope, sort_keys=True, separators=(",", ":")),
    }


def build_sealed_recovery_output_data(
    *, owner_id: str, owner_hash: str, root_chat_id: str, target_chat_id: str,
    turn_id: str, preflight_id: str, inference_task_id: str,
    recovery_public_key: str, chat_key_version: int, subject_id: str,
    output_kind: str, output_version: int, content: object,
    message_role: str | None = None,
) -> dict[str, object]:
    """Build a stable v2 record; retries may reseal but keep one output identity."""
    record_id = str(uuid.uuid5(
        uuid.UUID(turn_id),
        f"{target_chat_id}:{subject_id}:{output_kind}:{output_version}",
    ))
    if output_kind == "message" and message_role not in ("user", "assistant"):
        raise ValueError("A sealed message requires a fixed canonical role")
    if output_kind != "message" and message_role is not None:
        raise ValueError("Only a message may carry a canonical role")
    plaintext = json.dumps({
        "record_id": record_id,
        "root_chat_id": root_chat_id,
        "target_chat_id": target_chat_id,
        "turn_id": turn_id,
        "subject_id": subject_id,
        "output_kind": output_kind,
        "output_version": output_version,
        "key_version": chat_key_version,
        "content": content,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    envelope = seal_recovery_output(
        plaintext, recovery_public_key=recovery_public_key,
        owner_id=owner_id, root_chat_id=root_chat_id,
        target_chat_id=target_chat_id, turn_id=turn_id,
        record_id=record_id, subject_id=subject_id,
        output_kind=output_kind, output_version=output_version,
        key_version=chat_key_version,
    )
    return {
        "protocol_version": 1,  # transaction protocol remains v1; envelope is v2
        "record_id": record_id,
        "hashed_user_id": owner_hash,
        "root_chat_id": root_chat_id,
        "target_chat_id": target_chat_id,
        "turn_id": turn_id,
        "preflight_id": preflight_id,
        "inference_task_id": inference_task_id,
        "subject_id": subject_id,
        "output_kind": output_kind,
        "output_version": output_version,
        "chat_key_version": chat_key_version,
        **({"message_role": message_role} if message_role else {}),
        "sealed_payload": json.dumps(envelope, sort_keys=True, separators=(",", ":")),
    }
