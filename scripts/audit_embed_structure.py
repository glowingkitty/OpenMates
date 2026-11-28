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


def svelte_source(path: Path) -> str:
    return re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)


def extract_embed_header_cta_snippets(source: str) -> list[str]:
    return re.findall(r"\{#snippet\s+embedHeaderCta\([^)]*\)\}(.*?)\{/snippet\}", source, re.DOTALL)


def extract_svelte_component_attrs(source: str, component_name: str) -> list[tuple[int, str]]:
    attrs: list[tuple[int, str]] = []
    tag_start = f"<{component_name}"
    search_from = 0
    while True:
        start = source.find(tag_start, search_from)
        if start == -1:
            break

        i = start + len(tag_start)
        if i == len(source) or not (source[i].isspace() or source[i] in "/>"):
            search_from = i
            continue
        quote: str | None = None
        brace_depth = 0
        while i < len(source):
            char = source[i]
            if quote:
                if char == quote and source[i - 1] != "\\":
                    quote = None
            elif char in {'"', "'"}:
                quote = char
            elif char == "{":
                brace_depth += 1
            elif char == "}":
                brace_depth = max(0, brace_depth - 1)
            elif char == ">" and brace_depth == 0:
                attrs.append((start, source[start + len(tag_start):i]))
                search_from = i + 1
                break
            i += 1
        else:
            search_from = start + len(tag_start)
    return attrs


def count_possible_primary_header_ctas(snippet: str) -> int:
    controls = re.finditer(r"\{([#:/](?:if|else|each|await|then|catch))\b", snippet)
    events = [(match.start(), match[1]) for match in controls]
    for start, attrs in extract_svelte_component_attrs(snippet, "EmbedHeaderCtaButton"):
        variant = re.search(r"\bvariant\s*=\s*(?P<value>\{[^}]+\}|\"([^\"]+)\"|'([^']+)')", attrs)
        if variant:
            raw_value = variant.group("value").strip("{}\"'")
            if raw_value != "primary":
                continue
        events.append((start, "primary"))

    # Siblings can render together. Branches of one block cannot. A CTA in an
    # each loop may render more than once, regardless of its test ID.
    branches = [[0]]
    for _, event in sorted(events):
        if event == "primary":
            branches[-1][-1] += 1
        elif event.startswith("#"):
            branches.append([0])
        elif event.startswith(":") and len(branches) > 1:
            branches[-1].append(0)
        elif event.startswith("/") and len(branches) > 1:
            completed = branches.pop()
            if event == "/each" and completed[0]:
                completed[0] = max(2, completed[0])
            branches[-1][-1] += max(completed)
    return sum(max(block) for block in branches)


def audit_fullscreen_primary_ctas(embeds_root: Path = EMBEDS_ROOT) -> list[str]:
    issues: list[str] = []
    for path in sorted(embeds_root.glob("**/*Fullscreen.svelte")):
        source = svelte_source(path)
        for snippet in extract_embed_header_cta_snippets(source):
            primary_count = count_possible_primary_header_ctas(snippet)
            if primary_count > 1:
                relative = path.relative_to(embeds_root)
                issues.append(
                    f"{relative}: embedHeaderCta exposes {primary_count} possible primary EmbedHeaderCtaButton actions; "
                    "fullscreen headers may show at most one main CTA. Move secondary controls into content or mark them variant=\"secondary\"."
                )
    return issues


def preview_uses_unified_base(path: Path) -> bool:
    return file_contains(path, "<UnifiedEmbedPreview")


def fullscreen_uses_approved_base(path: Path) -> bool:
    if not path.exists():
        return False
    source = svelte_source(path)
    bases = ("UnifiedEmbedFullscreen", "SearchResultsTemplate", "EntryWithMapTemplate")
    if any(extract_svelte_component_attrs(source, base) for base in bases):
        return True
    # The documented result-detail adapter must itself still render the shared shell.
    adapter = path.parents[1] / "ResultEmbedFullscreen.svelte"
    return (
        bool(extract_svelte_component_attrs(source, "ResultEmbedFullscreen"))
        and bool(re.search(r"""\bimport\s+ResultEmbedFullscreen\s+from\s+['"]\.\./ResultEmbedFullscreen\.svelte['"]""", source))
        and adapter.exists()
        and bool(extract_svelte_component_attrs(svelte_source(adapter), "UnifiedEmbedFullscreen"))
    )


