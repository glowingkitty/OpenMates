# backend/core/api/app/routes/electronics_pcb_schematic.py
#
# Web-app endpoints for Electronics PCB schematic embeds. The route validates
# user ownership, decrypts the server-readable embed cache, runs atopile only in
# E2B through the shared provider, and writes sanitized compile metadata back to
# the encrypted embed content for fullscreen rendering.

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from toon_format import decode

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.embed_service import EmbedService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.e2b_pcb_schematic_compiler import (
    PcbSchematicCompileRequest,
    compile_pcb_schematic_in_e2b,
    get_e2b_api_key_async,
)
from backend.shared.python_utils.pcb_schematic_artifacts import get_cached_pcb_schematic_artifact


router = APIRouter(prefix="/v1/electronics/pcb-schematic", tags=["Electronics PCB Schematic"])
COMPILE_TTL_SECONDS = 3600


class PcbSchematicPrepareRequest(BaseModel):
    force: bool = False


class PcbSchematicPrepareResponse(BaseModel):
    compile_id: str
    status: str
    artifact_manifest: dict[str, Any] | None = None
    error: str | None = None
    logs: str | None = None


def get_cache_service(request: Request) -> CacheService:
    return request.app.state.cache_service


def get_directus_service(request: Request) -> DirectusService:
    return request.app.state.directus_service


def get_encryption_service(request: Request) -> EncryptionService:
    return request.app.state.encryption_service


def get_secrets_manager(request: Request) -> SecretsManager | None:
    return getattr(request.app.state, "secrets_manager", None)


def _compile_key(compile_id: str) -> str:
    return f"pcb_schematic_compile:{compile_id}"


async def _load_pcb_schematic_content(
    *,
    embed_id: str,
    current_user: User,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
) -> tuple[dict[str, Any], dict[str, Any]]:
    user_hash = hashlib.sha256(current_user.id.encode()).hexdigest()
    embed = await cache_service.get_embed_from_cache(embed_id)
    if not embed:
        embed = await directus_service.embed.get_embed_by_id(embed_id)
    if not embed:
        raise HTTPException(status_code=404, detail="PCB schematic embed not found")
    if embed.get("hashed_user_id") != user_hash:
        raise HTTPException(status_code=403, detail="PCB schematic embed is not available to this user")
    if not current_user.vault_key_id:
        raise HTTPException(status_code=400, detail="User vault key is required")

    encrypted_content = embed.get("encrypted_content")
    if not isinstance(encrypted_content, str) or not encrypted_content:
        raise HTTPException(status_code=422, detail="PCB schematic embed has no readable content")
    try:
        plaintext = await encryption_service.decrypt_with_user_key(encrypted_content, current_user.vault_key_id)
        content = decode(plaintext)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="PCB schematic embed content could not be decoded") from exc
    if not isinstance(content, dict) or content.get("type") != "pcb_schematic":
        raise HTTPException(status_code=422, detail="Target embed is not a PCB schematic")
    if not isinstance(content.get("code"), str) or not content.get("code", "").strip():
        raise HTTPException(status_code=422, detail="PCB schematic source is empty")
    return embed, content


