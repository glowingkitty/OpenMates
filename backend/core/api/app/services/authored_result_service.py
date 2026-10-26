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
    get_authored_results_schema,
    get_authoring_definitions,
    normalize_authored_results_source,
)
from backend.shared.python_utils.chat_recovery_context import RequiredRecoveryOutputError

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


async def update_authored_results_embed(
    service: Any, *, embed_id: str, source_json: str, chat_id: str,
    user_id: str, user_id_hash: str, user_vault_key_id: str,
    status: str = "finished", title: str | None = None,
    version_number: int | None = None, log_prefix: str = "",
) -> bool:
    """Seal typed children and their carrier before publishing completed content."""
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
        return True
    if status == "processing":
        return True
    normalized = normalize_authored_results_source(source_json) if status == "finished" else None
    source_hash = hashlib.sha256((normalized.source_json if normalized else "").encode()).hexdigest()
    if (status == "finished" and cached.get("status") == "finished"
            and cached.get("content_hash") == source_hash and version_number is None):
        return True
    now = int(datetime.now(timezone.utc).timestamp())
    warnings = list(normalized.warnings) if normalized else []
    children: list[dict[str, Any]] = []
    bindings: dict[str, str] = {}
    definitions = get_authoring_definitions()
    for item in (normalized.items if normalized else []):
        content, reference_warnings = await _resolve_record_references(
            service, item.content, chat_id=chat_id, user_id_hash=user_id_hash,
            user_vault_key_id=user_vault_key_id, log_prefix=log_prefix,
        )
        warnings.extend(reference_warnings)
        # A resource-only image reference cannot become a real asset when its
        # source failed authorization. Other informational cards remain usable.
        if (definitions[item.kind].get("real_asset")
                and not _has_resolved_resource(item.kind, content)):
            warnings.append({"code": "unavailable_resource", "path": "items"})
            continue
        child_id = authored_child_id(embed_id, item.local_id)
        content.update({
            "type": item.backend_type, "app_id": item.app_id, "skill_id": item.skill_id,
            "embed_ref": service._generate_direct_embed_ref(item.backend_type, child_id, content),
            "status": "finished",
        })
        bindings[item.local_id] = child_id
        children.append({"id": child_id, "item": item, "content": content})
    child_ids = [child["id"] for child in children]
    next_status = "finished" if children else "error"
    requested = normalized.view if normalized else None
    requested_ids = requested.get("items", list(bindings)) if requested else list(bindings)
    view = {
        "mode": requested.get("mode", "auto") if requested else "auto",
        "embeds": [bindings[label] for label in requested_ids if label in bindings],
    }
    version = version_number or int(existing.get("version_number") or 1)
    parent_content = {
        "type": AUTHORED_RESULTS_TYPE, "app_id": "ai", "skill_id": AUTHORED_RESULTS_TYPE,
        "schema_version": 1, "title": title or (normalized.title if normalized else None) or existing.get("title") or "Results",
        "status": next_status, "embed_ids": child_ids,
        "items": [{"embed_id": child["id"], "kind": child["item"].kind,
                   "title": child["content"]["title"], "embed_ref": child["content"]["embed_ref"]}
                  for child in children],
        "view": view, "source_json": normalized.source_json if normalized else "",
        "embed_ref": existing.get("embed_ref"), "version_number": version,
        "validation": {"status": ("partial" if warnings else "valid") if children else "invalid_source",
                       "warnings": warnings,
                       "parse_error": normalized.parse_error if normalized else "Content was interrupted"},
    }
    try:
        async with service._defer_completed_embed_publications() as batch:
            for child_index, child in enumerate(children):
                item = child["item"]
                toon = encode(child["content"])
                encrypted, _ = await service.encryption_service.encrypt_with_user_key(toon, user_vault_key_id)
                child_data = {
                    "embed_id": child["id"], "type": item.backend_type,
                    "chat_id": chat_id, "message_id": cached["message_id"],
                    "hashed_chat_id": cached["hashed_chat_id"], "hashed_message_id": cached["hashed_message_id"],
                    "hashed_task_id": cached.get("hashed_task_id"), "hashed_user_id": user_id_hash,
                    "parent_embed_id": embed_id, "status": "finished", "encryption_mode": "client",
                    "is_private": cached.get("is_private", False), "is_shared": False,
                    "encrypted_content": encrypted, "text_length_chars": len(toon),
                    "created_at": now, "updated_at": now,
                }
                sent = await service.send_embed_data_to_client(
                    embed_id=child["id"], embed_type=item.backend_type, content_toon=toon,
                    chat_id=chat_id, message_id=cached["message_id"], user_id=user_id,
                    user_id_hash=user_id_hash, status="finished", parent_embed_id=embed_id,
                    text_length_chars=len(toon), created_at=now, updated_at=now,
                    is_private=cached.get("is_private", False), is_shared=False,
                    app_id=item.app_id, skill_id=item.skill_id, log_prefix=log_prefix,
                    check_cache_status=False, producer_child_index=child_index,
                    finished_cache_data=child_data, finished_cache_vault_key_id=user_vault_key_id,
                )
                if not sent:
                    raise RequiredRecoveryOutputError("Authored child delivery failed")
            toon = encode(parent_content)
            encrypted, _ = await service.encryption_service.encrypt_with_user_key(toon, user_vault_key_id)
            parent_data = {
                **cached, "type": AUTHORED_RESULTS_TYPE, "encrypted_content": encrypted,
                "status": next_status, "embed_ids": child_ids, "version_number": version,
                "content_hash": source_hash, "updated_at": now,
            }
            sent = await service.send_embed_data_to_client(
                embed_id=embed_id, embed_type=AUTHORED_RESULTS_TYPE, content_toon=toon,
                chat_id=chat_id, message_id=cached["message_id"], user_id=user_id,
                user_id_hash=user_id_hash, status=next_status, embed_ids=child_ids,
                version_number=version, content_hash=source_hash,
                is_private=cached.get("is_private", False), is_shared=cached.get("is_shared", False),
                created_at=cached.get("created_at"), updated_at=now, log_prefix=log_prefix,
                check_cache_status=False, finished_cache_data=parent_data,
                finished_cache_vault_key_id=user_vault_key_id,
            )
            if not sent:
                raise RequiredRecoveryOutputError("Authored carrier delivery failed")
            await service._flush_completed_embed_publications(batch)
        for record_id in [*child_ids, embed_id]:
            service._schedule_embed_persistence_fallback(record_id)
        return True
    except RequiredRecoveryOutputError:
        raise
    except Exception:
        logger.exception("%s Authored result materialization failed for carrier %s", log_prefix, embed_id)
        return False


