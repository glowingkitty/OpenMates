# backend/apps/code/skills/run_code_skill.py
#
# Assistant skill for Code Run.
# The skill reuses the existing /v1/code/run collection/start path so assistant,
# web, REST, and SDK surfaces share validation, E2B execution, billing, and
# status semantics instead of creating a second sandbox entrypoint.

from __future__ import annotations

import base64
import hashlib
import inspect
import json
import re
import time
from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill


CODE_RUN_ASSISTANT_AUTH_TTL_SECONDS = 60 * 60
CODE_RUN_ASSISTANT_MAX_UNPROMPTED_RERUNS = 2
CODE_RUN_ASSISTANT_MAX_AUTO_RUNS = 1 + CODE_RUN_ASSISTANT_MAX_UNPROMPTED_RERUNS
CODE_RUN_ASSISTANT_MAX_FILES = 50
CODE_RUN_ASSISTANT_MAX_FILE_CHARS = 1_000_000
CODE_RUN_ASSISTANT_MAX_TOTAL_CHARS = 10_000_000
CODE_RUN_PYTHON_PACKAGE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9_,.-]+\])?(?:(?:==|~=|!=|<=|>=|<|>)[A-Za-z0-9.*+!_-]+)?$")
CODE_RUN_NPM_PACKAGE_NAME_PATTERN = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*|[a-z0-9][a-z0-9._-]*)$")
CODE_RUN_NPM_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9.*^~<>=| &!_-]+$")
CODE_RUN_PACKAGE_JSON_DEPENDENCY_SECTIONS = ("dependencies", "devDependencies")
CODE_RUN_PACKAGE_JSON_UNSUPPORTED_DEPENDENCY_SECTIONS = ("optionalDependencies", "peerDependencies", "bundleDependencies", "bundledDependencies")
CODE_RUN_UNSAFE_DEPENDENCY_PREFIXES = ("http:", "https:", "git:", "git+", "file:", "link:", "workspace:", "npm:")
CODE_RUN_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[oprsu]_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
]


class CodeRunInlineValidationError(ValueError):
    """Validation error for assistant-supplied inline Code Run files."""


class RunCodeInlineFile(BaseModel):
    path: str = Field(description="Relative file path to create and run, such as main.py.")
    code: str = Field(description="UTF-8 source code for this assistant-created file.")
    language: str = Field(default="", description="Programming language for display and execution hints.")
    mime_type: str = Field(default="text/plain", description="MIME type for this text file.")
    is_target: bool = Field(default=False, description="Whether this file is the entrypoint.")


class RunCodeRequest(BaseModel):
    chat_id: str | None = Field(default=None, description="Chat ID containing the code embeds to run.")
    target_embed_id: str | None = Field(default=None, description="Existing code embed ID to execute as the entrypoint.")
    entry_path: str | None = Field(default=None, description="Entrypoint path when files are supplied inline.")
    files: list[RunCodeInlineFile] = Field(default_factory=list, description="Assistant-created code files to create as embeds and run.")
    enable_internet: bool = Field(default=True, description="Allow outbound internet access from the E2B sandbox.")
    selected_embed_ids: list[str] | None = Field(default=None, description="Optional related embed IDs to include in the run.")
    dependency_installs: list[dict[str, Any]] = Field(default_factory=list, description="Selected package installs for this run.")


class RunCodeResponse(BaseModel):
    execution_id: str | None = None
    task_id: str | None = None
    embed_id: str | None = None
    target_embed_id: str | None = None
    created_embed_ids: list[str] = Field(default_factory=list)
    status: str = "processing"
    target_filename: str | None = None
    files: list[str] = Field(default_factory=list)
    credits_per_minute: int | None = None
    stream_path: str | None = None
    status_path: str | None = None
    error: str | None = None


def assistant_code_run_authorization_key(chat_id: str, message_id: str, target_embed_id: str) -> str:
    return f"code_run_assistant_authorized:{chat_id}:{message_id}:{target_embed_id}"


def assistant_code_run_attempt_key(chat_id: str, message_id: str, target_embed_id: str) -> str:
    return f"code_run_assistant_attempts:{chat_id}:{message_id}:{target_embed_id}"


