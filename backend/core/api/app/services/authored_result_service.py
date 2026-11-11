"""Materialize explicitly authored records through the existing encrypted lifecycle.

This is an internal chat-content producer, not a discovery skill or public route.
The carrier owns one level of typed children. Selected upload image descriptors
are copied only inside the intended child's encrypted content; uploads retain
their own identity, ownership, and keys.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from toon_format import decode, encode

from backend.apps.ai.utils.authored_result_fences import (
    get_authored_results_limits,
    get_authored_results_schema,
    get_authoring_definitions,
    normalize_authored_results_source,
)
from backend.core.api.app.services.authored_existing_cards import (
    authored_card_kind,
    resolve_existing_card,
)
from backend.core.api.app.services.authored_result_progressive import (
    CarrierProgress,
    PublishedCard,
    carrier_progress,
    existing_progress,
    finish_progress,
    track_background,
)
from backend.core.api.app.services.event_embed_enrichment import (
    discard_untrusted_event_coordinates,
    enrich_event_coordinates,
)
from backend.shared.python_utils.chat_recovery_context import (
    RequiredRecoveryOutputError,
    active_legacy_output_context,
    active_recovery_output_context,
)

logger = logging.getLogger(__name__)
AUTHORED_RESULTS_TYPE = "authored_results"
MAX_AUTHORED_CHILDREN = 50


def authored_child_id(carrier_id: str, local_id: str) -> str:
    """Reserve ordinary retry-stable identities without claiming Project provenance.

    UUIDv5 is a reserved registered-producer identity in durable embed storage.
    Carrier IDs are random UUIDs; hashing their scope plus the local label keeps
    ordinary UUIDv4-shaped child identities stable without that authority claim.
    """
    digest = hashlib.sha256(f"openmates:authored:{carrier_id}:{local_id}".encode()).digest()
    return str(uuid.UUID(bytes=digest[:16], version=4))


def _resource_details(kind: str, content: dict[str, Any]) -> dict[str, Any]:
    """Select the same fields the shared resource schema admits, without authority."""
    definition = get_authoring_definitions()[kind]
    schema = get_authored_results_schema([kind])
    ref = definition["details_schema"].get("$ref", "").removeprefix("#/$defs/")
    keys = schema.get("$defs", {}).get(ref, {}).get("properties", {})
    return {key: copy.deepcopy(content[key]) for key in keys if key != "embed_ref" and key in content}


def _has_resolved_resource(kind: str, content: dict[str, Any]) -> bool:
    """Revalidate real resource identity after consuming an untrusted reference."""
    if kind == "images.image_result" and content.get("authored_media"):
        return True
    validated = normalize_authored_results_source(json.dumps({
        "schemaVersion": 1, "items": [{
            "id": "resource", "kind": kind, "title": content["title"],
            "origin": "user_provided", "details": _resource_details(kind, content),
        }],
    }))
    return bool(validated.items)


async def _authorized_reference(
    service: Any, reference: str, *, chat_id: str, user_id_hash: str,
    user_vault_key_id: str, log_prefix: str,
) -> tuple[str, dict[str, Any]] | None:
    """Only resolve identities handed off by the authorized inference context."""
    index = getattr(service, "authoring_reference_index", {})
    embed_id = index.get(reference) if isinstance(index, dict) else None
    if not isinstance(embed_id, str):
        return None
    record = await service._get_cached_embed(embed_id, user_vault_key_id, log_prefix)
    if not isinstance(record, dict) or record.get("hashed_user_id") != user_id_hash:
        return None
    # The index can contain explicitly authorized references from other chats;
    # ownership still must match, and arbitrary guessed UUIDs never reach here.
    toon = await service._get_cached_embed_toon(embed_id, user_vault_key_id, log_prefix)
    if not toon:
        return None
    content = decode(toon)
    return (embed_id, content) if isinstance(content, dict) else None


async def _selected_image_descriptor(
    service: Any, embed_id: str, content: dict[str, Any], user_vault_key_id: str,
) -> dict[str, Any] | None:
    """Retain only the selected image and its real variant encryption metadata."""
    if content.get("type") not in {"image", "image_result", "generated_image"}:
        return None
    files = content.get("files")
    if not isinstance(files, dict):
        return None
    selected = {
        name: copy.deepcopy(files[name]) for name in ("preview", "original", "full")
        if isinstance(files.get(name), dict) and isinstance(files[name].get("s3_key"), str)
    }
    if not selected:
        return None
    key = content.get("aes_key")
    if not isinstance(key, str) and isinstance(content.get("vault_wrapped_aes_key"), str):
        key = await service.encryption_service.decrypt_with_user_key(
            content["vault_wrapped_aes_key"], user_vault_key_id,
        )
    try:
        if len(base64.b64decode(key or "", validate=True)) != 32:
            return None
    except (TypeError, ValueError):
        return None
    if not isinstance(content.get("s3_base_url"), str):
        return None
    descriptor = {
        "source_embed_id": embed_id,
        "s3_base_url": content["s3_base_url"],
        "aes_key": key,
        "files": selected,
    }
    if isinstance(content.get("aes_nonce"), str):
        descriptor["aes_nonce"] = content["aes_nonce"]
    return descriptor


async def _resolve_record_references(
    service: Any, content: dict[str, Any], *, chat_id: str, user_id_hash: str,
    user_vault_key_id: str, log_prefix: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Validate provenance refs and bind selected images without network fetches."""
    result = copy.deepcopy(content)
    authored = result["authoring"]
    warnings: list[dict[str, str]] = []
    definition = get_authoring_definitions()[authored["kind"]]
    resource_reference = result.pop("embed_ref", None)
    resource_image = None
    if definition.get("real_asset") and resource_reference:
        resolved = await _authorized_reference(
            service, resource_reference, chat_id=chat_id, user_id_hash=user_id_hash,
            user_vault_key_id=user_vault_key_id, log_prefix=log_prefix,
        )
        accepted_types = ({"image", "image_result", "generated_image"}
                          if authored["kind"] == "images.image_result" else {definition["backend_type"]})
        if not resolved or resolved[1].get("type") not in accepted_types:
            warnings.append({"code": "unavailable_resource_reference", "path": "details.embed_ref"})
        else:
            source = resolved[1]
            for key, value in _resource_details(authored["kind"], source).items():
                if key != "title" and key not in result:
                    result[key] = value
            if authored["kind"] == "images.image_result":
                resource_image = await _selected_image_descriptor(service, resolved[0], source, user_vault_key_id)
                if resource_image is None and not result.get("image_url") and not result.get("public_image_url"):
                    warnings.append({"code": "unavailable_resource_reference", "path": "details.embed_ref"})
    sources = []
    for source in authored.get("sources", []):
        reference = source.get("embed_ref")
        if reference and not await _authorized_reference(
            service, reference, chat_id=chat_id, user_id_hash=user_id_hash,
            user_vault_key_id=user_vault_key_id, log_prefix=log_prefix,
        ):
            warnings.append({"code": "unavailable_source_reference", "path": "sources"})
            continue
        sources.append(source)
    authored["sources"] = sources
    images = []
    descriptors = [resource_image] if resource_image else []
    for image in authored.get("images", []):
        if isinstance(image, str):
            images.append(image)
            continue
        reference = image.get("embed_ref")
        if not reference:
            images.append(image)
            continue
        resolved = await _authorized_reference(
            service, reference, chat_id=chat_id, user_id_hash=user_id_hash,
            user_vault_key_id=user_vault_key_id, log_prefix=log_prefix,
        )
        descriptor = (await _selected_image_descriptor(
            service, resolved[0], resolved[1], user_vault_key_id,
        )) if resolved else None
        if descriptor is None:
            warnings.append({"code": "unavailable_image_reference", "path": "images"})
            continue
        descriptors.append({**descriptor, **{
            key: image[key] for key in ("caption", "attribution") if key in image
        }})
        images.append(image)
    if "images" in authored:
        authored["images"] = images
    if descriptors:
        result["authored_media"] = descriptors
    return result, warnings


