# backend/apps/design/skills/get_design_skill.py
#
# design.get_design: read a Figma file or selected nodes through a connected
# account and return structure, styles, optional variables and image exports,
# plus a code handoff built only from values present in the file.
# Call budget per request: one content call, at most one images call and at
# most one variables call; 429 is never retried.
#
# Spec: specifications/features/app-skills/design-figma/specification.yml

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.figma.client import (
    MAX_NODE_IDS,
    FigmaClient,
    FigmaInputError,
    parse_figma_reference,
)
from backend.shared.providers.figma.errors import FigmaProviderError
from backend.shared.python_utils.connected_account_tokens import (
    access_token_for_handle,
    summarize_errors,
)
from backend.shared.python_utils.figma_design_handoff import (
    IMAGE_URL_EXPIRY_DAYS,
    build_code_handoff,
    list_frames,
    simplify_nodes,
)

IncludeKind = Literal["frames", "components", "styles", "variables", "images"]
_VARIABLE_STATUS = {
    "figma_plan_limited": "plan_limited",
    "figma_missing_scope": "not_granted",
    "figma_forbidden": "not_granted",
}


class DesignRequest(BaseModel):
    access_token_handle: str = Field(min_length=1)
    connected_account_id: str | None = None
    figma_url: str | None = Field(default=None, max_length=2048)
    file_key: str | None = Field(default=None, max_length=64)
    node_ids: list[str] = Field(default_factory=list, max_length=MAX_NODE_IDS)
    include: list[IncludeKind] = Field(default_factory=lambda: ["frames", "components", "styles"])
    image_format: Literal["png", "jpg", "svg", "pdf"] = "png"
    image_scale: float = Field(default=1.0, ge=0.5, le=2.0)
    depth: int = Field(default=2, ge=1, le=4)

    @model_validator(mode="after")
    def _needs_target(self) -> "DesignRequest":
        if not (self.figma_url or self.file_key):
            raise ValueError("figma_url or file_key is required")
        return self


class GetDesignRequest(BaseModel):
    requests: list[dict[str, Any]] = Field(min_length=1, max_length=3)  # each request costs Figma Tier 1 calls


class GetDesignResponse(BaseModel):
    results: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    external_data: bool = True


def _input_error(code: str, message: str) -> dict[str, Any]:
    return {"error": f"figma_{code}", "message": message, "reconnect_required": False, "retryable": False}


def _file_info(payload: dict[str, Any], file_key: str) -> dict[str, Any]:
    return {
        "file_key": file_key, "name": payload.get("name"), "last_modified": payload.get("lastModified"),
        "version": payload.get("version"), "editor_type": payload.get("editorType"),
        "link": f"https://www.figma.com/design/{file_key}",
    }


async def _variables(client: Any, file_key: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        payload = await client.get_local_variables(file_key)
    except FigmaProviderError as error:
        status = _VARIABLE_STATUS.get(error.code, "unavailable")
        return {"status": status, "error": error.code, "variables": []}, None
    meta = payload.get("meta") or {}
    collections = meta.get("variableCollections") or {}
    items = []
    for variable_id, variable in (meta.get("variables") or {}).items():
        collection = collections.get(variable.get("variableCollectionId")) or {}
        values = variable.get("valuesByMode") or {}
        items.append({
            "id": variable_id, "name": variable.get("name"), "resolved_type": variable.get("resolvedType"),
            "collection": collection.get("name"), "modes": collection.get("modes"),
            "values_by_mode": values,
        })
    return {"status": "ok", "variables": items}, meta


async def _images(
    client: Any, file_key: str, ids: list[str], item: DesignRequest,
) -> dict[str, str | None] | dict[str, Any]:
    if not ids:
        return {"status": "no_frames", "items": []}
    try:
        payload = await client.get_images(file_key, ids, item.image_format, item.image_scale)
    except FigmaProviderError as error:
        return {"status": "unavailable", "error": error.code, "items": []}
    return {"status": "ok", "urls": payload.get("images") or {}}


async def _read(item: DesignRequest, client: Any) -> dict[str, Any]:
    file_key, node_ids = parse_figma_reference(item.figma_url, item.file_key, item.node_ids)
    include = set(item.include)
    components: dict[str, Any] = {}
    styles: dict[str, Any] = {}
    missing: list[str] = []
    if node_ids:
        payload = await client.get_nodes(file_key, node_ids, item.depth)
        entries = payload.get("nodes") or {}
        roots = []
        for node_id in node_ids:
            entry = entries.get(node_id)
            if not entry:
                missing.append(node_id)
                continue
            roots.append(entry["document"])
            components.update(entry.get("components") or {})
            styles.update(entry.get("styles") or {})
        if not roots:
            raise FigmaProviderError("figma_not_found", status=404)
    else:
        payload = await client.get_file(file_key, item.depth)
        roots = [payload.get("document") or {}]
        components, styles = payload.get("components") or {}, payload.get("styles") or {}
    nodes, truncated = simplify_nodes(roots)
    frames = list_frames(roots)

    variables: dict[str, Any] = {"status": "not_requested", "variables": []}
    meta: dict[str, Any] | None = None
    if "variables" in include:
        variables, meta = await _variables(client, file_key)

    images: dict[str, Any] = {"status": "not_requested", "items": []}
    urls: dict[str, str | None] = {}
    if "images" in include:
        ids = node_ids or [frame["id"] for frame in frames[:MAX_NODE_IDS]]
        outcome = await _images(client, file_key, ids, item)
        if outcome.get("status") == "ok":
            urls = outcome["urls"]
            images = {
                "status": "ok", "format": item.image_format, "expires_in_days": IMAGE_URL_EXPIRY_DAYS,
                "items": [{"node_id": nid, "url": url} for nid, url in urls.items()],
            }
        else:
            images = outcome

    handoff = build_code_handoff(
        _file_info(payload, file_key), nodes, components, styles, meta, urls,
        frames=frames, image_format=item.image_format,
    )
    return {
        "file": _file_info(payload, file_key),
        "frames": frames if "frames" in include else [],
        "nodes": nodes, "truncated": truncated, "missing_node_ids": missing,
        "components": [{"id": cid, **c} for cid, c in components.items()] if "components" in include else [],
        "styles": [{"id": sid, **s} for sid, s in styles.items()] if "styles" in include else [],
        "variables": variables, "images": images, "code_handoff": handoff,
    }


class GetDesignSkill(BaseSkill):
    """Read a Figma design through a broker-authorized connected account."""

    async def execute(
        self, requests: list[dict[str, Any]],
        connected_account_access_tokens: dict[str, str] | None = None,
        figma_client_factory: Any | None = None, **_: Any,
    ) -> GetDesignResponse:
        normalized = GetDesignRequest(requests=requests)
        factory = figma_client_factory or FigmaClient
        results: list[dict[str, Any]] = []
        for raw in normalized.requests:
            try:
                item = DesignRequest(**raw)
                client = factory(access_token=access_token_for_handle(
                    item.access_token_handle, connected_account_access_tokens,
                ))
                results.append(await _read(item, client))
            except FigmaProviderError as error:
                results.append(error.to_result())
            except FigmaInputError as error:
                results.append(_input_error(error.code, str(error)))
            except ValidationError as error:
                fields = sorted({".".join(str(part) for part in e["loc"]) for e in error.errors()})
                results.append(_input_error("invalid_input", "Invalid or missing fields: " + ", ".join(fields)))
        return GetDesignResponse(results=results, error=summarize_errors(results))
