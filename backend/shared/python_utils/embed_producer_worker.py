"""Fail-closed worker admission for detached AI embed tasks."""
from __future__ import annotations

import hashlib
import uuid
from contextlib import contextmanager
from typing import Any

from backend.shared.python_utils.chat_recovery_context import (
    RecoveryOutputContext, VerifiedOutputProducer,
    active_recovery_output_context, active_verified_output_producer,
)
from backend.shared.python_utils.embed_producer_dispatch import (
    PRODUCER_HEADER, PRODUCER_VERSION, _transaction, bind_task_invocation,
)
from backend.shared.python_utils.volatile_embed_authority import (
    EMBED_HEADER, require_live_incognito_session, verify_embed_header,
)


PROTECTED_EMBED_TASK_NAMES = frozenset({
    "apps.audio.tasks.skill_generate", "apps.audio.tasks.skill_speak",
    "apps.code.tasks.skill_image_to_html", "apps.docs.tasks.generate_docx",
    "apps.images.tasks.skill_generate", "apps.images.tasks.skill_generate_draft",
    "apps.images.tasks.skill_vectorize", "apps.models3d.tasks.skill_generate",
    "apps.music.tasks.skill_generate", "apps.social_media.tasks.skill_search",
    "apps.social_media.tasks.skill_get-posts", "apps.videos.tasks.skill_generate",
    "apps.videos.tasks.render_remotion",
})


class ProducerHold(RuntimeError):
    """No provider work is safe; the original sealed output remains recoverable."""


@contextmanager
def bound_output_producer(
    producer: VerifiedOutputProducer,
    recovery: RecoveryOutputContext | None,
):
    producer_token = active_verified_output_producer.set(producer)
    recovery_token = active_recovery_output_context.set(recovery)
    try:
        yield
    finally:
        active_recovery_output_context.reset(recovery_token)
        active_verified_output_producer.reset(producer_token)


def _envelope_identity(task_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, str]:
    if task_name in {"apps.docs.tasks.generate_docx", "apps.videos.tasks.render_remotion"}:
        source = args[0] if len(args) == 1 and isinstance(args[0], dict) else None
    else:
        source = kwargs.get("arguments")
    if not isinstance(source, dict):
        raise ProducerHold("invalid_task_envelope")
    identity = {}
    for key in ("user_id", "embed_id"):
        value = source.get(key)
        if not isinstance(value, str) or not value or len(value) > 255:
            raise ProducerHold("invalid_task_identity")
        identity[key] = value
    for key in ("chat_id", "message_id"):
        value = source.get(key)
        if value is None or value == "":
            identity[key] = ""
        elif isinstance(value, str) and len(value) <= 255:
            identity[key] = value
        else:
            raise ProducerHold("invalid_task_identity")
    team_id = source.get("team_id")
    if team_id is not None:
        if not isinstance(team_id, str) or not team_id or len(team_id) > 255:
            raise ProducerHold("invalid_team_identity")
        identity["team_id"] = team_id
    return identity