def _selected_asset_storage_references(content: dict[str, Any]) -> list[dict[str, str]]:
    """Index only renditions already copied into this child's encrypted media.

    Source embed IDs are provenance, never storage dependencies or sharing grants.
    The existing storage collector consumes this flat metadata without decrypting
    content, so a surviving card can retain its own selected objects independently.
    """
    keys: set[str] = set()
    for media in content.get("authored_media", []):
        for name in ("preview", "original", "full"):
            variant = media.get("files", {}).get(name)
            key = variant.get("s3_key") if isinstance(variant, dict) else None
            if isinstance(key, str) and key.strip():
                keys.add(key)
    return [{"bucket": "chatfiles", "key": key} for key in sorted(keys)]


def _content_hash(content: dict[str, Any]) -> str:
    return hashlib.sha256(encode(content).encode()).hexdigest()


async def _materialize_child(
    service: Any, carrier_id: str, item: Any, warnings: list[dict[str, str]], *,
    chat_id: str, user_id_hash: str, user_vault_key_id: str, log_prefix: str,
) -> dict[str, Any] | None:
    """Build one card's content and stable id; coordinates are added after publication."""
    content, reference_warnings = await _resolve_record_references(
        service, item.content, chat_id=chat_id, user_id_hash=user_id_hash,
        user_vault_key_id=user_vault_key_id, log_prefix=log_prefix,
    )
    warnings.extend(reference_warnings)
    # A resource-only image reference cannot become a real asset when its
    # source failed authorization. Other informational cards remain usable.
    if (get_authoring_definitions()[item.kind].get("real_asset")
            and not _has_resolved_resource(item.kind, content)):
        warnings.append({"code": "unavailable_resource", "path": "items"})
        return None
    # Coordinates come from supplied facts or a server venue lookup, never from
    # model-written values: only user-supplied cards keep a valid supplied pair.
    needs_lookup = discard_untrusted_event_coordinates(
        item.backend_type, content, keep_supplied=content["authoring"]["origin"] == "user_provided",
    )
    child_id = authored_child_id(carrier_id, item.local_id)
    content.update({
        "type": item.backend_type, "app_id": item.app_id, "skill_id": item.skill_id,
        "embed_ref": service._generate_direct_embed_ref(item.backend_type, child_id, content),
        "status": "finished",
    })
    return {"id": child_id, "item": item, "content": content, "needs_lookup": needs_lookup}