def assistant_code_run_inline_attempt_key(chat_id: str, message_id: str, target_path: str) -> str:
    return f"code_run_assistant_inline_attempts:{chat_id}:{message_id}:{target_path}"


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _cache_get(cache_service: Any, key: str) -> Any:
    if cache_service is None:
        return None
    getter = getattr(cache_service, "get", None)
    if callable(getter):
        return await _maybe_await(getter(key))
    client_attr = getattr(cache_service, "client", None)
    client = await _maybe_await(client_attr) if client_attr is not None else None
    if client and hasattr(client, "get"):
        raw = await client.get(key)
        if isinstance(raw, bytes):
            return raw.decode("utf-8")
        return raw
    return None


async def _cache_set(cache_service: Any, key: str, value: Any, ttl: int) -> bool:
    if cache_service is None:
        return False
    setter = getattr(cache_service, "set", None)
    if callable(setter):
        return bool(await _maybe_await(setter(key, value, ttl=ttl)))
    client_attr = getattr(cache_service, "client", None)
    client = await _maybe_await(client_attr) if client_attr is not None else None
    if client and hasattr(client, "set"):
        return bool(await client.set(key, value, ex=ttl))
    return False


async def _increment_cache_counter(cache_service: Any, key: str, ttl: int) -> int:
    client_attr = getattr(cache_service, "client", None) if cache_service is not None else None
    client = await _maybe_await(client_attr) if client_attr is not None else None
    if client and hasattr(client, "incr"):
        count = int(await client.incr(key))
        if count == 1 and hasattr(client, "expire"):
            await client.expire(key, ttl)
        return count
    current = await _cache_get(cache_service, key)
    try:
        count = int(current or 0) + 1
    except (TypeError, ValueError):
        count = 1
    await _cache_set(cache_service, key, count, ttl)
    return count


async def mark_assistant_code_run_authorized(
    cache_service: Any,
    *,
    chat_id: str,
    message_id: str,
    target_embed_id: str,
    action: str,
) -> bool:
    """Mark an assistant-created/edited code embed as runnable without user confirmation."""
    if not chat_id or not message_id or not target_embed_id:
        return False
    return await _cache_set(
        cache_service,
        assistant_code_run_authorization_key(chat_id, message_id, target_embed_id),
        {"action": action, "created_at": int(time.time())},
        CODE_RUN_ASSISTANT_AUTH_TTL_SECONDS,
    )


async def _authorize_assistant_code_run(
    cache_service: Any,
    *,
    chat_id: str,
    message_id: str,
    target_embed_id: str,
) -> tuple[bool, str]:
    marker = await _cache_get(
        cache_service,
        assistant_code_run_authorization_key(chat_id, message_id, target_embed_id),
    )
    if not marker:
        return False, "Code Run can auto-run only code the assistant created or edited in this turn. Ask the user before running unmodified user code."
    attempt_count = await _increment_cache_counter(
        cache_service,
        assistant_code_run_attempt_key(chat_id, message_id, target_embed_id),
        CODE_RUN_ASSISTANT_AUTH_TTL_SECONDS,
    )
    if attempt_count > CODE_RUN_ASSISTANT_MAX_AUTO_RUNS:
        return False, "Code Run already used the initial run and two unprompted reruns for this code. Ask the user before running it again."
    return True, "assistant_current_turn"


async def _authorize_assistant_inline_code_run(
    cache_service: Any,
    *,
    chat_id: str,
    message_id: str,
    target_path: str,
) -> tuple[bool, str]:
    attempt_count = await _increment_cache_counter(
        cache_service,
        assistant_code_run_inline_attempt_key(chat_id, message_id, target_path),
        CODE_RUN_ASSISTANT_AUTH_TTL_SECONDS,
    )
    if attempt_count > CODE_RUN_ASSISTANT_MAX_AUTO_RUNS:
        return False, "Code Run already used the initial run and two unprompted reruns for this code. Ask the user before running it again."
    return True, "assistant_inline_current_turn"


def create_directus_service(*, cache_service: Any, encryption_service: Any) -> Any:
    from backend.core.api.app.services.directus import DirectusService

    return DirectusService(cache_service=cache_service, encryption_service=encryption_service)


