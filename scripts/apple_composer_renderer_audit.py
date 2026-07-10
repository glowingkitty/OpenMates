#!/usr/bin/env python3
"""Audit Apple composer renderer coverage against the generated web registry.

The generated web write-mode renderer map is authoritative. This audit derives
Apple model and read-renderer routing from Swift source, checks the active
pending-composer preview paths separately, and requires maintained fixture,
lifecycle, native-preview, and visual-case evidence for every registered type.
Generic renderers are inventory findings, never native composer parity.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "frontend/packages/ui/src/data/embedRegistry.generated.ts"
DEFAULT_MODELS = REPO_ROOT / "apple/OpenMates/Sources/Core/Models/EmbedModels.swift"
DEFAULT_ROUTER = REPO_ROOT / "apple/OpenMates/Sources/Features/Embeds/Views/EmbedContentView.swift"
DEFAULT_PENDING_PREVIEWS = (
    REPO_ROOT / "apple/OpenMates/Sources/Features/Chat/Views/InlinePreviewView.swift",
    REPO_ROOT / "apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift",
    REPO_ROOT / "apple/OpenMates/Sources/App/MainAppView.swift",
    REPO_ROOT / "apple/OpenMates/Sources/App/OpenMatesApp.swift",
)
DEFAULT_MANIFEST = REPO_ROOT / "shared/composer/fixtures/renderer-coverage.yml"
DEFAULT_COMPOSER_REGISTRY = (
    REPO_ROOT / "apple/OpenMates/Sources/Shared/Composer/AppleComposerRendererRegistry.swift"
)

CLASSIFICATIONS = {
    "specific_native",
    "generic_search",
    "generic_fallback",
    "structural_group_only",
    "missing",
    "not_applicable_to_composer",
}
PARITY_CLASSIFICATIONS = {"specific_native", "structural_group_only", "not_applicable_to_composer"}
REQUIRED_MANIFEST_FIELDS = ("fixture", "lifecycle", "native_preview_mapping", "visual_case")


@dataclass(frozen=True)
class AuditPaths:
    registry: Path
    models: Path
    router: Path
    pending_previews: tuple[Path, ...]
    manifest: Path
    composer_registry: Path | None = None


@dataclass(frozen=True)
class NativeRoute:
    classification: str
    model_case: str | None
    renderer: str | None


@dataclass(frozen=True)
class CoverageIssue:
    embed_type: str
    classification: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class AuditReport:
    registered_count: int
    classifications: dict[str, int]
    issues: tuple[CoverageIssue, ...]
    manifest_errors: tuple[str, ...]

    @property
    def uncovered_count(self) -> int:
        return len(self.issues)

    @property
    def passed(self) -> bool:
        return not self.issues and not self.manifest_errors


def _read(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Missing audit input: {path}")
    return path.read_text(encoding="utf-8")


def _extract_braced_block(text: str, marker: str) -> str:
    marker_index = text.find(marker)
    if marker_index < 0:
        raise ValueError(f"Missing source marker: {marker}")
    start = text.find("{", marker_index)
    if start < 0:
        raise ValueError(f"Missing opening brace after source marker: {marker}")
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index]
    raise ValueError(f"Missing closing brace after source marker: {marker}")


def parse_typescript_string_map(text: str, constant: str) -> dict[str, str]:
    block = _extract_braced_block(text, f"export const {constant}")
    entries = re.findall(r'^\s*"([^"]+)"\s*:\s*"([^"]+)"\s*,?\s*$', block, re.MULTILINE)
    if not entries:
        raise ValueError(f"{constant} contains no string entries")
    return dict(entries)


def parse_apple_models(text: str) -> tuple[dict[str, str], dict[str, str]]:
    block = _extract_braced_block(text, "enum EmbedType:")
    raw_to_case: dict[str, str] = {}
    for match in re.finditer(r'^    case\s+(\w+)(?:\s*=\s*"([^"]+)")?\s*$', block, re.MULTILINE):
        case_name, raw_value = match.groups()
        raw_to_case[raw_value or case_name] = case_name

    aliases: dict[str, str] = {}
    for raw_value, case_name in re.findall(r'case\s+"([^"]+)"\s*:\s*return\s+\.(\w+)', block):
        canonical = next((raw for raw, model_case in raw_to_case.items() if model_case == case_name), None)
        if canonical:
            aliases[raw_value] = canonical
    return raw_to_case, aliases


def parse_apple_routes(text: str) -> dict[str, NativeRoute]:
    switch_block = _extract_braced_block(text, "switch embedType")
    case_matches = list(re.finditer(r'^\s*case\s+([^:]+):\s*$', switch_block, re.MULTILINE))
    routes: dict[str, NativeRoute] = {}
    for index, match in enumerate(case_matches):
        body_end = case_matches[index + 1].start() if index + 1 < len(case_matches) else len(switch_block)
        body = switch_block[match.end() : body_end]
        case_names = re.findall(r'\.(\w+)', match.group(1))
        if "GenericEmbedRenderer" in body:
            classification = "generic_fallback"
            renderer = "GenericEmbedRenderer"
        elif "SearchResultsRenderer" in body:
            classification = "generic_search"
            renderer = "SearchResultsRenderer"
        else:
            renderer_match = re.search(r'\b([A-Z]\w*Renderer)\s*\(', body)
            renderer = renderer_match.group(1) if renderer_match else None
            classification = "specific_native" if renderer else "missing"
        for case_name in case_names:
            routes[case_name] = NativeRoute(classification, case_name, renderer)
    return routes


def parse_pending_preview_types(
    texts: Sequence[str],
    web_normalizations: dict[str, str],
    apple_aliases: dict[str, str],
) -> set[str]:
    raw_types: set[str] = set()
    for text in texts:
        raw_types.update(re.findall(r'embed\.type\s*==\s*"([^"]+)"', text))
    return {
        web_normalizations.get(raw_type, apple_aliases.get(raw_type, raw_type))
        for raw_type in raw_types
    }


def parse_composer_registry_types(text: str) -> tuple[dict[str, str], tuple[str, ...]]:
    entries = re.findall(
        r'^\s*"([^"]+)"\s*:\s*\.init\([^\n]*rendererIdentifier:\s*"([^"]+)"\)',
        text,
        re.MULTILINE,
    )
    routes: dict[str, str] = {}
    errors: list[str] = []
    for embed_type, renderer in entries:
        if "Generic" in renderer:
            errors.append(f"{embed_type}: generic renderer is forbidden")
            continue
        routes[embed_type] = renderer
    return routes, tuple(errors)


def apply_composer_registry(
    routes: dict[str, NativeRoute],
    composer_routes: dict[str, str],
) -> dict[str, NativeRoute]:
    result = dict(routes)
    for embed_type, renderer in composer_routes.items():
        existing = result.get(embed_type)
        classification = "structural_group_only" if embed_type.endswith("-group") else "specific_native"
        result[embed_type] = NativeRoute(
            classification,
            existing.model_case if existing else None,
            renderer,
        )
    return result


def derive_native_routes(
    renderer_map: dict[str, str],
    raw_to_case: dict[str, str],
    apple_routes: dict[str, NativeRoute],
    router_text: str,
) -> dict[str, NativeRoute]:
    routes: dict[str, NativeRoute] = {}
    for embed_type, web_renderer in renderer_map.items():
        if embed_type.endswith("-group") and web_renderer == "GroupRenderer":
            routes[embed_type] = NativeRoute("structural_group_only", None, "GroupedEmbedView")
            continue
        if embed_type == "app-skill-use" and "AppSkillUseRenderer" in router_text:
            # One umbrella route handles many app/skill payloads and has a generic
            # search fallback, so its existence cannot prove type-specific parity.
            routes[embed_type] = NativeRoute("generic_search", None, "AppSkillUseRenderer")
            continue
        model_case = raw_to_case.get(embed_type)
        if model_case is None:
            routes[embed_type] = NativeRoute("missing", None, None)
            continue
        routes[embed_type] = apple_routes.get(model_case, NativeRoute("missing", model_case, None))
    return routes


def load_manifest(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(_read(path)) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def _is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (dict, list, tuple, set)):
        return bool(value)
    return True


def audit(paths: AuditPaths) -> AuditReport:
    registry_text = _read(paths.registry)
    models_text = _read(paths.models)
    router_text = _read(paths.router)
    pending_texts = [_read(path) for path in paths.pending_previews]
    renderer_map = parse_typescript_string_map(registry_text, "EMBED_RENDERER_MAP")
    normalizations = parse_typescript_string_map(registry_text, "EMBED_TYPE_NORMALIZATION_MAP")
    raw_to_case, aliases = parse_apple_models(models_text)
    apple_routes = parse_apple_routes(router_text)
    routes = derive_native_routes(renderer_map, raw_to_case, apple_routes, router_text)
    composer_errors: tuple[str, ...] = ()
    if paths.composer_registry is not None:
        composer_routes, composer_errors = parse_composer_registry_types(_read(paths.composer_registry))
        routes = apply_composer_registry(routes, composer_routes)
        pending_types = set(composer_routes)
    else:
        pending_types = parse_pending_preview_types(pending_texts, normalizations, aliases)
    manifest = load_manifest(paths.manifest)
    manifest_types = manifest.get("types")
    manifest_errors: list[str] = list(composer_errors)
    if manifest.get("schema_version") != 1:
        manifest_errors.append("schema_version must equal 1")
    expected_source = "frontend/packages/ui/src/data/embedRegistry.generated.ts#EMBED_RENDERER_MAP"
    if manifest.get("source") != expected_source:
        manifest_errors.append(f"source must equal {expected_source!r}")
    if not isinstance(manifest_types, dict):
        manifest_errors.append("manifest 'types' must be a mapping")
        return AuditReport(len(renderer_map), {}, (), tuple(manifest_errors))

    registered = set(renderer_map)
    maintained = set(manifest_types)
    for embed_type in sorted(registered - maintained):
        manifest_errors.append(f"{embed_type}: missing manifest entry")
    for embed_type in sorted(maintained - registered):
        manifest_errors.append(f"{embed_type}: stale manifest entry not present in EMBED_RENDERER_MAP")

    classifications: Counter[str] = Counter()
    issues: list[CoverageIssue] = []
    for embed_type in sorted(registered):
        route = routes[embed_type]
        entry = manifest_types.get(embed_type)
        if not isinstance(entry, dict):
            classifications[route.classification] += 1
            issues.append(
                CoverageIssue(embed_type, route.classification, ("missing manifest entry and required proof fields",))
            )
            continue

        maintained_classification = entry.get("classification")
        classification = str(maintained_classification or route.classification)
        reasons: list[str] = []
        if classification not in CLASSIFICATIONS:
            reasons.append(f"invalid classification {classification!r}")
        elif classification == "not_applicable_to_composer":
            if not _is_filled(entry.get("not_applicable_reason")):
                reasons.append("not_applicable_to_composer requires not_applicable_reason")
        elif classification != route.classification:
            reasons.append(
                f"manifest classification {classification!r} disagrees with derived Apple route {route.classification!r}"
            )

        if entry.get("web_renderer") != renderer_map[embed_type]:
            reasons.append(f"web_renderer must equal {renderer_map[embed_type]!r}")
        for field in REQUIRED_MANIFEST_FIELDS:
            if field not in entry:
                reasons.append(f"missing manifest field {field!r}")

        if classification not in PARITY_CLASSIFICATIONS:
            reasons.append(f"{classification} does not count as native composer parity")
        elif classification != "not_applicable_to_composer":
            for field in REQUIRED_MANIFEST_FIELDS:
                if not _is_filled(entry.get(field)):
                    reasons.append(f"manifest field {field!r} has no coverage evidence")
            if classification == "specific_native" and embed_type not in pending_types:
                reasons.append("current pending-composer preview paths do not route this type")

        classifications[classification] += 1
        if reasons:
            issues.append(CoverageIssue(embed_type, classification, tuple(dict.fromkeys(reasons))))

    return AuditReport(
        registered_count=len(renderer_map),
        classifications=dict(sorted(classifications.items())),
        issues=tuple(issues),
        manifest_errors=tuple(manifest_errors),
    )


def _generated_entry(
    embed_type: str,
    web_renderer: str,
    route: NativeRoute,
    pending_types: set[str],
    existing: dict[str, Any],
) -> dict[str, Any]:
    classification = route.classification
    if existing.get("classification") == "not_applicable_to_composer":
        classification = "not_applicable_to_composer"
    elif embed_type == "focus-mode-activation":
        classification = "not_applicable_to_composer"
    entry = {
        "web_renderer": web_renderer,
        "classification": classification,
        "apple_model_case": route.model_case,
        "apple_read_renderer": route.renderer,
        "fixture": existing.get("fixture"),
        "lifecycle": existing.get("lifecycle", {}),
        "native_preview_mapping": existing.get("native_preview_mapping"),
        "visual_case": existing.get("visual_case"),
    }
    if classification == "structural_group_only":
        entry.update(
            fixture=existing.get("fixture", "shared/composer/fixtures/composer-document-v1.json#grouped-embed"),
            lifecycle=existing.get("lifecycle", {"finished": "structural group delegates to child previews"}),
            native_preview_mapping=existing.get(
                "native_preview_mapping",
                "apple/OpenMates/Sources/Features/Embeds/Grouping/EmbedGrouping.swift#GroupedEmbedView",
            ),
        )
    elif classification == "not_applicable_to_composer":
        entry.update(
            fixture=existing.get("fixture", "not_applicable"),
            lifecycle=existing.get("lifecycle", {"not_applicable": "system-generated read-only embed"}),
            native_preview_mapping=existing.get("native_preview_mapping", "not_applicable"),
            visual_case=existing.get("visual_case", "not_applicable"),
        )
        entry["not_applicable_reason"] = existing.get(
            "not_applicable_reason",
            "Focus-mode activation is system-generated and cannot be inserted by the composer.",
        )
    elif embed_type in pending_types:
        entry["native_preview_mapping"] = existing.get(
            "native_preview_mapping",
            "apple/OpenMates/Sources/Features/Chat/Views/InlinePreviewView.swift#PendingComposerEmbedPreview",
        )
        entry["lifecycle"] = existing.get("lifecycle", {"finished": "pending attachment preview"})
    return entry


def write_manifest(paths: AuditPaths) -> None:
    registry_text = _read(paths.registry)
    models_text = _read(paths.models)
    router_text = _read(paths.router)
    renderer_map = parse_typescript_string_map(registry_text, "EMBED_RENDERER_MAP")
    normalizations = parse_typescript_string_map(registry_text, "EMBED_TYPE_NORMALIZATION_MAP")
    raw_to_case, aliases = parse_apple_models(models_text)
    apple_routes = parse_apple_routes(router_text)
    routes = derive_native_routes(renderer_map, raw_to_case, apple_routes, router_text)
    if paths.composer_registry is not None:
        composer_routes, composer_errors = parse_composer_registry_types(_read(paths.composer_registry))
        if composer_errors:
            raise ValueError("; ".join(composer_errors))
        routes = apply_composer_registry(routes, composer_routes)
        pending_types = set(composer_routes)
    else:
        pending_types = parse_pending_preview_types(
            [_read(path) for path in paths.pending_previews], normalizations, aliases
        )
    existing_types: dict[str, Any] = {}
    if paths.manifest.exists():
        existing = load_manifest(paths.manifest).get("types")
        if isinstance(existing, dict):
            existing_types = existing

    payload = {
        "schema_version": 1,
        "source": "frontend/packages/ui/src/data/embedRegistry.generated.ts#EMBED_RENDERER_MAP",
        "types": {
            embed_type: _generated_entry(
                embed_type,
                renderer_map[embed_type],
                routes[embed_type],
                pending_types,
                existing_types.get(embed_type, {}) if isinstance(existing_types.get(embed_type, {}), dict) else {},
            )
            for embed_type in renderer_map
        },
    }
    header = (
        "# Apple composer renderer coverage inventory.\n"
        "# Generated keys and source classifications come from the web registry and Apple Swift routes.\n"
        "# Fixture, lifecycle, native preview mapping, and visual case are maintained proof fields.\n"
        "# Run: python3 scripts/apple_composer_renderer_audit.py --write-manifest\n"
        "# Generic search and fallback routes never count as composer parity.\n"
        "# Null proof values intentionally keep known native composer gaps visible.\n"
        "# Do not mark planned coverage as implemented evidence.\n"
    )
    paths.manifest.parent.mkdir(parents=True, exist_ok=True)
    paths.manifest.write_text(
        header + yaml.safe_dump(payload, sort_keys=False, allow_unicode=False, width=120),
        encoding="utf-8",
    )


def _default_paths(args: argparse.Namespace) -> AuditPaths:
    return AuditPaths(
        registry=Path(args.registry),
        models=Path(args.models),
        router=Path(args.router),
        pending_previews=tuple(Path(path) for path in args.pending_preview),
        manifest=Path(args.manifest),
        composer_registry=Path(args.composer_registry) if args.composer_registry else None,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Apple composer renderer coverage")
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    parser.add_argument("--models", default=DEFAULT_MODELS)
    parser.add_argument("--router", default=DEFAULT_ROUTER)
    parser.add_argument("--pending-preview", action="append", default=None)
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--composer-registry", default=DEFAULT_COMPOSER_REGISTRY)
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args(argv)
    if args.pending_preview is None:
        args.pending_preview = list(DEFAULT_PENDING_PREVIEWS)
    paths = _default_paths(args)

    try:
        if args.write_manifest:
            write_manifest(paths)
            print(f"Wrote Apple composer renderer manifest: {paths.manifest}")
            return 0
        report = audit(paths)
    except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
        print(f"Apple composer renderer audit failed: {exc}", file=sys.stderr)
        return 2

    print(f"Registered web write-mode renderer types: {report.registered_count}")
    print("Classifications: " + ", ".join(f"{name}={count}" for name, count in report.classifications.items()))
    for error in report.manifest_errors:
        print(f"MANIFEST: {error}")
    for issue in report.issues:
        print(f"UNCOVERED [{issue.classification}] {issue.embed_type}: {'; '.join(issue.reasons)}")
    if not report.passed:
        issue_categories = Counter(issue.classification for issue in report.issues)
        category_summary = ", ".join(f"{name}={count}" for name, count in sorted(issue_categories.items()))
        print(
            f"Apple composer renderer audit failed: {report.uncovered_count} uncovered type(s)"
            + (f" ({category_summary})" if category_summary else "")
        )
        return 1

    print("Apple composer renderer audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