def _require_media_admission(service: Any, children: list[dict[str, Any]]) -> None:
    if (any(child["content"].get("authored_media") for child in children)
            and not service._volatile_incognito_publication_required()
            and active_recovery_output_context.get() is None
            and active_legacy_output_context.get() is None):
        raise RequiredRecoveryOutputError("Selected media lacks durable output admission")


async def _send_child(
    service: Any, child: dict[str, Any], child_index: int, *, carrier_id: str,
    cached: dict[str, Any], restage: bool, user_id: str, user_id_hash: str,
    user_vault_key_id: str, log_prefix: str, now: int,
) -> None:
    """Encrypt, cache and publish one finished card inside the caller's batch."""
    item = child["item"]
    toon = encode(child["content"])
    encrypted, _ = await service.encryption_service.encrypt_with_user_key(toon, user_vault_key_id)
    child_data = {
        "embed_id": child["id"], "type": item.backend_type,
        "app_id": item.app_id, "skill_id": item.skill_id,
        "chat_id": cached["chat_id"], "message_id": cached["message_id"],
        "hashed_chat_id": cached["hashed_chat_id"], "hashed_message_id": cached["hashed_message_id"],
        "hashed_task_id": cached.get("hashed_task_id"), "hashed_user_id": user_id_hash,
        "parent_embed_id": carrier_id, "status": "finished", "encryption_mode": "client",
        "is_private": cached.get("is_private", False), "is_shared": False,
        "encrypted_content": encrypted, "text_length_chars": len(toon),
        "created_at": now, "updated_at": now,
        "s3_file_keys": _selected_asset_storage_references(child["content"]),
    }
    if not service._volatile_incognito_publication_required() and (child_data["s3_file_keys"] or restage):
        # Match generated-asset persistence: the first store_embed
        # round trip merges this server-owned dependency sidecar.
        # Stage it before publication; raw child cache writes and
        # encrypted recovery sealing retain their existing ordering.
        try:
            client = await service.cache_service.client
            if not client or not await client.set(
                f"embed:{child['id']}:s3_file_keys",
                json.dumps(child_data["s3_file_keys"]), ex=3600,
            ):
                raise RequiredRecoveryOutputError("Authored media storage references are unavailable")
        except RequiredRecoveryOutputError:
            raise
        except Exception as error:
            raise RequiredRecoveryOutputError("Authored media storage references are unavailable") from error
    sent = await service.send_embed_data_to_client(
        embed_id=child["id"], embed_type=item.backend_type, content_toon=toon,
        chat_id=cached["chat_id"], message_id=cached["message_id"], user_id=user_id,
        user_id_hash=user_id_hash, status="finished", parent_embed_id=carrier_id,
        text_length_chars=len(toon), created_at=now, updated_at=now,
        is_private=cached.get("is_private", False), is_shared=False,
        app_id=item.app_id, skill_id=item.skill_id, log_prefix=log_prefix,
        check_cache_status=False, producer_child_index=child_index,
        finished_cache_data=child_data, finished_cache_vault_key_id=user_vault_key_id,
    )
    if not sent:
        raise RequiredRecoveryOutputError("Authored child delivery failed")