def fullscreen_reaches_shared_shell(path: Path, visited: set[Path]) -> bool:
    """Follow mounted, local Svelte adapters from a registered fullscreen."""
    if path in visited or not path.is_file():
        return False
    visited.add(path)
    source = svelte_source(path)
    if extract_svelte_component_attrs(source, "UnifiedEmbedFullscreen"):
        return True
    imports = re.findall(r"""import\s+(\w+)\s+from\s+['"]([.][^'"]+\.svelte)['"]""", source)
    return any(
        extract_svelte_component_attrs(source, name)
        and fullscreen_reaches_shared_shell((path.parent / relative).resolve(), visited)
        for name, relative in imports
    )


def audit_registered_fullscreen_shells(registry: RegistryMaps) -> list[str]:
    """Every registered renderer reaches the single fullscreen shell."""
    issues = []
    for renderer in sorted(set(registry.fullscreens.values())):
        path = component_path(renderer)
        if not fullscreen_reaches_shared_shell(path, set()):
            issues.append(f"{renderer}: registered fullscreen does not render the shared shell")
        elif extract_svelte_component_attrs(svelte_source(path), "EmbedHeader"):
            issues.append(f"{renderer}: local header duplicates the shared fullscreen identity")
    return issues


# These specialized parents present results in place. Validate their actual
# loading and presentation wiring instead of expecting an overlay callback.
INLINE_PARENT_CONTRACTS = {
    ("mail:search", "mail/MailSearchEmbedFullscreen.svelte"): (
        "UnifiedEmbedFullscreen", ("embedIds={", "childEmbedTransformer={"),
        ("data.focusChildEmbedId", "{#snippet content({ children })}"),
    ),
    ("maps:search", "maps/MapsSearchEmbedFullscreen.svelte"): (
        "EmbedsMapView", ("sourceRefs={", "highlightRefs={", 'interactionMode="select"'),
        ("data.focusChildEmbedId",),
    ),
    ("videos:create", "videos/VideoCreateEmbedFullscreen.svelte"): (
        "UnifiedEmbedFullscreen", ("currentEmbedId={",),
        ("data.decodedContent", "dc.remotion_source", "dc.files", "fetchAndDecryptAudio(", "<VideoTimeline"),
    ),
}


def missing_inline_parent_wiring(parent_key: str, path: str, source: str) -> list[str] | None:
    contract = INLINE_PARENT_CONTRACTS.get((parent_key, path))
    if contract is None:
        return None
    component, required_attrs, required_source = contract
    missing = [token for token in required_source if token not in source]
    if not extract_svelte_component_attrs(source, "UnifiedEmbedFullscreen"):
        missing.append("UnifiedEmbedFullscreen")
    if not any(
        all(token in attrs for token in required_attrs)
        for _, attrs in extract_svelte_component_attrs(source, component)
    ):
        missing.append(f"{component} wired with {', '.join(required_attrs)}")
    return missing


def audit_embed_structure() -> AuditResult:
    registry = load_registry()
    issues: list[str] = []
    warnings: list[str] = []

    issues.extend(audit_fullscreen_primary_ctas())
    issues.extend(audit_registered_fullscreen_shells(registry))

    for parent_key, child_server_type in sorted(registry.child_types.items()):
        parent_registry_key = f"app:{parent_key}"
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
        elif not preview_uses_unified_base(component_path(parent_preview)):
            issues.append(f"{label}: parent preview {parent_preview} does not use UnifiedEmbedPreview")

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
        elif not preview_uses_unified_base(component_path(child_preview)):
            issues.append(f"{label}: child preview {child_preview} does not use UnifiedEmbedPreview")

        if not child_fullscreen:
            issues.append(f"{label}: missing child fullscreen registry entry {child_registry_key}")
        elif not component_path(child_fullscreen).exists():
            issues.append(f"{label}: child fullscreen file missing: {child_fullscreen}")
        elif not fullscreen_uses_approved_base(component_path(child_fullscreen)):
            issues.append(
                f"{label}: child fullscreen {child_fullscreen} does not use UnifiedEmbedFullscreen, "
                "ResultEmbedFullscreen, SearchResultsTemplate, or EntryWithMapTemplate"
            )

        source = svelte_source(parent_fullscreen_path)
        uses_search_template = "<SearchResultsTemplate" in source
        uses_map_template = "<EntryWithMapTemplate" in source
        uses_child_transformer = "childEmbedTransformer" in source
        renders_result_card = "#snippet resultCard" in source
        renders_child_fullscreen = "#snippet childFullscreen" in source
        passes_on_select = "onSelect" in source and ("onFullscreen" in source or "{onSelect}" in source)

        missing_inline = missing_inline_parent_wiring(parent_key, parent_fullscreen, source)
        if missing_inline is not None and not uses_search_template and not uses_map_template:
            for required in missing_inline:
                if required not in source:
                    issues.append(f"{label}: inline fullscreen is missing {required}")
            continue

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
