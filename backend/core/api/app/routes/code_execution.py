# backend/core/api/app/routes/code_execution.py
#
# Web-app route for running Code embeds in isolated E2B sandboxes.
# The browser sends the current chat and target embed; the backend collects the
# chat's server-cached code embeds, normalizes them to files, starts a Celery
# execution task, and exposes a small polling endpoint for the terminal panel.

from __future__ import annotations

import hashlib
import base64
import json
import logging
import os
import re
import time
import uuid
from pathlib import PurePosixPath
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field, field_validator
from toon_format import decode as toon_decode
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.routes.auth_ws import get_current_user_ws
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.embed_service import EmbedService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.tasks.celery_config import app as celery_app


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/code/run", tags=["Code Run"])

MAX_FILES = 50
MAX_FILE_CHARS = 1_000_000
MAX_TOTAL_CHARS = 10_000_000
MAX_ATTACHMENT_BYTES = 5_000_000
MAX_TOTAL_ATTACHMENT_BYTES = 20_000_000
EXECUTION_TTL_SECONDS = 3600
RUN_CREDITS_PER_MINUTE = 5
ACTIVE_RUN_TTL_SECONDS = 600
MAX_ACTIVE_RUNS_PER_USER = 5
PROVIDER_ACTIVE_RUN_TTL_SECONDS = 600
MAX_ACTIVE_E2B_RUNS = int(os.getenv("CODE_RUN_MAX_ACTIVE_E2B_RUNS", "100"))
E2B_CREATE_RATE_WINDOW_SECONDS = int(os.getenv("CODE_RUN_E2B_CREATE_RATE_WINDOW_SECONDS", "1"))
CODE_RUN_START_RATE_LIMIT = "10/minute"
CODE_RUN_CHANNEL_PREFIX = "code_run_stream"
CLIENT_CONTENT_REQUIRED_CODE = "client_content_required"
TERMINAL_RUN_STATUSES = {"finished", "failed", "timeout", "cancelled"}
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
PYTHON_PACKAGE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9_,.-]+\])?(?:(?:==|~=|!=|<=|>=|<|>)[A-Za-z0-9.*+!_-]+)?$")
NPM_PACKAGE_NAME_PATTERN = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*|[a-z0-9][a-z0-9._-]*)$")
NPM_PACKAGE_PATTERN = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*|[a-z0-9][a-z0-9._-]*)(?:@[A-Za-z0-9._~^*-]+)?$")
NPM_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9.*^~<>=| &!_-]+$")
INSTALL_SNIPPET_LANGUAGES = {"bash", "sh", "shell", "terminal", "console"}
PACKAGE_JSON_DEPENDENCY_SECTIONS = ("dependencies", "devDependencies")
PACKAGE_JSON_UNSUPPORTED_DEPENDENCY_SECTIONS = ("optionalDependencies", "peerDependencies", "bundleDependencies", "bundledDependencies")
UNSAFE_DEPENDENCY_PREFIXES = ("http:", "https:", "git:", "git+", "file:", "link:", "workspace:", "npm:")
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


class CodeRunClientFile(BaseModel):
    embed_id: str = Field(min_length=1)
    code: str = Field(min_length=1, max_length=MAX_FILE_CHARS)
    language: str = ""
    filename: str | None = None
    is_target: bool = False


class CodeRunClientAttachment(BaseModel):
    embed_id: str = Field(min_length=1)
    path: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1)
    mime_type: str = "application/octet-stream"


class CodeRunDependencyInstall(BaseModel):
    ecosystem: Literal["python", "npm"]
    packages: list[str] = Field(min_length=1, max_length=30)

    @field_validator("packages")
    @classmethod
    def validate_packages(cls, packages: list[str], info: Any) -> list[str]:
        ecosystem = info.data.get("ecosystem")
        pattern = PYTHON_PACKAGE_PATTERN if ecosystem == "python" else NPM_PACKAGE_PATTERN
        normalized: list[str] = []
        seen: set[str] = set()
        for package in packages:
            value = package.strip()
            if not value or value.startswith("-") or not pattern.match(value):
                raise ValueError("Unsupported dependency package specifier")
            if value not in seen:
                normalized.append(value)
                seen.add(value)
        return normalized