def _carrier_content(
    existing: dict[str, Any], *, title: str, status: str, cards: list[dict[str, str]],
    member_ids: list[str], view: dict[str, Any], source_json: str, version: int,
    validation: dict[str, Any], pending_count: int = 0,
) -> dict[str, Any]:
    content = {
        "type": AUTHORED_RESULTS_TYPE, "app_id": "ai", "skill_id": AUTHORED_RESULTS_TYPE,
        "schema_version": 1, "title": title, "status": status,
        "embed_ids": [card["embed_id"] for card in cards], "member_ids": member_ids,
        "items": cards, "view": view, "source_json": source_json,
        "embed_ref": existing.get("embed_ref"), "version_number": version, "validation": validation,
    }
    if pending_count:
        # Announced members still being written; the web shows placeholder cards.
        content["pending_count"] = pending_count
    return content


async def _send_finished_carrier(
    service: Any, parent_content: dict[str, Any], *, embed_id: str, cached: dict[str, Any],
    source_hash: str, user_id: str, user_id_hash: str, user_vault_key_id: str,
    log_prefix: str, now: int,
) -> None:
    toon = encode(parent_content)
    encrypted, _ = await service.encryption_service.encrypt_with_user_key(toon, user_vault_key_id)
    status, child_ids, version = (parent_content["status"], parent_content["embed_ids"],
                                  parent_content["version_number"])
    parent_data = {
        **cached, "type": AUTHORED_RESULTS_TYPE, "app_id": "ai",
        "skill_id": AUTHORED_RESULTS_TYPE, "encrypted_content": encrypted,
        "status": status, "embed_ids": child_ids, "version_number": version,
        "content_hash": source_hash, "updated_at": now,
    }
    sent = await service.send_embed_data_to_client(
        embed_id=embed_id, embed_type=AUTHORED_RESULTS_TYPE, content_toon=toon,
        chat_id=cached["chat_id"], message_id=cached["message_id"], user_id=user_id,
        user_id_hash=user_id_hash, status=status, embed_ids=child_ids,
        app_id="ai", skill_id=AUTHORED_RESULTS_TYPE,
        version_number=version, content_hash=source_hash,
        is_private=cached.get("is_private", False), is_shared=cached.get("is_shared", False),
        created_at=cached.get("created_at"), updated_at=now, log_prefix=log_prefix,
        check_cache_status=False, finished_cache_data=parent_data,
        finished_cache_vault_key_id=user_vault_key_id,
    )
    if not sent:
        raise RequiredRecoveryOutputError("Authored carrier delivery failed")


