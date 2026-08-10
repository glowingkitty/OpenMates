# backend/core/api/app/routes/code_notebook_execution.py
#
# First-party notebook execution route for Code app notebook embeds.
# Notebook source stays an encrypted embed; this route only validates transient
# client-supplied or recent cached nbformat content, builds an inert Python
# runner bundle, and delegates sandbox lifecycle/billing to existing Code Run.
# Runtime outputs are synchronized separately via notebook_run_outputs sidecars.

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from pydantic import BaseModel, Field, field_validator
from toon_format import decode as toon_decode

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user
from backend.core.api.app.routes.auth_ws import get_current_user_ws
from backend.core.api.app.routes.code_execution import (
    CLIENT_CONTENT_REQUIRED_CODE,
    CODE_RUN_START_RATE_LIMIT,
    MAX_FILE_CHARS,
    MAX_TOTAL_CHARS,
    RUN_CREDITS_PER_MINUTE,
    CodeRunDependencyInstall,
    _get_embed_metadata,
    _looks_like_secret,
    get_cache_service,
    get_code_run_status,
    get_directus_service,
    get_encryption_service,
    start_code_run_execution,
    stream_code_run_status,
)
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.embed_service import EmbedService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.utils.encryption import EncryptionService


router = APIRouter(prefix="/v1/code/notebooks/run", tags=["Code Notebooks"])

MAX_NOTEBOOK_CELLS = 200
MAX_NOTEBOOK_JSON_CHARS = MAX_TOTAL_CHARS
NOTEBOOK_FILENAME = "notebook.ipynb"
NOTEBOOK_RUNNER_FILENAME = "openmates_notebook_runner.py"
PUBLIC_EXAMPLE_NOTEBOOK_EMBED_IDS: dict[str, frozenset[str]] = {
    "example-open-meteo-weather-notebook": frozenset({"b7ea93b1-e497-41bc-b952-bb7495610e5f"}),
}
NOTEBOOK_REQUIREMENTS = (
    "nbformat",
    "nbclient",
    "ipykernel",
    "pandas",
    "requests",
    "matplotlib",
)


class NotebookRunStartRequest(BaseModel):
    chat_id: str = Field(min_length=1)
    notebook_embed_id: str = Field(min_length=1)
    run_scope: Literal["all", "cells"] = "all"
    cell_indices: list[int] | None = Field(default=None, max_length=MAX_NOTEBOOK_CELLS)
    enable_internet: bool = True
    dependency_installs: list[CodeRunDependencyInstall] = Field(default_factory=list, max_length=20)
    client_notebook: dict[str, Any] | None = None
    source_version: str | None = Field(default=None, max_length=128)

    @field_validator("cell_indices")
    @classmethod
    def validate_cell_indices(cls, indices: list[int] | None) -> list[int] | None:
        if indices is None:
            return None
        if not indices:
            raise ValueError("cell_indices cannot be empty when run_scope is cells")
        if any(index < 0 for index in indices):
            raise ValueError("cell_indices must be zero-based positive integers")
        return indices


class NotebookRunStartResponse(BaseModel):
    execution_id: str
    status: str
    notebook_embed_id: str
    selected_cell_indices: list[int]
    source_version: str | None = None
    credits_per_minute: int = RUN_CREDITS_PER_MINUTE
    stream_path: str
    status_path: str


def _source_to_text(source: Any) -> str:
    if isinstance(source, str):
        return source
    if isinstance(source, list) and all(isinstance(part, str) for part in source):
        return "".join(source)
    return ""


def _notebook_language(metadata: dict[str, Any]) -> str:
    kernelspec = metadata.get("kernelspec") if isinstance(metadata.get("kernelspec"), dict) else {}
    language_info = metadata.get("language_info") if isinstance(metadata.get("language_info"), dict) else {}
    for value in (kernelspec.get("language"), language_info.get("name"), kernelspec.get("name")):
        if isinstance(value, str) and value.strip():
            normalized = value.strip().lower()
            if normalized in {"python", "python3", "py"}:
                return "python"
            return normalized
    return "unknown"


def _notebook_content_from_embed_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    notebook = payload.get("notebook")
    if isinstance(notebook, dict):
        return notebook
    content = payload.get("content")
    if isinstance(content, dict):
        return content
    if isinstance(content, str) and content.strip():
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return payload if "cells" in payload else None