class CodeRunStartRequest(BaseModel):
    chat_id: str = Field(min_length=1)
    target_embed_id: str = Field(min_length=1)
    enable_internet: bool = True
    client_files: list[CodeRunClientFile] = Field(default_factory=list, max_length=MAX_FILES)
    client_attachments: list[CodeRunClientAttachment] = Field(default_factory=list, max_length=MAX_FILES)
    selected_embed_ids: list[str] | None = Field(default=None, max_length=MAX_FILES)
    dependency_installs: list[CodeRunDependencyInstall] = Field(default_factory=list, max_length=20)


class CodeRunStartResponse(BaseModel):
    execution_id: str
    status: str
    target_filename: str
    files: list[str]
    credits_per_minute: int = RUN_CREDITS_PER_MINUTE


class CodeRunCancelResponse(BaseModel):
    execution_id: str
    status: str


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


def _provider_active_run_key() -> str:
    return "code_run_provider_active:e2b"


def _provider_create_rate_key() -> str:
    return "code_run_provider_create_rate:e2b"


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


def _safe_attachment_path(raw_path: str, embed_id: str) -> str:
    filename = raw_path.strip().replace("\\", "/") or f"attachment-{embed_id[:8]}.bin"
    parts = [part for part in PurePosixPath(filename).parts if part not in ("", ".", "..")]
    cleaned = "/".join(re.sub(r"[^A-Za-z0-9._/-]", "_", part) for part in parts)
    if not cleaned.startswith("inputs/"):
        cleaned = f"inputs/{cleaned}"
    return cleaned or f"inputs/attachment-{embed_id[:8]}.bin"


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


def _embed_metadata_matches(embed: dict[str, Any], chat_id: str, expected_user_hash: str) -> bool:
    hashed_user_id = embed.get("hashed_user_id")
    if hashed_user_id != expected_user_hash:
        return False
    hashed_chat_id = embed.get("hashed_chat_id")
    if hashed_chat_id != hashlib.sha256(chat_id.encode()).hexdigest():
        return False
    return True


async def _get_embed_metadata(
    embed_id: str,
    cache_service: CacheService,
    directus_service: DirectusService,
) -> dict[str, Any] | None:
    cached = await cache_service.get_embed_from_cache(embed_id)
    if cached:
        return cached
    # Metadata only. Directus stores client-encrypted content and must never be
    # treated as server-readable execution input.
    return await directus_service.embed.get_embed_by_id(embed_id)


def _decode_toon_content(plaintext_toon: str) -> dict[str, Any] | None:
    try:
        decoded = toon_decode(plaintext_toon)
    except Exception:
        return None
    return decoded if isinstance(decoded, dict) else None


def _client_file_to_content(file: CodeRunClientFile) -> dict[str, Any]:
    return {
        "type": "code",
        "code": file.code,
        "language": file.language,
        "filename": file.filename,
    }


def _parse_install_line(line: str) -> tuple[Literal["python", "npm"], list[str]] | None:
    if re.search(r"[;&|<>`$\\]", line):
        return None
    trimmed = line.strip()
    python_match = re.match(r"^(?:pip3?\s+install|python3?\s+-m\s+pip\s+install)\s+(.+)$", trimmed)
    npm_match = re.match(r"^npm\s+(?:install|i)\s+(.+)$", trimmed)
    ecosystem: Literal["python", "npm"] | None = "python" if python_match else "npm" if npm_match else None
    raw_packages = (python_match or npm_match).group(1) if python_match or npm_match else ""
    if not ecosystem or not raw_packages.strip():
        return None
    packages = [part for part in raw_packages.split() if part]
    pattern = PYTHON_PACKAGE_PATTERN if ecosystem == "python" else NPM_PACKAGE_PATTERN
    if not packages or any(part.startswith("-") or not pattern.match(part) for part in packages):
        return None
    return ecosystem, packages