async def _geocode_card(
    service: Any, child: dict[str, Any], child_index: int, *, carrier_id: str,
    cached: dict[str, Any], user_id: str, user_id_hash: str, user_vault_key_id: str,
    log_prefix: str,
) -> None:
    """Look up the venue after publication and republish the same card with coordinates."""
    content = await enrich_event_coordinates(
        child["item"].backend_type, copy.deepcopy(child["content"]), log_prefix, trust_supplied=False,
    )
    if content == child["content"]:
        return
    try:
        async with service._defer_completed_embed_publications() as batch:
            await _send_child(
                service, {**child, "content": content}, child_index, carrier_id=carrier_id,
                cached=cached, restage=True, user_id=user_id, user_id_hash=user_id_hash,
                user_vault_key_id=user_vault_key_id, log_prefix=log_prefix,
                now=int(datetime.now(timezone.utc).timestamp()),
            )
            await service._flush_completed_embed_publications(batch)
    except RequiredRecoveryOutputError:
        # The card stays published without coordinates; nothing is invented.
        logger.warning("%s Authored card %s coordinate update was not delivered", log_prefix, child["id"])


def _schedule_geocoding(
    service: Any, children: list[tuple[int, dict[str, Any]]], progress: CarrierProgress | None, *,
    carrier_id: str, cached: dict[str, Any], user_id: str, user_id_hash: str,
    user_vault_key_id: str, log_prefix: str,
) -> None:
    """Start venue lookups outside any publication batch, once per card."""
    for child_index, child in children:
        if not child["needs_lookup"] or (progress is not None and child["id"] in progress.geocoding):
            continue
        if progress is not None:
            progress.geocoding.add(child["id"])
        track_background(cached["message_id"], _geocode_card(
            service, copy.deepcopy(child), child_index, carrier_id=carrier_id, cached=cached,
            user_id=user_id, user_id_hash=user_id_hash, user_vault_key_id=user_vault_key_id,
            log_prefix=log_prefix,
        ))


def _card_summary(child: dict[str, Any]) -> dict[str, str]:
    return {"embed_id": child["id"], "kind": child["item"].kind,
            "title": child["content"]["title"], "embed_ref": child["content"]["embed_ref"]}


