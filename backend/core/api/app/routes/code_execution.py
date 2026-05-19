# backend/core/api/app/routes/code_execution.py
#
# Web-app route for running Code embeds in isolated E2B sandboxes.
# The browser sends the current chat and target embed; the backend collects the
# chat's server-cached code embeds, normalizes them to files, starts a Celery
# execution task, and exposes a small polling endpoint for the terminal panel.

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from pathlib import PurePosixPath
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from toon_format import decode as toon_decode

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.routes.auth_ws import get_current_user_ws
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.tasks.celery_config import app as celery_app


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/code/run", tags=["Code Run"])

MAX_FILES = 50
MAX_FILE_CHARS = 1_000_000
MAX_TOTAL_CHARS = 10_000_000
EXECUTION_TTL_SECONDS = 3600
RUN_CREDITS_PER_MINUTE = 10
ACTIVE_RUN_TTL_SECONDS = 600
MAX_ACTIVE_RUNS_PER_USER = 5
CODE_RUN_CHANNEL_PREFIX = "code_run_stream"
EXECUTABLE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".sh": "bash",
}
EXECUTABLE_LANGUAGES = {
    "python",
    "py",
    "javascript",
    "js",
    "node",
    "typescript",
    "ts",
    "bash",
    "sh",
    "shell",
}
DEPENDENCY_FILENAMES = {"requirements.txt", "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[oprsu]_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*=\s*[^\s]+"),
]


class CodeRunStartRequest(BaseModel):
    chat_id: str = Field(min_length=1)
    target_embed_id: str = Field(min_length=1)


class CodeRunStartResponse(BaseModel):
    execution_id: str
    status: str
    target_filename: str
    files: list[str]
    credits_per_minute: int = 10


def get_cache_service(request: Request) -> CacheService:
    return request.app.state.cache_service


def get_directus_service(request: Request) -> DirectusService:
    return request.app.state.directus_service


def get_encryption_service(request: Request) -> EncryptionService:
    return request.app.state.encryption_service


def _execution_key(execution_id: str) -> str:
    return f"code_run_execution:{execution_id}"


def _active_run_key(user_id_hash: str) -> str:
    return f"code_run_active:{user_id_hash}"


def _stream_channel(execution_id: str) -> str:
    return f"{CODE_RUN_CHANNEL_PREFIX}:{execution_id}"


def _looks_like_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in SECRET_PATTERNS)


def _safe_filename(raw_filename: str | None, embed_id: str, language: str) -> str:
    filename = (raw_filename or "").strip().replace("\\", "/")
    if not filename:
        ext = {
            "python": ".py",
            "py": ".py",
            "javascript": ".js",
            "js": ".js",
            "typescript": ".ts",
            "ts": ".ts",
            "bash": ".sh",
            "sh": ".sh",
            "shell": ".sh",
        }.get((language or "").lower(), ".txt")
        filename = f"snippet-{embed_id[:8]}{ext}"

    parts = [part for part in PurePosixPath(filename).parts if part not in ("", ".", "..")]
    cleaned = "/".join(re.sub(r"[^A-Za-z0-9._/-]", "_", part) for part in parts)
    return cleaned or f"snippet-{embed_id[:8]}.txt"


def _dedupe_path(path: str, used: set[str]) -> str:
    if path not in used:
        used.add(path)
        return path
    stem, dot, suffix = path.rpartition(".")
    base = stem if dot else path
    ext = f".{suffix}" if dot else ""
    counter = 2
    while True:
        candidate = f"{base}-{counter}{ext}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        counter += 1


async def _decrypt_embed_content(embed: dict[str, Any], encryption_service: EncryptionService, vault_key_id: str) -> dict[str, Any] | None:
    encrypted_content = embed.get("encrypted_content")
    if not encrypted_content:
        return None
    plaintext = await encryption_service.decrypt_with_user_key(encrypted_content, vault_key_id)
    if not plaintext:
        return None
    try:
        decoded = toon_decode(plaintext)
    except Exception:
        return None
    return decoded if isinstance(decoded, dict) else None


async def _get_embed_with_fallback(embed_id: str, cache_service: CacheService, directus_service: DirectusService) -> dict[str, Any] | None:
    cached = await cache_service.get_embed_from_cache(embed_id)
    if cached:
        return cached
    return await directus_service.embed.get_embed_by_id(embed_id)


async def _collect_code_files(
    chat_id: str,
    target_embed_id: str,
    current_user: User,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
) -> tuple[list[dict[str, Any]], str]:
    embed_ids = await cache_service.get_chat_embed_ids(chat_id)
    if target_embed_id not in embed_ids:
        embed_ids.append(target_embed_id)

    if len(embed_ids) > MAX_FILES:
        embed_ids = embed_ids[:MAX_FILES]

    used_paths: set[str] = set()
    files: list[dict[str, Any]] = []
    target_path: str | None = None
    total_chars = 0
    expected_user_hash = hashlib.sha256(current_user.id.encode()).hexdigest()

    for embed_id in embed_ids:
        embed = await _get_embed_with_fallback(embed_id, cache_service, directus_service)
        if not embed:
            continue
        if embed.get("hashed_user_id") and embed.get("hashed_user_id") != expected_user_hash:
            continue
        content = await _decrypt_embed_content(embed, encryption_service, current_user.vault_key_id)
        if not content:
            continue
        embed_type = str(content.get("type") or embed.get("type") or "").lower()
        if embed_type not in {"code", "code-code"}:
            continue
        code = content.get("code")
        if not isinstance(code, str) or not code:
            continue
        if _looks_like_secret(code):
            raise HTTPException(status_code=400, detail="Code appears to contain secrets and cannot be sent to the sandbox")
        if len(code) > MAX_FILE_CHARS:
            raise HTTPException(status_code=400, detail="One code file is too large to run")
        total_chars += len(code)
        if total_chars > MAX_TOTAL_CHARS:
            raise HTTPException(status_code=400, detail="Chat code files are too large to run together")

        language = str(content.get("language") or "").lower()
        path = _dedupe_path(_safe_filename(content.get("filename"), embed_id, language), used_paths)
        is_dependency = path.rsplit("/", 1)[-1] in DEPENDENCY_FILENAMES
        is_executable = language in EXECUTABLE_LANGUAGES or PurePosixPath(path).suffix.lower() in EXECUTABLE_EXTENSIONS
        if not is_dependency and not is_executable and embed_id != target_embed_id:
            continue
        file_item = {"path": path, "content": code, "language": language, "is_target": embed_id == target_embed_id}
        files.append(file_item)
        if embed_id == target_embed_id:
            target_path = path

    if not target_path:
        raise HTTPException(status_code=404, detail="Target code embed is not available for server-side execution")
    return files, target_path