async def authored_children_for_context(
    service: Any, carrier_id: str, *, user_vault_key_id: str, log_prefix: str = "",
) -> list[tuple[str, str]]:
    """Expand only bounded, matching direct children of an authorized carrier."""
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
    for child_id in list(dict.fromkeys(i for i in ids if isinstance(i, str)))[:MAX_AUTHORED_CHILDREN]:
        child = await service._get_cached_embed(child_id, user_vault_key_id, log_prefix)
        if (not isinstance(child, dict) or child.get("parent_embed_id") != carrier_id
                or child.get("hashed_user_id") != parent.get("hashed_user_id")
                or child.get("chat_id") != parent.get("chat_id") or child.get("status") != "finished"):
            continue
        if parent.get("hashed_chat_id") and child.get("hashed_chat_id") != parent["hashed_chat_id"]:
            continue
        toon = await service._get_cached_embed_toon(child_id, user_vault_key_id, log_prefix)
        if toon:
            decoded = decode(toon)
            authored = decoded.get("authoring", {}) if isinstance(decoded, dict) else {}
            definition = get_authoring_definitions().get(authored.get("kind")) if isinstance(authored, dict) else None
            if (definition and definition["backend_type"] == child.get("type")
                    and decoded.get("type") == child.get("type")
                    and definition["app_id"] == decoded.get("app_id")
                    and definition["skill_id"] == decoded.get("skill_id")):
                result.append((child_id, toon))
    return result