async def _publish_progress(
    service: Any, *, embed_id: str, cached: dict[str, Any], existing: dict[str, Any],
    source_json: str, user_id: str, user_id_hash: str, user_vault_key_id: str, log_prefix: str,
) -> bool:
    """Publish each newly complete valid card and the carrier's members so far."""
    limits = get_authored_results_limits()
    progress = carrier_progress(
        embed_id, cached["message_id"], source_byte_limit=limits["source_bytes"], item_limit=limits["items"],
    )
    if progress.last_snapshot is None:
        progress.last_snapshot = ((), 0, existing.get("title"))
    chat_id = cached["chat_id"]
    new_children: list[tuple[int, dict[str, Any]]] = []
    for entry in progress.envelope.feed_source(source_json or ""):
        if entry.item is not None:
            child = await _materialize_child(
                service, embed_id, entry.item, [], chat_id=chat_id, user_id_hash=user_id_hash,
                user_vault_key_id=user_vault_key_id, log_prefix=log_prefix,
            )
            if child is None:
                continue
            new_children.append((len(progress.cards) + len(new_children), child))
            progress.bind(entry.local_id, child["id"])
            continue
        card = await resolve_existing_card(
            service, entry.reference.embed_ref, index=getattr(service, "authoring_reference_index", None),
            chat_id=chat_id, user_id_hash=user_id_hash, user_vault_key_id=user_vault_key_id,
            log_prefix=log_prefix,
        )
        if card is not None and card.embed_id not in progress.bindings.values():
            progress.bind(entry.local_id, card.embed_id)
    now = int(datetime.now(timezone.utc).timestamp())
    if new_children:
        children = [child for _, child in new_children]
        _require_media_admission(service, children)
        async with service._defer_completed_embed_publications() as batch:
            for child_index, child in new_children:
                await _send_child(
                    service, child, child_index, carrier_id=embed_id, cached=cached,
                    restage=child["id"] in existing.get("embed_ids", []), user_id=user_id,
                    user_id_hash=user_id_hash, user_vault_key_id=user_vault_key_id,
                    log_prefix=log_prefix, now=now,
                )
            await service._flush_completed_embed_publications(batch)
        for child_index, child in new_children:
            summary = _card_summary(child)
            progress.cards.append(PublishedCard(
                child["id"], child["item"].local_id, summary["kind"], summary["title"],
                summary["embed_ref"], _content_hash(child["content"]),
            ))
            service._schedule_embed_persistence_fallback(child["id"])
        _schedule_geocoding(
            service, new_children, progress, carrier_id=embed_id, cached=cached, user_id=user_id,
            user_id_hash=user_id_hash, user_vault_key_id=user_vault_key_id, log_prefix=log_prefix,
        )
    members = progress.member_ids()
    pending = 1 if progress.envelope.pending else 0
    title = progress.envelope.parser.title or existing.get("title") or "Results"
    snapshot = (tuple(members), pending, title)
    if snapshot == progress.last_snapshot:
        return True
    progress.last_snapshot = snapshot
    version = int(existing.get("version_number") or 1)
    cards = [{"embed_id": card.child_id, "kind": card.kind, "title": card.title, "embed_ref": card.embed_ref}
             for card in progress.own_cards()]
    parent_content = _carrier_content(
        existing, title=title, status="processing", cards=cards, member_ids=members,
        view={"mode": "auto", "embeds": members}, source_json="", version=version,
        validation={"status": "processing", "warnings": []}, pending_count=pending,
    )
    toon = encode(parent_content)
    encrypted, _ = await service.encryption_service.encrypt_with_user_key(toon, user_vault_key_id)
    await service._cache_embed(embed_id, {
        **cached, "encrypted_content": encrypted, "status": "processing",
        "embed_ids": parent_content["embed_ids"], "updated_at": now,
    }, chat_id, user_id_hash, user_vault_key_id, user_id)
    await service.send_embed_data_to_client(
        embed_id=embed_id, embed_type=AUTHORED_RESULTS_TYPE, content_toon=toon,
        chat_id=chat_id, message_id=cached["message_id"], user_id=user_id,
        user_id_hash=user_id_hash, status="processing", embed_ids=parent_content["embed_ids"],
        app_id="ai", skill_id=AUTHORED_RESULTS_TYPE, version_number=version,
        is_private=cached.get("is_private", False), is_shared=cached.get("is_shared", False),
        created_at=cached.get("created_at"), updated_at=now, log_prefix=log_prefix,
        check_cache_status=False,
    )
    return True


def _interrupted_carrier(progress: CarrierProgress, existing: dict[str, Any]) -> dict[str, Any]:
    """Keep cards already published finished; the cut-off item never appears."""
    members = progress.member_ids()
    cards = [{"embed_id": card.child_id, "kind": card.kind, "title": card.title, "embed_ref": card.embed_ref}
             for card in progress.own_cards()]
    return _carrier_content(
        existing, title=progress.envelope.parser.title or existing.get("title") or "Results",
        status="finished", cards=cards, member_ids=members, view={"mode": "auto", "embeds": members},
        source_json="", version=int(existing.get("version_number") or 1),
        validation={"status": "partial", "warnings": [{"code": "interrupted", "path": "items"}],
                    "parse_error": "Content was interrupted"},
    )