def _is_public_example_notebook_embed(chat_id: str, notebook_embed_id: str) -> bool:
    return notebook_embed_id in PUBLIC_EXAMPLE_NOTEBOOK_EMBED_IDS.get(chat_id, frozenset())


def validate_notebook_payload(
    payload: dict[str, Any],
    *,
    filename: str | None = None,
    require_python: bool = False,
) -> dict[str, Any]:
    notebook = _notebook_content_from_embed_payload(payload)
    if not isinstance(notebook, dict):
        raise HTTPException(status_code=422, detail="Notebook payload must be a nbformat object")

    try:
        encoded = json.dumps(notebook, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Notebook payload must be JSON serializable") from exc
    if len(encoded) > MAX_NOTEBOOK_JSON_CHARS:
        raise HTTPException(status_code=422, detail="Notebook is too large to run")
    if _looks_like_secret(encoded):
        raise HTTPException(status_code=422, detail="Notebook appears to contain secrets and cannot be sent to the sandbox")

    if not isinstance(notebook.get("nbformat"), int):
        raise HTTPException(status_code=422, detail="Notebook is missing nbformat")
    if not isinstance(notebook.get("nbformat_minor"), int):
        raise HTTPException(status_code=422, detail="Notebook is missing nbformat_minor")
    metadata = notebook.get("metadata")
    if not isinstance(metadata, dict):
        raise HTTPException(status_code=422, detail="Notebook metadata must be an object")
    cells = notebook.get("cells")
    if not isinstance(cells, list) or not cells:
        raise HTTPException(status_code=422, detail="Notebook cells must be a non-empty list")
    if len(cells) > MAX_NOTEBOOK_CELLS:
        raise HTTPException(status_code=422, detail="Notebook has too many cells")

    for index, cell in enumerate(cells):
        if not isinstance(cell, dict):
            raise HTTPException(status_code=422, detail=f"Notebook cell {index} must be an object")
        cell_type = cell.get("cell_type")
        if cell_type not in {"markdown", "code", "raw"}:
            raise HTTPException(status_code=422, detail=f"Notebook cell {index} has unsupported cell_type")
        if not isinstance(cell.get("metadata", {}), dict):
            raise HTTPException(status_code=422, detail=f"Notebook cell {index} metadata must be an object")
        if cell_type == "code" and not isinstance(cell.get("outputs", []), list):
            raise HTTPException(status_code=422, detail=f"Notebook code cell {index} outputs must be a list")
        source = _source_to_text(cell.get("source", ""))
        if len(source) > MAX_FILE_CHARS:
            raise HTTPException(status_code=422, detail=f"Notebook cell {index} is too large")

    language = _notebook_language(metadata)
    is_python = language == "python"
    if require_python and not is_python:
        raise HTTPException(status_code=422, detail="Python notebooks only in v1")

    safe_filename = filename or payload.get("filename") or NOTEBOOK_FILENAME
    if not isinstance(safe_filename, str) or not safe_filename.strip():
        safe_filename = NOTEBOOK_FILENAME
    safe_filename = PurePosixPath(safe_filename.replace("\\", "/")).name or NOTEBOOK_FILENAME
    if not safe_filename.endswith(".ipynb"):
        safe_filename = f"{safe_filename}.ipynb"

    return {
        "notebook": notebook,
        "filename": safe_filename,
        "cell_count": len(cells),
        "language": language,
        "is_python": is_python,
    }


def _selected_code_cell_indices(notebook: dict[str, Any], run_scope: str, cell_indices: list[int] | None) -> list[int]:
    cells = notebook["cells"]
    code_indices = [index for index, cell in enumerate(cells) if cell.get("cell_type") == "code" and _source_to_text(cell.get("source", "")).strip()]
    if not code_indices:
        raise HTTPException(status_code=422, detail="Notebook has no runnable Python code cells")
    if run_scope == "all":
        return code_indices
    if not cell_indices:
        raise HTTPException(status_code=422, detail="cell_indices are required when run_scope is cells")
    invalid = [index for index in cell_indices if index not in code_indices]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Invalid runnable notebook cell indices: {invalid}")
    return list(dict.fromkeys(cell_indices))


def _notebook_dependency_installs(dependency_installs: list[CodeRunDependencyInstall]) -> list[CodeRunDependencyInstall]:
    packages = list(NOTEBOOK_REQUIREMENTS)
    seen = {package.lower() for package in packages}
    for install in dependency_installs:
        if install.ecosystem != "python":
            raise HTTPException(status_code=422, detail="Python notebooks only support Python dependencies in v1")
        for package in install.packages:
            package_id = re.split(r"[<>=!~]", package, 1)[0].strip().lower()
            if package_id and package_id not in seen:
                packages.append(package)
                seen.add(package_id)
    return [CodeRunDependencyInstall(ecosystem="python", packages=packages)]


def _requirement_lines(dependency_installs: list[CodeRunDependencyInstall]) -> str:
    packages = _notebook_dependency_installs(dependency_installs)[0].packages
    return "\n".join(packages) + "\n"


def _runner_source(selected_indices: list[int]) -> str:
    selected_json = json.dumps(selected_indices)
    return f'''import json
import sys
import traceback

import nbformat
from nbclient import NotebookClient

NOTEBOOK_PATH = {NOTEBOOK_FILENAME!r}
SELECTED_INDICES = set({selected_json})


def main():
    notebook = nbformat.read(NOTEBOOK_PATH, as_version=4)
    for index, cell in enumerate(notebook.cells):
        if cell.get("cell_type") != "code" or index not in SELECTED_INDICES:
            cell["source"] = ""
    client = NotebookClient(notebook, timeout=300, kernel_name="python3", allow_errors=True)
    status = "finished"
    try:
        client.execute()
    except Exception as exc:
        status = "failed"
        print(f"Notebook execution failed: {{exc}}", file=sys.stderr)
        traceback.print_exc()

    cell_outputs = []
    for index in sorted(SELECTED_INDICES):
        cell = notebook.cells[index]
        cell_outputs.append({{
            "cell_index": index,
            "execution_count": cell.get("execution_count"),
            "outputs": cell.get("outputs", []),
        }})
    payload = {{
        "type": "notebook_run_output",
        "status": status,
        "selected_cell_indices": sorted(SELECTED_INDICES),
        "cell_outputs": cell_outputs,
    }}
    print("OPENMATES_NOTEBOOK_OUTPUT_JSON_START")
    print(json.dumps(payload, default=str))
    print("OPENMATES_NOTEBOOK_OUTPUT_JSON_END")
    if status != "finished":
        sys.exit(1)


if __name__ == "__main__":
    main()
'''


def build_notebook_run_bundle(
    *,
    notebook: dict[str, Any],
    notebook_embed_id: str,
    run_scope: Literal["all", "cells"],
    cell_indices: list[int] | None,
    dependency_installs: list[CodeRunDependencyInstall],
) -> tuple[list[dict[str, Any]], str, list[int]]:
    validated = validate_notebook_payload(notebook, require_python=True)
    selected_indices = _selected_code_cell_indices(validated["notebook"], run_scope, cell_indices)
    notebook_json = json.dumps(validated["notebook"], ensure_ascii=False, indent=2)
    files = [
        {
            "path": NOTEBOOK_FILENAME,
            "content": notebook_json,
            "language": "json",
            "is_target": False,
            "source_embed_id": notebook_embed_id,
        },
        {
            "path": "requirements.txt",
            "content": _requirement_lines(dependency_installs),
            "language": "",
            "is_target": False,
            "source_embed_id": notebook_embed_id,
        },
        {
            "path": NOTEBOOK_RUNNER_FILENAME,
            "content": _runner_source(selected_indices),
            "language": "python",
            "is_target": True,
            "source_embed_id": notebook_embed_id,
        },
    ]
    return files, NOTEBOOK_RUNNER_FILENAME, selected_indices


async def verify_notebook_embed_access(
    chat_id: str,
    notebook_embed_id: str,
    current_user: User,
    cache_service: CacheService,
    directus_service: DirectusService,
) -> bool:
    embed_ids = await cache_service.get_chat_embed_ids(chat_id)
    if notebook_embed_id in embed_ids:
        return True
    metadata = await _get_embed_metadata(notebook_embed_id, cache_service, directus_service)
    if not isinstance(metadata, dict):
        return False
    expected_user_hash = hashlib.sha256(current_user.id.encode()).hexdigest()
    expected_chat_hash = hashlib.sha256(chat_id.encode()).hexdigest()
    return metadata.get("hashed_user_id") == expected_user_hash and metadata.get("hashed_chat_id") == expected_chat_hash


async def _load_cached_notebook(
    chat_id: str,
    notebook_embed_id: str,
    current_user: User,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
) -> dict[str, Any]:
    metadata = await _get_embed_metadata(notebook_embed_id, cache_service, directus_service)
    embed_service = EmbedService(cache_service=cache_service, directus_service=directus_service, encryption_service=encryption_service)
    cached_toon = await embed_service._get_cached_embed_toon(notebook_embed_id, current_user.vault_key_id, "[NOTEBOOK_RUN] ")
    if cached_toon:
        try:
            decoded = toon_decode(cached_toon)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Cached notebook content is invalid") from exc
        if isinstance(decoded, dict):
            return decoded
    if isinstance(metadata, dict):
        expected_user_hash = hashlib.sha256(current_user.id.encode()).hexdigest()
        expected_chat_hash = hashlib.sha256(chat_id.encode()).hexdigest()
        if metadata.get("hashed_user_id") == expected_user_hash and metadata.get("hashed_chat_id") == expected_chat_hash:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": CLIENT_CONTENT_REQUIRED_CODE,
                    "message": "Notebook content is not in the recent server cache; resend the decrypted notebook from this device.",
                },
            )
    raise HTTPException(status_code=404, detail="Notebook embed is not available for execution")