def _validate_python_requirements_manifest(content: str) -> None:
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        requirement = line.split(" #", 1)[0].strip()
        lower = requirement.lower()
        if (
            not requirement
            or requirement.startswith(("-", ".", "/"))
            or "://" in requirement
            or lower.startswith(("git+", "hg+", "svn+", "bzr+"))
            or not PYTHON_PACKAGE_PATTERN.match(requirement)
        ):
            raise HTTPException(status_code=400, detail="requirements.txt contains unsupported dependency entries")


def _is_safe_npm_version(value: str) -> bool:
    version = value.strip()
    lower = version.lower()
    return (
        bool(version)
        and not lower.startswith(UNSAFE_DEPENDENCY_PREFIXES)
        and "://" not in lower
        and ".." not in version
        and bool(NPM_VERSION_PATTERN.match(version))
    )


def _validate_package_json_manifest(content: str) -> None:
    try:
        package_json = json.loads(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="package.json is not valid JSON") from exc
    if not isinstance(package_json, dict):
        raise HTTPException(status_code=400, detail="package.json must be an object")
    if package_json.get("scripts"):
        raise HTTPException(status_code=400, detail="package.json scripts are not supported in Code Run")
    for section in PACKAGE_JSON_UNSUPPORTED_DEPENDENCY_SECTIONS:
        if package_json.get(section):
            raise HTTPException(status_code=400, detail=f"package.json {section} are not supported in Code Run")
    for section in PACKAGE_JSON_DEPENDENCY_SECTIONS:
        dependencies = package_json.get(section)
        if dependencies is None:
            continue
        if not isinstance(dependencies, dict):
            raise HTTPException(status_code=400, detail=f"package.json {section} must be an object")
        for package_name, package_version in dependencies.items():
            if not isinstance(package_name, str) or not NPM_PACKAGE_NAME_PATTERN.match(package_name):
                raise HTTPException(status_code=400, detail="package.json contains unsupported package names")
            if not isinstance(package_version, str) or not _is_safe_npm_version(package_version):
                raise HTTPException(status_code=400, detail="package.json contains unsupported dependency versions")


def _validate_dependency_manifest(path: str, content: str) -> None:
    filename = path.rsplit("/", 1)[-1]
    if filename == "requirements.txt":
        _validate_python_requirements_manifest(content)
    elif filename == "package.json":
        _validate_package_json_manifest(content)


def _dependency_installs_from_install_snippets(files: list[dict[str, Any]]) -> list[CodeRunDependencyInstall]:
    installs: dict[Literal["python", "npm"], list[str]] = {"python": [], "npm": []}
    seen: dict[Literal["python", "npm"], set[str]] = {"python": set(), "npm": set()}
    for file in files:
        language = str(file.get("language") or "").lower()
        path = str(file.get("path") or "")
        if language not in INSTALL_SNIPPET_LANGUAGES and not path.endswith(".sh"):
            continue
        content = file.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        parsed_lines: list[tuple[Literal["python", "npm"], list[str]]] = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parsed = _parse_install_line(line)
            if not parsed:
                parsed_lines = []
                break
            parsed_lines.append(parsed)
        for ecosystem, packages in parsed_lines:
            for package in packages:
                if package not in seen[ecosystem]:
                    installs[ecosystem].append(package)
                    seen[ecosystem].add(package)
    return [
        CodeRunDependencyInstall(ecosystem=ecosystem, packages=packages)
        for ecosystem, packages in installs.items()
        if packages
    ]


def _merge_dependency_installs(*groups: list[CodeRunDependencyInstall]) -> list[CodeRunDependencyInstall]:
    merged: dict[Literal["python", "npm"], list[str]] = {"python": [], "npm": []}
    seen: dict[Literal["python", "npm"], set[str]] = {"python": set(), "npm": set()}
    for group in groups:
        for install in group:
            for package in install.packages:
                if package not in seen[install.ecosystem]:
                    merged[install.ecosystem].append(package)
                    seen[install.ecosystem].add(package)
    return [
        CodeRunDependencyInstall(ecosystem=ecosystem, packages=packages)
        for ecosystem, packages in merged.items()
        if packages
    ]