def _checked_context(
    resolved: dict[str, Any], identity: dict[str, str], task_id: str,
    task_name: str, binding: str,
) -> tuple[VerifiedOutputProducer, RecoveryOutputContext | None]:
    status = resolved.get("status")
    if status == "COMPLETED" and resolved.get("reason_code") == "direct_skill_already_completed":
        raise ProducerHold("producer_already_completed")
    if status not in {"PENDING", "SEALED", "DIRECT_AUTHORIZED", "LEGACY_AUTHORIZED"}:
        raise ProducerHold("producer_not_pending")
    context = resolved.get("context")
    if not isinstance(context, dict):
        raise ProducerHold("producer_context_missing")
    owner_hash = hashlib.sha256(identity["user_id"].encode("utf-8")).hexdigest()
    if (
        context.get("hashed_user_id") != owner_hash
        or (context.get("target_chat_id") or "") != identity["chat_id"]
        or (context.get("primary_message_id") or "") != identity["message_id"]
        or context.get("primary_embed_id") != identity["embed_id"]
    ):
        raise ProducerHold("producer_identity_mismatch")
    team_hash = context.get("hashed_team_id")
    if status in {"DIRECT_AUTHORIZED", "LEGACY_AUTHORIZED"}:
        intent_kind = resolved.get("intent_kind")
        if intent_kind not in {"rerender", "direct_skill", "legacy_chat"}:
            raise ProducerHold("direct_intent_kind_missing")
        if (status == "LEGACY_AUTHORIZED") != (intent_kind == "legacy_chat"):
            raise ProducerHold("legacy_intent_kind_mismatch")
        if intent_kind == "rerender" and (not identity["chat_id"] or not identity["message_id"]):
            raise ProducerHold("rerender_identity_missing")
        if intent_kind == "rerender" and (
            not isinstance(context.get("expected_embed_version"), int)
            or isinstance(context.get("expected_embed_version"), bool)
            or context["expected_embed_version"] < 1
        ):
            raise ProducerHold("rerender_head_version_missing")
        if intent_kind == "direct_skill" and not identity["chat_id"] and identity["message_id"]:
            raise ProducerHold("standalone_skill_scope_invalid")
    elif not identity["chat_id"] or not identity["message_id"]:
        raise ProducerHold("registered_ai_identity_missing")
    if identity.get("team_id") and hashlib.sha256(identity["team_id"].encode()).hexdigest() != team_hash:
        raise ProducerHold("producer_team_mismatch")
    if team_hash is not None and (not isinstance(team_hash, str) or len(team_hash) != 64):
        raise ProducerHold("producer_team_invalid")
    producer = VerifiedOutputProducer(
        classification=("authorized_legacy" if status == "LEGACY_AUTHORIZED"
                        else "authorized_direct" if status == "DIRECT_AUTHORIZED"
                        else "registered_ai"),
        intent_id=task_id, task_id=task_id, task_name=task_name, kwargs_binding=binding,
        primary_embed_id=identity["embed_id"],
        primary_message_id=identity["message_id"], target_chat_id=identity["chat_id"],
        owner_hash=owner_hash, hashed_team_id=team_hash,
        intent_kind=intent_kind if status in {"DIRECT_AUTHORIZED", "LEGACY_AUTHORIZED"} else None,
        expected_embed_version=context.get("expected_embed_version")
        if status == "DIRECT_AUTHORIZED" else None,
    )
    if status == "SEALED":
        raise ProducerHold("sealed_result_recovery_pending")
    if status in {"DIRECT_AUTHORIZED", "LEGACY_AUTHORIZED"}:
        return producer, None
    for key in ("root_chat_id", "turn_id", "preflight_id", "inference_task_id", "recovery_public_key"):
        if not isinstance(context.get(key), str) or not context[key]:
            raise ProducerHold("producer_crypto_context_missing")
    version = context.get("chat_key_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ProducerHold("producer_key_version_invalid")
    return producer, RecoveryOutputContext(
        owner_id=identity["user_id"], owner_hash=owner_hash,
        root_chat_id=context["root_chat_id"], target_chat_id=identity["chat_id"],
        turn_id=context["turn_id"], preflight_id=context["preflight_id"],
        inference_task_id=context["inference_task_id"],
        public_key=context["recovery_public_key"], key_version=version,
    )


async def verify_output_producer(
    *, task_name: str, task_id: str, args: tuple[Any, ...],
    kwargs: dict[str, Any], headers: Any,
) -> tuple[VerifiedOutputProducer, RecoveryOutputContext | None]:
    """Resolve an authoritative registration, or hold an admitted old task."""
    if task_name not in PROTECTED_EMBED_TASK_NAMES:
        raise ValueError("Not an embed producer task")
    identity = _envelope_identity(task_name, args, kwargs)
    try:
        uuid.UUID(task_id)
    except (TypeError, ValueError) as exc:
        raise ProducerHold("invalid_task_id") from exc
    volatile_header = headers.get(EMBED_HEADER) if isinstance(headers, dict) else None
    if volatile_header is not None:
        if isinstance(headers, dict) and headers.get(PRODUCER_HEADER) is not None:
            raise ProducerHold("conflicting_producer_authorities")
        binding = bind_task_invocation(
            task_name=task_name, task_uuid=task_id, args=list(args), kwargs=kwargs,
        )
        try:
            payload = verify_embed_header(
                volatile_header, task_uuid=task_id, task_name=task_name,
                kwargs_binding=binding, owner_id=identity["user_id"],
                chat_id=identity["chat_id"], message_id=identity["message_id"],
                embed_id=identity["embed_id"],
            )
        except ValueError as exc:
            raise ProducerHold("volatile_authority_invalid") from exc
        signed_team_hash = payload.get("hashed_team_id")
        if identity.get("team_id"):
            if hashlib.sha256(identity["team_id"].encode()).hexdigest() != signed_team_hash:
                raise ProducerHold("volatile_team_mismatch")
        if payload["mode"] == "incognito":
            try:
                await require_live_incognito_session(
                    payload["session_nonce"], payload["owner_hash"],
                )
            except ValueError as exc:
                raise ProducerHold("incognito_session_closed") from exc
        authority = await _transaction("verify_volatile_output_actor", {
            "protocol_version": PRODUCER_VERSION,
            "actor_user_id": identity["user_id"],
            "hashed_user_id": payload["owner_hash"],
            "target_chat_id": None,
            "hashed_team_id": signed_team_hash,
        })
        if authority.get("authorized") is not True:
            raise ProducerHold("volatile_actor_no_longer_authorized")
        # The signed main request is the only authority for this ephemeral
        # task. It grants no saved-chat recovery or persistent output rights.
        producer = VerifiedOutputProducer(
            classification="authorized_volatile", intent_id=task_id,
            task_id=task_id, task_name=task_name, kwargs_binding=binding,
            primary_embed_id=identity["embed_id"],
            primary_message_id=identity["message_id"],
            target_chat_id=identity["chat_id"],
            owner_hash=payload["owner_hash"], intent_kind=payload["mode"],
            hashed_team_id=signed_team_hash,
            session_nonce=payload.get("session_nonce"),
        )
        return producer, None
    header = headers.get(PRODUCER_HEADER) if isinstance(headers, dict) else None
    if header is None:
        if not identity["chat_id"] or not identity["message_id"]:
            raise ProducerHold("untagged_task_requires_durable_authorization")
        classification = await _transaction("classify_untagged_output_producer", {
            "protocol_version": PRODUCER_VERSION,
            "hashed_user_id": hashlib.sha256(identity["user_id"].encode()).hexdigest(),
            "target_chat_id": identity["chat_id"],
            "primary_message_id": identity["message_id"],
            "task_uuid": task_id, "task_name": task_name,
        })
        if classification.get("status") == "ADMITTED_UNTAGGED":
            raise ProducerHold("admitted_task_missing_intent")
        if classification.get("status") == "UNRELATED":
            # An expired or deleted preflight can look unrelated. Only a
            # separate durable direct authorization can run protected tasks.
            raise ProducerHold("untagged_task_requires_durable_authorization")
        raise ProducerHold("untagged_classification_unknown")
    if (
        not isinstance(header, dict) or type(header.get("version")) is not int
        or header.get("version") != PRODUCER_VERSION
        or header.get("intent_id") != task_id
    ):
        raise ProducerHold("invalid_producer_header")
    binding = bind_task_invocation(
        task_name=task_name, task_uuid=task_id, args=list(args), kwargs=kwargs,
    )
    resolved = await _transaction("resolve_output_producer", {
        "protocol_version": PRODUCER_VERSION, "task_uuid": task_id,
        "task_name": task_name, "kwargs_binding": binding,
    })
    producer, recovery = _checked_context(resolved, identity, task_id, task_name, binding)
    if producer.classification in {"authorized_direct", "authorized_legacy"}:
        claim = await _transaction("claim_authorized_direct_producer", {
            "protocol_version": PRODUCER_VERSION, "task_uuid": task_id,
            "task_name": task_name, "kwargs_binding": binding,
        })
        if (
            claim.get("status") != "RUNNING"
            or claim.get("claimed") is not True
            or claim.get("producer_intent_id") != task_id
            or claim.get("intent_kind") != producer.intent_kind
        ):
            raise ProducerHold("direct_intent_already_claimed")
    return producer, recovery
