# backend/core/api/app/services/push_subscription_targets.py
#
# Pure helpers for serializing OpenMates push notification targets.
# Browser Web Push and native APNs registrations share one persisted user field,
# so these utilities preserve all devices while remaining readable from tests
# without importing FastAPI route dependencies.

import hashlib
import json
from typing import Any, Optional


MULTI_PUSH_SUBSCRIPTION_TYPE = "multi"


def normalize_push_subscription_targets(subscription_json: Optional[str]) -> list[dict[str, Any]]:
    """Return push targets from legacy single-target or v1 multi-target storage."""
    if not subscription_json:
        return []
    try:
        subscription = json.loads(subscription_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(subscription, dict):
        return []

    if subscription.get("type") == MULTI_PUSH_SUBSCRIPTION_TYPE:
        targets = subscription.get("targets")
        if not isinstance(targets, list):
            return []
        return [target for target in targets if isinstance(target, dict) and push_target_id(target)]

    if push_target_id(subscription):
        target = dict(subscription)
        if not target.get("type"):
            target["type"] = "web"
        return [target]
    return []


def merge_push_subscription_target(existing_subscription_json: Optional[str], target: dict[str, Any]) -> str:
    """Merge or replace one browser/APNs target without dropping other devices."""
    target_id = push_target_id(target)
    if not target_id:
        raise ValueError("Push subscription target is missing a stable identifier")

    targets = [
        existing
        for existing in normalize_push_subscription_targets(existing_subscription_json)
        if push_target_id(existing) != target_id
    ]
    targets.append(target)
    return json.dumps(
        {"type": MULTI_PUSH_SUBSCRIPTION_TYPE, "targets": targets},
        separators=(",", ":"),
    )


def remove_push_subscription_targets(existing_subscription_json: Optional[str], target_type: str) -> tuple[str | None, bool]:
    """Remove targets of a type and return serialized storage plus enabled flag."""
    targets = [
        target
        for target in normalize_push_subscription_targets(existing_subscription_json)
        if target.get("type", "web") != target_type
    ]
    if not targets:
        return None, False
    return (
        json.dumps({"type": MULTI_PUSH_SUBSCRIPTION_TYPE, "targets": targets}, separators=(",", ":")),
        True,
    )


def push_target_id(target: dict[str, Any]) -> Optional[str]:
    target_type = target.get("type", "web")
    if target_type == "apns":
        token = str(target.get("token") or "").strip()
        if token:
            return "apns:" + hashlib.sha256(token.encode()).hexdigest()
        return None
    endpoint = str(target.get("endpoint") or "").strip()
    if endpoint:
        return "web:" + hashlib.sha256(endpoint.encode()).hexdigest()
    return None