def _metadata_allowed_for_chat(embed: dict[str, Any], chat_id: str, expected_user_hash: str, chat_index_embed_ids: set[str]) -> bool:
    if _embed_metadata_matches(embed, chat_id, expected_user_hash):
        return True
    embed_id = embed.get("embed_id")
    # Upload-cache entries are written by the upload service for server-side app
    # skills and may not include hashed_chat_id. Only trust them when the chat's
    # embed index already listed the ID for this selected chat.
    return isinstance(embed_id, str) and embed_id in chat_index_embed_ids and embed.get("status") == "finished"


def _pick_file_variant(files: Any) -> dict[str, Any] | None:
    if not isinstance(files, dict):
        return None
    for variant_name in ("original", "full", "audio", "source", "preview"):
        variant = files.get(variant_name)
        if isinstance(variant, dict) and isinstance(variant.get("s3_key"), str):
            return variant
    for variant in files.values():
        if isinstance(variant, dict) and isinstance(variant.get("s3_key"), str):
            return variant
    return None


def _attachment_extension(content: dict[str, Any], variant: dict[str, Any]) -> str:
    file_format = variant.get("format")
    if isinstance(file_format, str) and file_format:
        return f".{file_format.lower().lstrip('.')}"
    content_type = content.get("content_type") or content.get("mime_type")
    if isinstance(content_type, str) and "/" in content_type:
        return f".{content_type.rsplit('/', 1)[-1].lower()}"
    return ".bin"


def _attachment_path(content: dict[str, Any], embed_id: str, variant: dict[str, Any]) -> str:
    filename = content.get("filename") or content.get("original_filename")
    if not isinstance(filename, str) or not filename.strip():
        filename = f"attachment-{embed_id[:8]}{_attachment_extension(content, variant)}"
    return filename


async def _download_encrypted_s3_bytes(s3_key: str) -> bytes:
    download_url = f"{os.environ.get('INTERNAL_API_BASE_URL', 'http://api:8000')}/internal/s3/download"
    shared_token = os.environ.get("INTERNAL_API_SHARED_TOKEN", "")
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.get(
            download_url,
            params={"bucket_key": "chatfiles", "s3_key": s3_key},
            headers={"X-Internal-Service-Token": shared_token},
        )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Selected file could not be loaded from storage")
    return response.content


async def _decrypt_attachment_bytes(
    *,
    encrypted_bytes: bytes,
    vault_wrapped_aes_key: str,
    aes_nonce: str,
    current_user: User,
    encryption_service: EncryptionService,
) -> bytes:
    aes_key_b64 = await encryption_service.decrypt_with_user_key(vault_wrapped_aes_key, current_user.vault_key_id)
    if not aes_key_b64:
        raise HTTPException(status_code=400, detail="Selected file key could not be decrypted")
    aes_key = base64.b64decode(aes_key_b64)
    if aes_nonce == "":
        nonce = encrypted_bytes[:12]
        ciphertext = encrypted_bytes[12:]
    else:
        nonce = base64.b64decode(aes_nonce)
        ciphertext = encrypted_bytes
    return AESGCM(aes_key).decrypt(nonce, ciphertext, None)


