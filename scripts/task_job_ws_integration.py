"""Disposable authenticated Task-job WebSocket fixture for isolated CI only."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import secrets
import sys
import time
import uuid
from types import SimpleNamespace

from scripts.storage_archive_integration import require_isolated_storage


def _guard() -> None:
    require_isolated_storage()
    if os.getenv("OPENMATES_CI_ARCHIVE_LIFECYCLE_PROBE") != "1" or not re.fullmatch(
        r"[0-9a-f]{40}", os.getenv("BUILD_COMMIT_SHA", "")
    ):
        raise RuntimeError("Task-job WebSocket probe requires pinned isolated lifecycle source")


def _cipher() -> str:
    return base64.b64encode(secrets.token_bytes(96)).decode()


def _identities() -> dict[str, str]:
    raw = sys.stdin.read(4097)
    if len(raw) > 4096:
        raise RuntimeError("Task-job fixture identity exceeds input budget")
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {"user_id", "chat_id", "task_id", "job_id", "session_hash"}:
        raise RuntimeError("Task-job fixture identity is invalid")
    if not all(isinstance(data[key], str) and str(uuid.UUID(data[key])) == data[key]
               for key in ("user_id", "chat_id", "task_id", "job_id")):
        raise RuntimeError("Task-job fixture identity is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", data["session_hash"]):
        raise RuntimeError("Task-job fixture identity is invalid")
    return data


async def _prepare(directus, cache) -> dict:
    from backend.apps.ai.processing.task_tool_executor import TASK_TOOL_JOB_CACHE_PREFIX
    from backend.core.api.app.utils.device_fingerprint import generate_device_fingerprint_hash
    from backend.core.api.app.utils.ws_token import create_ws_token
    from backend.core.api.app.services.session_security_state import register_session_state

    now = int(time.time())
    user_id, chat_id, task_id, job_id = (str(uuid.uuid4()) for _ in range(4))
    session_id = str(uuid.uuid4())
    refresh_token = secrets.token_urlsafe(48)
    session_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    owner_hash = hashlib.sha256(user_id.encode()).hexdigest()
    user_agent = "OpenMates CLI/0.1 (Linux)"
    request = SimpleNamespace(headers={"User-Agent": user_agent}, client=SimpleNamespace(host="127.0.0.1"))
    device_hash, connection_hash, *_ = generate_device_fingerprint_hash(request, user_id, session_id)
    if not connection_hash:
        raise RuntimeError("Task-job fixture device binding unavailable")
    token = await directus.ensure_auth_token(admin_required=True)
    if not token:
        raise RuntimeError("Task-job fixture admin token unavailable")
    user_payload = {
        "id": user_id, "email": f"{owner_hash}@example.com",
        "password": secrets.token_urlsafe(32), "status": "active",
        "hashed_email": owner_hash,
    }
    response = await directus._make_api_request(
        "POST", f"{directus.base_url.rstrip('/')}/users",
        headers={"Authorization": f"Bearer {token}"}, json=user_payload,
    )
    if response.status_code not in {200, 201}:
        raise RuntimeError("Task-job disposable user creation failed")
    try:
        profile = {"id": user_id, "user_id": user_id, "connected_devices": [device_hash]}
        if not await cache.set_user(profile, refresh_token=refresh_token, ttl=900):
            raise RuntimeError("Task-job fixture session cache creation failed")
        await register_session_state(directus, cache, refresh_token, user_id, ttl_seconds=900)
        created, _ = await directus.create_item("chats", {
            "id": chat_id, "hashed_user_id": owner_hash,
            "encrypted_title": _cipher(), "encrypted_chat_key": _cipher(),
            "messages_v": 0, "title_v": 1, "created_at": now, "updated_at": now,
        }, admin_required=True)
        if not created:
            raise RuntimeError("Task-job fixture chat creation failed")
        lease_token = secrets.token_urlsafe(32)
        job = {
            "job_id": job_id, "owner_hash": owner_hash, "task_id": task_id,
            "chat_id": chat_id, "state": "LEASED", "operation": "create",
            "expected_task_version": 0, "lease_token": lease_token,
            "lease_generation": 1, "lease_device_hash": connection_hash,
            "lease_expires_at": now + 600, "expires_at": now + 900,
        }
        if not await cache.set(f"{TASK_TOOL_JOB_CACHE_PREFIX}{job_id}", job, ttl=900):
            raise RuntimeError("Task-job fixture lease creation failed")
        encrypted_payload = {
            "encrypted_title": _cipher(), "encrypted_description": _cipher(),
            "encrypted_slug": _cipher(),
            "slug_lookup_hash": hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
            "encrypted_task_key": _cipher(),
            "status": "todo", "assignee_type": "user", "assignee_hash": owner_hash,
            "primary_chat_id": chat_id, "version": 1,
            "created_at": now, "updated_at": now,
        }
        ws_token = create_ws_token(refresh_token)
        if not ws_token:
            raise RuntimeError("Task-job fixture WebSocket token unavailable")
        return {
            "user_id": user_id, "chat_id": chat_id, "task_id": task_id,
            "job_id": job_id, "session_hash": session_hash,
            "session_id": session_id, "ws_token": ws_token,
            "lease_token": lease_token, "user_agent": user_agent,
            "encrypted_task_payload": encrypted_payload,
        }
    except BaseException:
        await _cleanup(directus, cache, {
            "user_id": user_id, "chat_id": chat_id, "task_id": task_id,
            "job_id": job_id, "session_hash": session_hash,
        })
        raise


async def _verify(directus, cache, identity: dict) -> dict:
    from backend.apps.ai.processing.task_tool_executor import TASK_TOOL_JOB_CACHE_PREFIX
    task_id, job_id = identity["task_id"], identity["job_id"]
    rows = await directus.get_items("user_tasks", params={
        "filter": {"task_id": {"_eq": task_id}},
        "fields": "task_id,hashed_user_id,primary_chat_id,encrypted_title,encrypted_description,encrypted_slug,slug_lookup_hash,version",
        "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    job = await cache.get(f"{TASK_TOOL_JOB_CACHE_PREFIX}{job_id}")
    if len(rows) != 1 or not isinstance(job, dict) or job.get("state") != "TASK_PERSISTED":
        raise RuntimeError("Task-job WebSocket did not persist a durable Task")
    payload = job.get("client_encrypted_payload")
    if not isinstance(payload, dict):
        raise RuntimeError("Task-job WebSocket lost encrypted payload")
    row = rows[0]
    owner_hash = hashlib.sha256(identity["user_id"].encode()).hexdigest()
    expected = ("encrypted_title", "encrypted_description", "encrypted_slug", "slug_lookup_hash")
    if any(row.get(key) != payload.get(key) for key in expected) or any(
        key in payload for key in ("plaintext_title", "plaintext_description")
    ) or row.get("hashed_user_id") != owner_hash or row.get("primary_chat_id") != identity["chat_id"]:
        raise RuntimeError("Task-job durable ciphertext, hash, or owner mismatch")
    return {"passed": True, "task_job_ws_persisted_slug_hash": True,
            "source_commit": os.environ["BUILD_COMMIT_SHA"]}


async def _cleanup(directus, cache, identity: dict) -> dict:
    from backend.apps.ai.processing.task_tool_executor import TASK_TOOL_JOB_CACHE_PREFIX
    failures: list[str] = []
    rows = await directus.get_items("user_tasks", params={
        "filter": {"task_id": {"_eq": identity["task_id"]}}, "fields": "id", "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    for row in rows:
        if not await directus.delete_item("user_tasks", row["id"], admin_required=True):
            failures.append("task")
    if not await directus.delete_item("chats", identity["chat_id"], admin_required=True):
        existing = await directus.get_items("chats", params={"filter": {"id": {"_eq": identity["chat_id"]}}, "limit": 1}, admin_required=True, no_cache=True)
        if existing:
            failures.append("chat")
    states = await directus.get_items("session_security_states", params={
        "filter": {"token_hash": {"_eq": identity["session_hash"]}}, "fields": "id", "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    for row in states:
        if not await directus.delete_item("session_security_states", row["id"], admin_required=True):
            failures.append("session")
    token = await directus.ensure_auth_token(admin_required=True)
    response = await directus._make_api_request(
        "DELETE", f"{directus.base_url.rstrip('/')}/users/{identity['user_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.status_code not in {200, 204, 404}:
        failures.append("user")
    for key in (
        f"{TASK_TOOL_JOB_CACHE_PREFIX}{identity['job_id']}",
        f"session:{identity['session_hash']}",
        f"user_profile:{identity['user_id']}",
        f"user_tokens:{identity['user_id']}",
    ):
        await cache.delete(key)
    if failures:
        raise RuntimeError("Task-job fixture cleanup failed: " + ",".join(failures))
    return {"passed": True, "task_job_fixture_cleanup_verified": True}


async def _run(mode: str) -> dict:
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus import DirectusService
    _guard()
    directus, cache = DirectusService(), CacheService()
    try:
        if mode == "prepare":
            return await _prepare(directus, cache)
        identity = _identities()
        if mode == "verify":
            return await _verify(directus, cache, identity)
        if mode == "cleanup":
            return await _cleanup(directus, cache, identity)
        raise RuntimeError("Unsupported Task-job WebSocket fixture mode")
    finally:
        await cache.close()
        await directus.close()


def main() -> None:
    mode = os.environ.get("OPENMATES_CI_TASK_JOB_WS_PROBE", "")
    print(json.dumps(asyncio.run(_run(mode)), sort_keys=True))