async def create_code_embeds_for_assistant(
    *,
    files: list[dict[str, Any]],
    target_path: str,
    chat_id: str,
    message_id: str,
    user_id: str,
    user_vault_key_id: str,
    cache_service: Any,
    directus_service: Any,
    encryption_service: Any,
) -> tuple[str, list[str]]:
    from backend.core.api.app.services.embed_service import EmbedService

    embed_service = EmbedService(
        cache_service=cache_service,
        directus_service=directus_service,
        encryption_service=encryption_service,
    )
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
    created_embed_ids: list[str] = []
    target_embed_id: str | None = None
    for file in files:
        path = str(file.get("path") or "")
        language = str(file.get("language") or _language_for_path(path))
        embed_data = await embed_service.create_code_embed_placeholder(
            language=language,
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
            user_id_hash=user_id_hash,
            user_vault_key_id=user_vault_key_id,
            filename=path,
            code_content=str(file.get("content") or ""),
            log_prefix="[assistant_code_run] ",
        )
        if not embed_data or not embed_data.get("embed_id"):
            raise RuntimeError("Code Run could not create a chat code embed for assistant-created code.")
        embed_id = str(embed_data["embed_id"])
        updated = await embed_service.update_code_embed_content(
            embed_id=embed_id,
            code_content=str(file.get("content") or ""),
            chat_id=chat_id,
            user_id=user_id,
            user_id_hash=user_id_hash,
            user_vault_key_id=user_vault_key_id,
            status="finished",
            log_prefix="[assistant_code_run] ",
        )
        if not updated:
            raise RuntimeError("Code Run could not finalize the assistant-created code embed.")
        await mark_assistant_code_run_authorized(
            cache_service,
            chat_id=chat_id,
            message_id=message_id,
            target_embed_id=embed_id,
            action="created",
        )
        created_embed_ids.append(embed_id)
        if path == target_path:
            target_embed_id = embed_id
    if not target_embed_id:
        raise RuntimeError("Code Run could not identify the target assistant-created code embed.")
    return target_embed_id, created_embed_ids


async def collect_code_files_for_assistant(**kwargs: Any) -> tuple[list[dict[str, Any]], str]:
    from backend.core.api.app.routes.code_execution import _collect_code_files

    return await _collect_code_files(**kwargs)


async def start_code_run_for_assistant(**kwargs: Any) -> Any:
    from backend.core.api.app.routes.code_execution import start_code_run_execution

    return await start_code_run_execution(**kwargs)


def _dependency_installs(items: list[dict[str, Any]]) -> list[Any]:
    if not items:
        return []
    from backend.core.api.app.routes.code_execution import CodeRunDependencyInstall

    return [CodeRunDependencyInstall.model_validate(item) for item in items]


def _coerce_credit_balance(value: Any) -> int | None:
    try:
        credits = int(value)
    except (TypeError, ValueError):
        return None
    return credits if credits >= 0 else None


async def get_assistant_user_credit_balance(cache_service: Any, directus_service: Any, user_id: str) -> int:
    cached_getter = getattr(cache_service, "get_user_by_id", None)
    if callable(cached_getter):
        cached_user = await _maybe_await(cached_getter(user_id))
        if isinstance(cached_user, dict):
            cached_credits = _coerce_credit_balance(cached_user.get("credits"))
            if cached_credits is not None:
                return cached_credits

    profile_getter = getattr(directus_service, "get_user_profile", None)
    if callable(profile_getter):
        profile_result = await _maybe_await(profile_getter(user_id))
        if isinstance(profile_result, tuple) and len(profile_result) >= 2:
            success, profile = profile_result[0], profile_result[1]
            if success and isinstance(profile, dict):
                profile_credits = _coerce_credit_balance(profile.get("credits"))
                if profile_credits is not None:
                    return profile_credits

    raise RuntimeError("Code Run could not verify the current user credit balance.")


def _language_for_path(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    return {
        ".py": "python",
        ".js": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".ts": "typescript",
        ".sh": "bash",
        ".c": "c",
        ".cc": "cpp",
        ".cpp": "cpp",
        ".cxx": "cpp",
        ".rs": "rust",
        ".go": "go",
    }.get(suffix, "")


def _looks_like_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in CODE_RUN_SECRET_PATTERNS)


def _validate_inline_code_run_path(raw_path: str) -> str:
    path = raw_path.strip().replace("\\", "/")
    if (
        not path
        or "\x00" in path
        or path.startswith(("/", "~/"))
        or re.match(r"^[A-Za-z]:/", path)
    ):
        raise CodeRunInlineValidationError("Unsafe Code Run path")
    parts = PurePosixPath(path).parts
    if any(part in ("", ".", "..") for part in parts):
        raise CodeRunInlineValidationError("Unsafe Code Run path")
    cleaned = "/".join(parts)
    if not cleaned or cleaned != path:
        raise CodeRunInlineValidationError("Unsafe Code Run path")
    return cleaned


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
            or not CODE_RUN_PYTHON_PACKAGE_PATTERN.match(requirement)
        ):
            raise CodeRunInlineValidationError("requirements.txt contains unsupported dependency entries")