async def _append_server_attachment(
    *,
    embed_id: str,
    content: dict[str, Any],
    current_user: User,
    encryption_service: EncryptionService,
    used_paths: set[str],
    files: list[dict[str, Any]],
) -> bool:
    vault_wrapped_aes_key = content.get("vault_wrapped_aes_key")
    aes_nonce = content.get("aes_nonce")
    variant = _pick_file_variant(content.get("files") or content.get("s3_files"))
    if not isinstance(vault_wrapped_aes_key, str) or not isinstance(aes_nonce, str) or not variant:
        return False
    s3_key = variant["s3_key"]
    encrypted_bytes = await _download_encrypted_s3_bytes(s3_key)
    plaintext = await _decrypt_attachment_bytes(
        encrypted_bytes=encrypted_bytes,
        vault_wrapped_aes_key=vault_wrapped_aes_key,
        aes_nonce=aes_nonce,
        current_user=current_user,
        encryption_service=encryption_service,
    )
    if len(plaintext) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=400, detail="One selected attachment is too large to run")
    path = _dedupe_path(_safe_attachment_path(_attachment_path(content, embed_id, variant), embed_id), used_paths)
    files.append({
        "path": path,
        "content_base64": base64.b64encode(plaintext).decode("ascii"),
        "language": "",
        "is_target": False,
        "mime_type": str(content.get("content_type") or content.get("mime_type") or "application/octet-stream"),
        "source_embed_id": embed_id,
    })
    return True


def _append_code_file(
    *,
    embed_id: str,
    target_embed_id: str,
    content: dict[str, Any],
    used_paths: set[str],
    files: list[dict[str, Any]],
    total_chars: int,
) -> tuple[int, str | None]:
    embed_type = str(content.get("type") or "").lower()
    if embed_type not in {"code", "code-code"}:
        return total_chars, None

    code = content.get("code")
    if not isinstance(code, str) or not code:
        return total_chars, None
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
        return total_chars, None
    if is_dependency:
        _validate_dependency_manifest(path, code)

    files.append({"path": path, "content": code, "language": language, "is_target": embed_id == target_embed_id})
    return total_chars, path if embed_id == target_embed_id else None


def _append_client_attachments(
    *,
    attachments: list[CodeRunClientAttachment],
    selected_embed_ids: set[str] | None,
    expected_embed_ids: set[str],
    used_paths: set[str],
    files: list[dict[str, Any]],
) -> None:
    total_bytes = 0
    server_resolved_embed_ids = {str(file.get("source_embed_id")) for file in files if file.get("source_embed_id")}
    for attachment in attachments:
        if attachment.embed_id in server_resolved_embed_ids:
            continue
        if selected_embed_ids is not None and attachment.embed_id not in selected_embed_ids:
            continue
        if attachment.embed_id not in expected_embed_ids:
            raise HTTPException(status_code=400, detail="Attachment does not belong to the selected chat")
        try:
            content = base64.b64decode(attachment.content_base64, validate=True)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Attachment content is not valid base64") from exc
        if len(content) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(status_code=400, detail="One selected attachment is too large to run")
        total_bytes += len(content)
        if total_bytes > MAX_TOTAL_ATTACHMENT_BYTES:
            raise HTTPException(status_code=400, detail="Selected attachments are too large to run together")
        path = _dedupe_path(_safe_attachment_path(attachment.path, attachment.embed_id), used_paths)
        files.append({
            "path": path,
            "content_base64": base64.b64encode(content).decode("ascii"),
            "language": "",
            "is_target": False,
            "mime_type": attachment.mime_type,
            "source_embed_id": attachment.embed_id,
        })