async def update_authored_results_embed(
    service: Any, *, embed_id: str, source_json: str, chat_id: str,
    user_id: str, user_id_hash: str, user_vault_key_id: str,
    status: str = "finished", title: str | None = None,
    version_number: int | None = None, log_prefix: str = "",
) -> bool:
    """Publish cards as the block streams, then seal the finished carrier.

    ``processing`` updates publish each newly complete valid card at once and
    the carrier's members so far plus a pending count. The finished update
    produces exactly the closed-block result: cards already published with the
    same content are not sent again. Venue coordinates follow in the background.
    """
    cached = await service._get_cached_embed(embed_id, user_vault_key_id, log_prefix)
    if not isinstance(cached, dict) or cached.get("type") != AUTHORED_RESULTS_TYPE:
        return False
    if cached.get("hashed_user_id") != user_id_hash or cached.get("chat_id") != chat_id:
        return False
    existing_toon = await service._get_cached_embed_toon(embed_id, user_vault_key_id, log_prefix)
    existing = decode(existing_toon) if existing_toon else {}
    if not isinstance(existing, dict):
        return False
    # A later cancellation must not invalidate an already completed independent
    # artifact. Partial source is never published as a finished record.
    if cached.get("status") == "finished" and status != "finished":
        finish_progress(embed_id)
        return True
    if status == "processing":
        return await _publish_progress(
            service, embed_id=embed_id, cached=cached, existing=existing, source_json=source_json,
            user_id=user_id, user_id_hash=user_id_hash, user_vault_key_id=user_vault_key_id,
            log_prefix=log_prefix,
        )
    progress = existing_progress(embed_id)
    finish_progress(embed_id)
    interrupted = status != "finished" and progress is not None and bool(progress.member_ids())
    normalized = normalize_authored_results_source(source_json) if status == "finished" else None
    source_hash = hashlib.sha256((normalized.source_json if normalized else "").encode()).hexdigest()
    if (status == "finished" and cached.get("status") == "finished"
            and cached.get("content_hash") == source_hash and version_number is None):
        return True
    now = int(datetime.now(timezone.utc).timestamp())
    warnings = list(normalized.warnings) if normalized else []
    children: list[dict[str, Any]] = []
    bindings: dict[str, str] = {}
    for item in (normalized.items if normalized else []):
        child = await _materialize_child(
            service, embed_id, item, warnings, chat_id=chat_id, user_id_hash=user_id_hash,
            user_vault_key_id=user_vault_key_id, log_prefix=log_prefix,
        )
        if child is None:
            continue
        published = progress.card(child["id"]) if progress is not None else None
        # A card streamed earlier with identical content is not sent again; a
        # coordinate update that already landed therefore stays in place.
        child["published"] = published is not None and published.content_hash == _content_hash(child["content"])
        bindings[item.local_id] = child["id"]
        children.append(child)
    member_titles: list[str] = []
    for reference in (normalized.references if normalized else []):
        # A reused card stays a child of its original carrier with its own key;
        # this carrier only lists it as a member. Never resolve a guessed id.
        card = await resolve_existing_card(
            service, reference.embed_ref, index=getattr(service, "authoring_reference_index", None),
            chat_id=chat_id, user_id_hash=user_id_hash, user_vault_key_id=user_vault_key_id,
            log_prefix=log_prefix,
        )
        if card is None:
            warnings.append({"code": "unavailable_existing_card", "path": f"items[{reference.index}]"})
            continue
        if card.embed_id in bindings.values():
            warnings.append({"code": "duplicate_existing_card", "path": f"items[{reference.index}]"})
            continue
        bindings[reference.local_id] = card.embed_id
        member_titles.append(card.title)
    ordered_labels = [label for label in (normalized.order if normalized else []) if label in bindings]
    member_ids = [bindings[label] for label in ordered_labels]
    next_status = "finished" if member_ids else "error"
    requested = normalized.view if normalized else None
    requested_ids = requested.get("items", ordered_labels) if requested else ordered_labels
    view = {
        "mode": requested.get("mode", "auto") if requested else "auto",
        "embeds": [bindings[label] for label in requested_ids if label in bindings],
    }
    version = version_number or int(existing.get("version_number") or 1)
    parent_content = _carrier_content(
        existing,
        title=(title or (normalized.title if normalized else None) or next(iter(member_titles), None)
               or existing.get("title") or "Results"),
        status=next_status, cards=[_card_summary(child) for child in children], member_ids=member_ids,
        view=view, source_json=normalized.source_json if normalized else "", version=version,
        validation={"status": ("partial" if warnings else "valid") if member_ids else "invalid_source",
                    "warnings": warnings,
                    "parse_error": normalized.parse_error if normalized else "Content was interrupted"},
    )
    if interrupted:
        parent_content = _interrupted_carrier(progress, existing)
    try:
        _require_media_admission(service, children)
        async with service._defer_completed_embed_publications() as batch:
            for child_index, child in enumerate(children):
                if child["published"]:
                    continue
                await _send_child(
                    service, child, child_index, carrier_id=embed_id, cached=cached,
                    restage=child["id"] in existing.get("embed_ids", []), user_id=user_id,
                    user_id_hash=user_id_hash, user_vault_key_id=user_vault_key_id,
                    log_prefix=log_prefix, now=now,
                )
            await _send_finished_carrier(
                service, parent_content, embed_id=embed_id, cached=cached, source_hash=source_hash,
                user_id=user_id, user_id_hash=user_id_hash, user_vault_key_id=user_vault_key_id,
                log_prefix=log_prefix, now=now,
            )
            await service._flush_completed_embed_publications(batch)
        for child in children:
            if not child["published"]:
                service._schedule_embed_persistence_fallback(child["id"])
        service._schedule_embed_persistence_fallback(embed_id)
        _schedule_geocoding(
            service, list(enumerate(children)), progress, carrier_id=embed_id, cached=cached,
            user_id=user_id, user_id_hash=user_id_hash, user_vault_key_id=user_vault_key_id,
            log_prefix=log_prefix,
        )
        return True
    except RequiredRecoveryOutputError:
        raise
    except Exception:
        logger.exception("%s Authored result materialization failed for carrier %s", log_prefix, embed_id)
        return False


