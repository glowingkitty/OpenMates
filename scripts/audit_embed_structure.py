#!/usr/bin/env python3
"""
Audit embed preview/fullscreen structure for parent-child embed flows.

This script validates the generated embed registry against the frontend files:
parents that declare child embed types should have preview/fullscreen components,
child types should have preview/fullscreen components, and parent fullscreens
should use the shared SearchResultsTemplate drilldown contract unless explicitly
reviewed as a custom exception.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EMBEDS_ROOT = REPO_ROOT / "frontend/packages/ui/src/components/embeds"
REGISTRY_PATH = REPO_ROOT / "frontend/packages/ui/src/data/embedRegistry.generated.ts"


@dataclass(frozen=True)
class RegistryMaps:
    normalization: dict[str, str]
    child_types: dict[str, str]
    previews: dict[str, str]
    fullscreens: dict[str, str]


@dataclass(frozen=True)
class AuditResult:
    issues: list[str]
    warnings: list[str]


def extract_record(source: str, name: str) -> dict[str, str]:
    pattern = re.compile(
        rf"export const {re.escape(name)}: Record<[^>]+> = \{{(?P<body>.*?)\n\}};",
        re.DOTALL,
    )
    match = pattern.search(source)
    if not match:
        raise ValueError(f"Could not find registry map {name}")

    entries: dict[str, str] = {}
    for key, value in re.findall(r'"([^"]+)"\s*:\s*"([^"]+)"', match.group("body")):
        entries[key] = value
    return entries


def load_registry() -> RegistryMaps:
    source = REGISTRY_PATH.read_text(encoding="utf-8")
    return RegistryMaps(
        normalization=extract_record(source, "EMBED_TYPE_NORMALIZATION_MAP"),
        child_types=extract_record(source, "EMBED_CHILD_TYPE_MAP"),
        previews=extract_record(source, "EMBED_PREVIEW_COMPONENTS"),
        fullscreens=extract_record(source, "EMBED_FULLSCREEN_COMPONENTS"),
    )


def component_path(relative_path: str) -> Path:
    return EMBEDS_ROOT / relative_path


def file_contains(path: Path, needle: str) -> bool:
    if not path.exists():
        return False
    return needle in path.read_text(encoding="utf-8")


def audit_embed_structure() -> AuditResult:
    registry = load_registry()
    issues: list[str] = []
    warnings: list[str] = []

    for parent_key, child_server_type in sorted(registry.child_types.items()):
        parent_registry_key = f"app:{parent_key.replace(':', ':')}"
        child_registry_key = registry.normalization.get(child_server_type, child_server_type)

        parent_preview = registry.previews.get(parent_registry_key)
        parent_fullscreen = registry.fullscreens.get(parent_registry_key)
        child_preview = registry.previews.get(child_registry_key)
        child_fullscreen = registry.fullscreens.get(child_registry_key)

        label = f"{parent_key} -> {child_server_type} ({child_registry_key})"

        if not parent_preview:
            issues.append(f"{label}: missing parent preview registry entry {parent_registry_key}")
        elif not component_path(parent_preview).exists():
            issues.append(f"{label}: parent preview file missing: {parent_preview}")

        if not parent_fullscreen:
            issues.append(f"{label}: missing parent fullscreen registry entry {parent_registry_key}")
            continue

        parent_fullscreen_path = component_path(parent_fullscreen)
        if not parent_fullscreen_path.exists():
            issues.append(f"{label}: parent fullscreen file missing: {parent_fullscreen}")
            continue

        if not child_preview:
            issues.append(f"{label}: missing child preview registry entry {child_registry_key}")
        elif not component_path(child_preview).exists():
            issues.append(f"{label}: child preview file missing: {child_preview}")

        if not child_fullscreen:
            issues.append(f"{label}: missing child fullscreen registry entry {child_registry_key}")
        elif not component_path(child_fullscreen).exists():
            issues.append(f"{label}: child fullscreen file missing: {child_fullscreen}")

        source = parent_fullscreen_path.read_text(encoding="utf-8")
        uses_search_template = "<SearchResultsTemplate" in source
        uses_map_template = "<EntryWithMapTemplate" in source
        uses_child_transformer = "childEmbedTransformer" in source
        renders_result_card = "#snippet resultCard" in source
        renders_child_fullscreen = "#snippet childFullscreen" in source
        passes_on_select = "onSelect" in source and ("onFullscreen" in source or "{onSelect}" in source)

        if not uses_child_transformer:
            issues.append(f"{label}: parent fullscreen does not pass childEmbedTransformer")

        if not uses_search_template and not uses_map_template:
            warnings.append(
                f"{label}: parent fullscreen {parent_fullscreen} does not use SearchResultsTemplate; "
                "custom drilldown must be reviewed for selected child state, overlay, close, prev/next, and deep-link behavior"
            )
        elif uses_search_template:
            if not renders_result_card:
                issues.append(f"{label}: SearchResultsTemplate parent is missing #snippet resultCard")
            if not renders_child_fullscreen:
                issues.append(f"{label}: SearchResultsTemplate parent is missing #snippet childFullscreen")
            if not passes_on_select:
                issues.append(f"{label}: resultCard does not appear to pass onSelect to child preview onFullscreen")
        elif uses_map_template:
            if "<ChildEmbedOverlay" not in source:
                issues.append(f"{label}: EntryWithMapTemplate parent is missing ChildEmbedOverlay for result drilldown")
            if "onAutoOpenChild" not in source:
                issues.append(f"{label}: EntryWithMapTemplate parent is missing onAutoOpenChild deep-link wiring")
            if "onChildrenLoaded" not in source:
                issues.append(f"{label}: EntryWithMapTemplate parent is missing onChildrenLoaded state wiring")

    return AuditResult(issues=issues, warnings=warnings)


def main() -> int:
    result = audit_embed_structure()

    if result.issues:
        print("EMBED STRUCTURE ISSUES")
        for issue in result.issues:
            print(f"- {issue}")

    if result.warnings:
        print("EMBED STRUCTURE WARNINGS")
        for warning in result.warnings:
            print(f"- {warning}")

    if not result.issues and not result.warnings:
        print("Embed structure audit passed.")
        return 0

    print(f"Summary: {len(result.issues)} issue(s), {len(result.warnings)} warning(s).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