@router.post("/embeds/{embed_id}/prepare-files", response_model=PcbSchematicPrepareResponse)
async def prepare_pcb_schematic_files(
    embed_id: str,
    body: PcbSchematicPrepareRequest,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
    secrets_manager: SecretsManager | None = Depends(get_secrets_manager),
) -> PcbSchematicPrepareResponse:
    embed, content = await _load_pcb_schematic_content(
        embed_id=embed_id,
        current_user=current_user,
        cache_service=cache_service,
        directus_service=directus_service,
        encryption_service=encryption_service,
    )
    if content.get("compile_status") == "running" and not body.force:
        raise HTTPException(status_code=409, detail="PCB schematic compile already running")

    compile_id = str(uuid.uuid4())
    user_hash = hashlib.sha256(current_user.id.encode()).hexdigest()
    client = await cache_service.client
    now = time.time()
    await client.set(
        _compile_key(compile_id),
        json.dumps({"compile_id": compile_id, "embed_id": embed_id, "user_id_hash": user_hash, "status": "running", "created_at": now, "updated_at": now}),
        ex=COMPILE_TTL_SECONDS,
    )

    embed_service = EmbedService(cache_service, directus_service, encryption_service)
    await embed_service.update_pcb_schematic_embed_content(
        embed_id=embed_id,
        code_content=str(content["code"]),
        chat_id=str(embed.get("chat_id") or ""),
        user_id=current_user.id,
        user_id_hash=user_hash,
        user_vault_key_id=current_user.vault_key_id,
        status=str(embed.get("status") or "finished"),
        title=content.get("title") if isinstance(content.get("title"), str) else None,
        module_name=content.get("module_name") if isinstance(content.get("module_name"), str) else None,
        filename=content.get("filename") if isinstance(content.get("filename"), str) else None,
        compile_id=compile_id,
        compile_status="running",
    )

    try:
        api_key = await get_e2b_api_key_async(secrets_manager)
        result = compile_pcb_schematic_in_e2b(
            PcbSchematicCompileRequest(
                source=str(content["code"]),
                filename=str(content.get("filename") or "main.ato"),
                module_name=str(content.get("module_name") or "App"),
            ),
            api_key=api_key,
        )
        await embed_service.update_pcb_schematic_embed_content(
            embed_id=embed_id,
            code_content=str(content["code"]),
            chat_id=str(embed.get("chat_id") or ""),
            user_id=current_user.id,
            user_id_hash=user_hash,
            user_vault_key_id=current_user.vault_key_id,
            status=str(embed.get("status") or "finished"),
            title=content.get("title") if isinstance(content.get("title"), str) else None,
            module_name=content.get("module_name") if isinstance(content.get("module_name"), str) else None,
            filename=content.get("filename") if isinstance(content.get("filename"), str) else None,
            compile_id=compile_id,
            compile_status=result.status,
            compile_logs=result.logs,
            artifact_manifest=result.artifact_manifest,
        )
        artifact_payloads = [
            {
                "id": artifact.id,
                "type": artifact.type,
                "path": artifact.path,
                "name": artifact.name,
                "content": artifact.content,
            }
            for artifact in result.artifacts
        ]
        record = {
            "compile_id": compile_id,
            "embed_id": embed_id,
            "user_id_hash": user_hash,
            "status": result.status,
            "logs": result.logs,
            "artifact_manifest": result.artifact_manifest,
            "artifacts": artifact_payloads,
            "created_at": now,
            "updated_at": time.time(),
        }
        await client.set(_compile_key(compile_id), json.dumps(record), ex=COMPILE_TTL_SECONDS)
        return PcbSchematicPrepareResponse(
            compile_id=compile_id,
            status=result.status,
            artifact_manifest=result.artifact_manifest,
            logs=result.logs,
        )
    except Exception as exc:
        error = str(exc)
        await embed_service.update_pcb_schematic_embed_content(
            embed_id=embed_id,
            code_content=str(content["code"]),
            chat_id=str(embed.get("chat_id") or ""),
            user_id=current_user.id,
            user_id_hash=user_hash,
            user_vault_key_id=current_user.vault_key_id,
            status=str(embed.get("status") or "finished"),
            title=content.get("title") if isinstance(content.get("title"), str) else None,
            module_name=content.get("module_name") if isinstance(content.get("module_name"), str) else None,
            filename=content.get("filename") if isinstance(content.get("filename"), str) else None,
            compile_id=compile_id,
            compile_status="failed",
            compile_logs=error,
        )
        await client.set(
            _compile_key(compile_id),
            json.dumps({"compile_id": compile_id, "embed_id": embed_id, "user_id_hash": user_hash, "status": "failed", "error": error, "created_at": now, "updated_at": time.time()}),
            ex=COMPILE_TTL_SECONDS,
        )
        return PcbSchematicPrepareResponse(compile_id=compile_id, status="failed", error=error, logs=error)


@router.get("/compile/{compile_id}")
async def get_pcb_schematic_compile_status(
    compile_id: str,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
) -> dict[str, Any]:
    client = await cache_service.client
    raw = await client.get(_compile_key(compile_id))
    if not raw:
        raise HTTPException(status_code=404, detail="PCB schematic compile not found")
    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    if data.get("user_id_hash") != hashlib.sha256(current_user.id.encode()).hexdigest():
        raise HTTPException(status_code=404, detail="PCB schematic compile not found")
    data.pop("artifacts", None)
    return data


@router.get("/compile/{compile_id}/artifacts/{artifact_id}")
async def download_pcb_schematic_artifact(
    compile_id: str,
    artifact_id: str,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
) -> Response:
    client = await cache_service.client
    raw = await client.get(_compile_key(compile_id))
    if not raw:
        raise HTTPException(status_code=404, detail="PCB schematic artifact not found")
    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    if data.get("user_id_hash") != hashlib.sha256(current_user.id.encode()).hexdigest():
        raise HTTPException(status_code=404, detail="PCB schematic artifact not found")

    artifact = get_cached_pcb_schematic_artifact(data, artifact_id)
    if artifact:
        filename, content = artifact
        return Response(
            content=content,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    raise HTTPException(status_code=404, detail="PCB schematic artifact not found")