async def _create_execution_record(cache_service: CacheService, execution_id: str, data: dict[str, Any]) -> None:
    client = await cache_service.client
    await client.set(_execution_key(execution_id), json.dumps(data), ex=EXECUTION_TTL_SECONDS)


async def _try_add_active_run(client: Any, active_key: str, execution_id: str) -> bool:
    script = """
local active_key = KEYS[1]
local execution_id = ARGV[1]
local max_runs = tonumber(ARGV[2])
local ttl_seconds = tonumber(ARGV[3])
if redis.call('SCARD', active_key) >= max_runs then
    return 0
end
redis.call('SADD', active_key, execution_id)
redis.call('EXPIRE', active_key, ttl_seconds)
return 1
"""
    result = await client.eval(script, 1, active_key, execution_id, MAX_ACTIVE_RUNS_PER_USER, ACTIVE_RUN_TTL_SECONDS)
    return int(result) == 1


@router.post("", response_model=CodeRunStartResponse)
async def start_code_run(
    body: CodeRunStartRequest,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
) -> CodeRunStartResponse:
    if current_user.credits < RUN_CREDITS_PER_MINUTE:
        raise HTTPException(status_code=402, detail="Not enough credits to run code")

    files, target_path = await _collect_code_files(
        body.chat_id,
        body.target_embed_id,
        current_user,
        cache_service,
        directus_service,
        encryption_service,
    )
    user_id_hash = hashlib.sha256(current_user.id.encode()).hexdigest()
    client = await cache_service.client
    active_key = _active_run_key(user_id_hash)
    execution_id = str(uuid.uuid4())
    run_slot_created = await _try_add_active_run(client, active_key, execution_id)
    if not run_slot_created:
        raise HTTPException(status_code=429, detail="Too many code runs are already active for this user")

    now = time.time()
    record = {
        "execution_id": execution_id,
        "user_id_hash": user_id_hash,
        "status": "queued",
        "target_embed_id": body.target_embed_id,
        "target_filename": target_path,
        "files": [file["path"] for file in files],
        "events": [{"kind": "status", "text": "Queued code run...\n", "timestamp": now}],
        "created_at": now,
        "updated_at": now,
    }
    payload = {
        "user_id": current_user.id,
        "user_id_hash": user_id_hash,
        "chat_id": body.chat_id,
        "target_embed_id": body.target_embed_id,
        "target_path": target_path,
        "files": files,
        "active_run_key": active_key,
        "active_run_owner": execution_id,
    }
    try:
        await _create_execution_record(cache_service, execution_id, record)
        celery_app.send_task("code.run_execution", args=[execution_id, payload], queue="app_code")
    except Exception:
        await client.srem(active_key, execution_id)
        raise
    return CodeRunStartResponse(
        execution_id=execution_id,
        status="queued",
        target_filename=target_path,
        files=[file["path"] for file in files],
    )


@router.get("/{execution_id}")
async def get_code_run_status(
    execution_id: str,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
) -> dict[str, Any]:
    client = await cache_service.client
    raw = await client.get(_execution_key(execution_id))
    if not raw:
        raise HTTPException(status_code=404, detail="Code run not found or expired")
    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    expected_user_hash = hashlib.sha256(current_user.id.encode()).hexdigest()
    if data.get("user_id_hash") != expected_user_hash:
        raise HTTPException(status_code=404, detail="Code run not found or expired")
    return data


@router.websocket("/{execution_id}/stream")
async def stream_code_run_status(
    websocket: WebSocket,
    execution_id: str,
    auth_data: dict | None = Depends(get_current_user_ws),
) -> None:
    if auth_data is None:
        return

    cache_service: CacheService = websocket.app.state.cache_service
    client = await cache_service.client
    raw = await client.get(_execution_key(execution_id))
    if not raw:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Code run not found")
        return

    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    expected_user_hash = hashlib.sha256(auth_data["user_id"].encode()).hexdigest()
    if data.get("user_id_hash") != expected_user_hash:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Code run not found")
        return

    await websocket.accept()
    await websocket.send_json({"type": "code_run_snapshot", "payload": data})
    if data.get("status") in {"finished", "failed", "timeout", "cancelled"}:
        return

    try:
        async for message in cache_service.subscribe_to_channel(_stream_channel(execution_id)):
            payload = message.get("data") if isinstance(message, dict) else None
            if not isinstance(payload, dict):
                continue
            await websocket.send_json(payload)
            update_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
            if update_payload.get("status") in {"finished", "failed", "timeout", "cancelled"}:
                break
    except WebSocketDisconnect:
        logger.debug("Code Run stream disconnected for execution %s", execution_id)