async def _collect_code_files(
    chat_id: str,
    target_embed_id: str,
    client_files: list[CodeRunClientFile],
    client_attachments: list[CodeRunClientAttachment],
    selected_embed_ids: list[str] | None,
    current_user: User,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
) -> tuple[list[dict[str, Any]], str]:
    embed_ids = await cache_service.get_chat_embed_ids(chat_id)
    selected_ids = set(selected_embed_ids) if selected_embed_ids is not None else None
    chat_index_embed_ids = set(embed_ids)
    if selected_ids is not None:
        selected_ids.add(target_embed_id)
        for embed_id in selected_ids:
            if embed_id not in embed_ids:
                embed_ids.append(embed_id)

    if target_embed_id not in embed_ids:
        embed_ids.append(target_embed_id)
    if selected_ids is not None:
        embed_ids = [embed_id for embed_id in embed_ids if embed_id in selected_ids]

    if len(embed_ids) > MAX_FILES:
        embed_ids = [embed_id for embed_id in embed_ids if embed_id != target_embed_id][: MAX_FILES - 1]
        embed_ids.append(target_embed_id)

    used_paths: set[str] = set()
    files: list[dict[str, Any]] = []
    target_path: str | None = None
    total_chars = 0
    expected_user_hash = hashlib.sha256(current_user.id.encode()).hexdigest()
    client_files_by_id = {file.embed_id: file for file in client_files}
    validated_embed_ids: set[str] = set()
    embed_service = EmbedService(cache_service=cache_service, directus_service=directus_service, encryption_service=encryption_service)

    for embed_id in embed_ids:
        metadata = await _get_embed_metadata(embed_id, cache_service, directus_service)
        if not metadata or not _metadata_allowed_for_chat(metadata, chat_id, expected_user_hash, chat_index_embed_ids):
            continue
        validated_embed_ids.add(embed_id)

        content: dict[str, Any] | None = None
        cached_toon = await embed_service._get_cached_embed_toon(embed_id, current_user.vault_key_id, "[CODE_RUN] ")
        if cached_toon:
            content = _decode_toon_content(cached_toon)
        elif embed_id in client_files_by_id:
            content = _client_file_to_content(client_files_by_id[embed_id])
        else:
            content = metadata

        if not content:
            continue

        total_chars, maybe_target_path = _append_code_file(
            embed_id=embed_id,
            target_embed_id=target_embed_id,
            content=content,
            used_paths=used_paths,
            files=files,
            total_chars=total_chars,
        )
        if maybe_target_path:
            target_path = maybe_target_path
        elif embed_id != target_embed_id and selected_ids is not None:
            await _append_server_attachment(
                embed_id=embed_id,
                content=content,
                current_user=current_user,
                encryption_service=encryption_service,
                used_paths=used_paths,
                files=files,
            )

    if not target_path:
        metadata = await _get_embed_metadata(target_embed_id, cache_service, directus_service)
        if metadata and _embed_metadata_matches(metadata, chat_id, expected_user_hash) and not client_files_by_id.get(target_embed_id):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": CLIENT_CONTENT_REQUIRED_CODE,
                    "message": "Code content is not in the recent server cache; resend the decrypted code from this device.",
                },
            )
        raise HTTPException(status_code=404, detail="Target code embed is not available for server-side execution")

    _append_client_attachments(
        attachments=client_attachments,
        selected_embed_ids=selected_ids,
        expected_embed_ids=validated_embed_ids,
        used_paths=used_paths,
        files=files,
    )
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


async def _try_reserve_provider_run(client: Any, execution_id: str) -> str | None:
    script = """
local active_key = KEYS[1]
local rate_key = KEYS[2]
local execution_id = ARGV[1]
local max_runs = tonumber(ARGV[2])
local active_ttl_seconds = tonumber(ARGV[3])
local create_rate_window_seconds = tonumber(ARGV[4])
if redis.call('GET', rate_key) then
    return 'rate_limited'
end
if redis.call('SCARD', active_key) >= max_runs then
    return 'capacity_limited'
end
redis.call('SET', rate_key, execution_id, 'EX', create_rate_window_seconds)
redis.call('SADD', active_key, execution_id)
redis.call('EXPIRE', active_key, active_ttl_seconds)
return 'ok'
"""
    result = await client.eval(
        script,
        2,
        _provider_active_run_key(),
        _provider_create_rate_key(),
        execution_id,
        MAX_ACTIVE_E2B_RUNS,
        PROVIDER_ACTIVE_RUN_TTL_SECONDS,
        E2B_CREATE_RATE_WINDOW_SECONDS,
    )
    value = result.decode("utf-8") if isinstance(result, bytes) else str(result)
    return None if value == "ok" else value