def _is_safe_npm_version(value: str) -> bool:
    version = value.strip()
    lower = version.lower()
    return (
        bool(version)
        and not lower.startswith(CODE_RUN_UNSAFE_DEPENDENCY_PREFIXES)
        and "://" not in lower
        and ".." not in version
        and bool(CODE_RUN_NPM_VERSION_PATTERN.match(version))
    )


def _validate_package_json_manifest(content: str) -> None:
    try:
        package_json = json.loads(content)
    except json.JSONDecodeError as exc:
        raise CodeRunInlineValidationError("package.json is not valid JSON") from exc
    if not isinstance(package_json, dict):
        raise CodeRunInlineValidationError("package.json must be an object")
    if package_json.get("scripts"):
        raise CodeRunInlineValidationError("package.json scripts are not supported in Code Run")
    for section in CODE_RUN_PACKAGE_JSON_UNSUPPORTED_DEPENDENCY_SECTIONS:
        if package_json.get(section):
            raise CodeRunInlineValidationError(f"package.json {section} are not supported in Code Run")
    for section in CODE_RUN_PACKAGE_JSON_DEPENDENCY_SECTIONS:
        dependencies = package_json.get(section)
        if dependencies is None:
            continue
        if not isinstance(dependencies, dict):
            raise CodeRunInlineValidationError(f"package.json {section} must be an object")
        for package_name, package_version in dependencies.items():
            if not isinstance(package_name, str) or not CODE_RUN_NPM_PACKAGE_NAME_PATTERN.match(package_name):
                raise CodeRunInlineValidationError("package.json contains unsupported package names")
            if not isinstance(package_version, str) or not _is_safe_npm_version(package_version):
                raise CodeRunInlineValidationError("package.json contains unsupported dependency versions")


def _validate_dependency_manifest(path: str, content: str) -> None:
    filename = path.rsplit("/", 1)[-1]
    if filename == "requirements.txt":
        _validate_python_requirements_manifest(content)
    elif filename == "package.json":
        _validate_package_json_manifest(content)


def collect_inline_code_files_for_assistant(request: RunCodeRequest) -> tuple[list[dict[str, Any]], str]:
    if not request.files:
        raise CodeRunInlineValidationError("Direct Code Run requires at least one file")
    if len(request.files) > CODE_RUN_ASSISTANT_MAX_FILES:
        raise CodeRunInlineValidationError("Code Run file bundle contains too many files")

    used_paths: set[str] = set()
    files: list[dict[str, Any]] = []
    total_chars = 0
    entry_path = _validate_inline_code_run_path(request.entry_path or "") if request.entry_path else None

    for file in request.files:
        path = _validate_inline_code_run_path(file.path)
        if path in used_paths:
            raise CodeRunInlineValidationError("Duplicate Code Run file path")
        used_paths.add(path)
        content = file.code
        if len(content) > CODE_RUN_ASSISTANT_MAX_FILE_CHARS:
            raise CodeRunInlineValidationError("One Code Run file is too large")
        total_chars += len(content)
        if total_chars > CODE_RUN_ASSISTANT_MAX_TOTAL_CHARS:
            raise CodeRunInlineValidationError("Code Run file bundle is too large")
        if _looks_like_secret(content):
            raise CodeRunInlineValidationError(f"Code Run file {path} appears to contain a secret")
        _validate_dependency_manifest(path, content)
        content_bytes = content.encode("utf-8")
        files.append({
            "path": path,
            "content_base64": base64.b64encode(content_bytes).decode("ascii"),
            "content": content,
            "language": file.language or _language_for_path(path),
            "is_target": file.is_target,
            "mime_type": file.mime_type,
        })

    target_path = entry_path or next((file["path"] for file in files if file.get("is_target")), None)
    if not target_path:
        target_path = files[0]["path"]
        files[0]["is_target"] = True
    target_path = _validate_inline_code_run_path(target_path)
    if target_path not in used_paths:
        raise CodeRunInlineValidationError("Code Run entry file is not included in uploaded files")
    for file in files:
        file["is_target"] = file["path"] == target_path
    return files, target_path