async def _carrier_member_ids(
    service: Any, carrier_id: str, own_ids: list[str], *, user_vault_key_id: str, log_prefix: str,
) -> list[str]:
    """Order own children and reused members as the carrier lists them.

    ``member_ids`` lives in the encrypted carrier content; a carrier without it
    (older or client-only ciphertext) contributes only its own children.
    """
    toon = await service._get_cached_embed_toon(carrier_id, user_vault_key_id, log_prefix)
    content = decode(toon) if toon else None
    listed = content.get("member_ids") if isinstance(content, dict) else None
    members = [value for value in listed if isinstance(value, str)] if isinstance(listed, list) else []
    return list(dict.fromkeys([*members, *own_ids]))[:MAX_AUTHORED_CHILDREN]


async def authored_children_for_context(
    service: Any, carrier_id: str, *, user_vault_key_id: str, log_prefix: str = "",
) -> list[tuple[str, str]]:
    """Expand bounded, matching children and reused members of an authorized carrier.

    Own children must name this carrier as parent. A reused member stays the
    child of its original carrier, so the parent check does not apply to it; the
    owner, chat, finished-status and admitted-kind checks apply to both.
    """
    parent = await service._get_cached_embed(carrier_id, user_vault_key_id, log_prefix)
    if not isinstance(parent, dict) or parent.get("type") != AUTHORED_RESULTS_TYPE:
        return []
    if not isinstance(parent.get("hashed_user_id"), str) or not parent["hashed_user_id"]:
        return []
    if not parent.get("chat_id") and not parent.get("hashed_chat_id"):
        return []
    result = []
    ids = parent.get("embed_ids")
    if not isinstance(ids, list):
        return []
    own_ids = list(dict.fromkeys(i for i in ids if isinstance(i, str)))[:MAX_AUTHORED_CHILDREN]
    ordered = await _carrier_member_ids(
        service, carrier_id, own_ids, user_vault_key_id=user_vault_key_id, log_prefix=log_prefix,
    )
    for child_id in ordered:
        child = await service._get_cached_embed(child_id, user_vault_key_id, log_prefix)
        if (not isinstance(child, dict)
                or (child_id in own_ids and child.get("parent_embed_id") != carrier_id)
                or child.get("hashed_user_id") != parent.get("hashed_user_id")
                or child.get("chat_id") != parent.get("chat_id") or child.get("status") != "finished"):
            continue
        if parent.get("hashed_chat_id") and child.get("hashed_chat_id") != parent["hashed_chat_id"]:
            continue
        if child_id not in own_ids and not (
                isinstance(child.get("parent_embed_id"), str) and child["parent_embed_id"]):
            # Only authored cards (children of some carrier) can be reused members.
            continue
        toon = await service._get_cached_embed_toon(child_id, user_vault_key_id, log_prefix)
        if toon and authored_card_kind(child, decode(toon)) is not None:
            result.append((child_id, toon))
    return result