@router.post("", response_model=CodeRunStartResponse)
@limiter.limit(CODE_RUN_START_RATE_LIMIT)
async def start_code_run(
    request: Request,
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
        body.client_files,
        body.client_attachments,
        body.selected_embed_ids,
        current_user,
        cache_service,
        directus_service,
        encryption_service,
    )
    dependency_installs = _merge_dependency_installs(
        body.dependency_installs,
        _dependency_installs_from_install_snippets(files),
    )
    if dependency_installs:
        logger.info(
            "Code Run dependency installs requested: %s",
            {install.ecosystem: len(install.packages) for install in dependency_installs},
        )
    target_metadata = await _get_embed_metadata(body.target_embed_id, cache_service, directus_service) or {}
    target_message_id = target_metadata.get("message_id")
    user_id_hash = hashlib.sha256(current_user.id.encode()).hexdigest()
    client = await cache_service.client
    active_key = _active_run_key(user_id_hash)
    execution_id = str(uuid.uuid4())
    run_slot_created = await _try_add_active_run(client, active_key, execution_id)
    if not run_slot_created:
        raise HTTPException(status_code=429, detail="Too many code runs are already active for this user")
    provider_limit = await _try_reserve_provider_run(client, execution_id)
    if provider_limit:
        await client.srem(active_key, execution_id)
        if provider_limit == "rate_limited":
            raise HTTPException(
                status_code=429,
                detail="Code Run is starting sandboxes too quickly. Please try again in a moment",
            )
        raise HTTPException(
            status_code=429,
            detail="Code Run sandbox capacity is currently full. Please try again shortly",
        )

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
        "message_id": target_message_id if isinstance(target_message_id, str) else None,
        "target_embed_id": body.target_embed_id,
        "target_path": target_path,
        "enable_internet": body.enable_internet,
        "files": files,
        "dependency_installs": [install.model_dump() for install in dependency_installs],
        "active_run_key": active_key,
        "active_run_owner": execution_id,
        "provider_active_run_key": _provider_active_run_key(),
        "provider_active_run_owner": execution_id,
    }
    try:
        await _create_execution_record(cache_service, execution_id, record)
        celery_app.send_task("code.run_execution", args=[execution_id, payload], queue="app_code")
    except Exception:
        await client.srem(active_key, execution_id)
        await client.srem(_provider_active_run_key(), execution_id)
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


@router.post("/{execution_id}/cancel", response_model=CodeRunCancelResponse)
async def cancel_code_run(
    execution_id: str,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
) -> CodeRunCancelResponse:
    client = await cache_service.client
    key = _execution_key(execution_id)
    raw = await client.get(key)
    if not raw:
        raise HTTPException(status_code=404, detail="Code run not found or expired")
    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    expected_user_hash = hashlib.sha256(current_user.id.encode()).hexdigest()
    if data.get("user_id_hash") != expected_user_hash:
        raise HTTPException(status_code=404, detail="Code run not found or expired")

    if data.get("status") in TERMINAL_RUN_STATUSES:
        return CodeRunCancelResponse(execution_id=execution_id, status=str(data.get("status")))

    now = time.time()
    data.update({"cancel_requested": True, "cancel_requested_at": now, "status": "cancelling", "updated_at": now})
    await client.set(key, json.dumps(data), ex=EXECUTION_TTL_SECONDS)
    await cache_service.publish_event(
        _stream_channel(execution_id),
        {"type": "code_run_update", "payload": {"status": "cancelling", "cancel_requested": True, "updated_at": now}},
    )
    return CodeRunCancelResponse(execution_id=execution_id, status="cancelling")


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
    if data.get("status") in TERMINAL_RUN_STATUSES:
        return

    try:
        async for message in cache_service.subscribe_to_channel(_stream_channel(execution_id)):
            payload = message.get("data") if isinstance(message, dict) else None
            if not isinstance(payload, dict):
                continue
            await websocket.send_json(payload)
            update_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
            if update_payload.get("status") in TERMINAL_RUN_STATUSES:
                break
    except WebSocketDisconnect:
        logger.debug("Code Run stream disconnected for execution %s", execution_id)