class RunCodeSkill(BaseSkill):
    """Run assistant-created or explicitly confirmed code in an E2B sandbox."""

    async def execute(self, request: RunCodeRequest, **kwargs: Any) -> RunCodeResponse:
        context_chat_id = kwargs.get("chat_id") or self._current_chat_id
        if request.chat_id and context_chat_id and str(request.chat_id) != str(context_chat_id):
            return RunCodeResponse(status="error", error="Code Run chat_id does not match the current chat context.")
        chat_id = context_chat_id or request.chat_id
        message_id = kwargs.get("message_id") or self._current_message_id
        user_id = kwargs.get("user_id")
        user_vault_key_id = kwargs.get("user_vault_key_id")
        cache_service = kwargs.get("cache_service")
        encryption_service = kwargs.get("encryption_service")
        if not chat_id or not message_id or not user_id or not user_vault_key_id or cache_service is None or encryption_service is None:
            return RunCodeResponse(status="error", error="Code Run requires chat, message, user, cache, and encryption context.")

        created_embed_ids: list[str] = []
        target_embed_id = request.target_embed_id
        if request.files:
            try:
                files, target_path = collect_inline_code_files_for_assistant(request)
            except CodeRunInlineValidationError as exc:
                return RunCodeResponse(status="error", error=str(exc))
            authorized, reason = await _authorize_assistant_inline_code_run(
                cache_service,
                chat_id=str(chat_id),
                message_id=str(message_id),
                target_path=target_path,
            )
            if not authorized:
                return RunCodeResponse(status="requires_confirmation", error=reason)
        else:
            if not target_embed_id:
                return RunCodeResponse(
                    status="error",
                    error="Code Run requires either target_embed_id for an existing code embed or files for assistant-created code.",
                )
            authorized, reason = await _authorize_assistant_code_run(
                cache_service,
                chat_id=str(chat_id),
                message_id=str(message_id),
                target_embed_id=target_embed_id,
            )
            if not authorized:
                return RunCodeResponse(status="requires_confirmation", error=reason)

        directus_service = create_directus_service(cache_service=cache_service, encryption_service=encryption_service)
        try:
            credits = await get_assistant_user_credit_balance(cache_service, directus_service, str(user_id))
        except RuntimeError as exc:
            return RunCodeResponse(status="error", error=str(exc))
        current_user = SimpleNamespace(
            id=str(user_id),
            username="assistant-code-run-user",
            vault_key_id=str(user_vault_key_id),
            credits=credits,
        )

        if request.files:
            target_embed_id, created_embed_ids = await create_code_embeds_for_assistant(
                files=files,
                target_path=target_path,
                chat_id=str(chat_id),
                message_id=str(message_id),
                user_id=str(user_id),
                user_vault_key_id=str(user_vault_key_id),
                cache_service=cache_service,
                directus_service=directus_service,
                encryption_service=encryption_service,
            )
        else:
            files, target_path = await collect_code_files_for_assistant(
                chat_id=str(chat_id),
                target_embed_id=target_embed_id,
                client_files=[],
                client_attachments=[],
                selected_embed_ids=request.selected_embed_ids,
                current_user=current_user,
                cache_service=cache_service,
                directus_service=directus_service,
                encryption_service=encryption_service,
            )
        execution = await start_code_run_for_assistant(
            current_user=current_user,
            cache_service=cache_service,
            files=files,
            target_path=target_path,
            enable_internet=request.enable_internet,
            chat_id=str(chat_id),
            target_embed_id=target_embed_id,
            message_id=str(message_id),
            dependency_installs=_dependency_installs(request.dependency_installs),
            api_key_hash=kwargs.get("api_key_hash"),
            device_hash=kwargs.get("device_hash"),
            assistant_async_task=True,
        )
        return RunCodeResponse(
            execution_id=execution.execution_id,
            task_id=execution.execution_id,
            embed_id=target_embed_id,
            target_embed_id=target_embed_id,
            created_embed_ids=created_embed_ids,
            status="processing",
            target_filename=execution.target_filename,
            files=list(execution.files),
            credits_per_minute=execution.credits_per_minute,
            stream_path=f"/v1/code/run/{execution.execution_id}/stream",
            status_path=f"/v1/code/run/{execution.execution_id}",
        )