@router.post("", response_model=NotebookRunStartResponse)
@limiter.limit(CODE_RUN_START_RATE_LIMIT)
async def start_notebook_run(
    request: Request,
    body: NotebookRunStartRequest,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
    directus_service: DirectusService = Depends(get_directus_service),
    encryption_service: EncryptionService = Depends(get_encryption_service),
) -> NotebookRunStartResponse:
    notebook_payload = body.client_notebook
    has_embed_access = await verify_notebook_embed_access(body.chat_id, body.notebook_embed_id, current_user, cache_service, directus_service)
    if not has_embed_access:
        if not (_is_public_example_notebook_embed(body.chat_id, body.notebook_embed_id) and notebook_payload is not None):
            raise HTTPException(status_code=403, detail="Notebook embed does not belong to this chat")
        validate_notebook_payload(notebook_payload, require_python=True)

    if notebook_payload is None:
        notebook_payload = await _load_cached_notebook(
            body.chat_id,
            body.notebook_embed_id,
            current_user,
            cache_service,
            directus_service,
            encryption_service,
        )
    files, target_path, selected_indices = build_notebook_run_bundle(
        notebook=notebook_payload,
        notebook_embed_id=body.notebook_embed_id,
        run_scope=body.run_scope,
        cell_indices=body.cell_indices,
        dependency_installs=body.dependency_installs,
    )
    dependency_installs = _notebook_dependency_installs(body.dependency_installs)
    start_response = await start_code_run_execution(
        current_user=current_user,
        cache_service=cache_service,
        files=files,
        target_path=target_path,
        enable_internet=body.enable_internet,
        chat_id=body.chat_id,
        target_embed_id=body.notebook_embed_id,
        message_id=None,
        dependency_installs=dependency_installs,
    )
    return NotebookRunStartResponse(
        execution_id=start_response.execution_id,
        status=start_response.status,
        notebook_embed_id=body.notebook_embed_id,
        selected_cell_indices=selected_indices,
        source_version=body.source_version,
        stream_path=f"/v1/code/run/{start_response.execution_id}/stream",
        status_path=f"/v1/code/notebooks/run/{start_response.execution_id}/status",
    )


@router.get("/{execution_id}/status")
async def get_notebook_run_status(
    execution_id: str,
    current_user: User = Depends(get_current_user),
    cache_service: CacheService = Depends(get_cache_service),
) -> dict[str, Any]:
    return await get_code_run_status(execution_id, current_user, cache_service)


@router.websocket("/{execution_id}/stream")
async def stream_notebook_run_status(
    websocket: WebSocket,
    execution_id: str,
    auth_data: dict | None = Depends(get_current_user_ws),
) -> None:
    await stream_code_run_status(websocket, execution_id, auth_data)
