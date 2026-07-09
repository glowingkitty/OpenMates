"""Focused tests for the Apple composer renderer coverage audit.

Synthetic generated-registry and Swift fixtures exercise the source parsers
without depending on the repository's intentionally incomplete native coverage.
The clean case proves all maintained evidence is accepted; failing cases prove
missing and generic routes cannot be reported as native composer parity.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.apple_composer_renderer_audit import AuditPaths, audit, main


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def synthetic_paths(tmp_path: Path, renderer_map: str, models: str, router: str, manifest: dict) -> AuditPaths:
    registry = write(
        tmp_path / "embedRegistry.generated.ts",
        "export const EMBED_TYPE_NORMALIZATION_MAP: Record<string, string> = {\n"
        '  "audio-recording": "recording"\n'
        "};\n"
        "export const EMBED_RENDERER_MAP: Record<string, string> = {\n"
        f"{renderer_map}\n"
        "};\n",
    )
    model_path = write(tmp_path / "EmbedModels.swift", models)
    router_path = write(tmp_path / "EmbedContentView.swift", router)
    pending = write(
        tmp_path / "InlinePreviewView.swift",
        'if embed.type == "audio-recording" { return RecordingPreview() }\n',
    )
    manifest_path = write(tmp_path / "renderer-coverage.yml", yaml.safe_dump(manifest, sort_keys=False))
    return AuditPaths(registry, model_path, router_path, (pending,), manifest_path)


def proof_entry(web_renderer: str, classification: str = "specific_native") -> dict:
    return {
        "web_renderer": web_renderer,
        "classification": classification,
        "fixture": "fixtures.json#recording",
        "lifecycle": {"finished": "preview"},
        "native_preview_mapping": "InlinePreviewView.swift#RecordingPreview",
        "visual_case": "RendererTests.swift#testRecordingPreview",
    }


def test_clean_specific_native_case_passes(tmp_path: Path) -> None:
    paths = synthetic_paths(
        tmp_path,
        '  "recording": "RecordingRenderer"',
        'enum EmbedType: String, CaseIterable {\n    case recording\n}',
        "switch embedType {\ncase .recording:\n    RecordingRenderer(data: data)\n}",
        {
            "schema_version": 1,
            "source": "frontend/packages/ui/src/data/embedRegistry.generated.ts#EMBED_RENDERER_MAP",
            "types": {"recording": proof_entry("RecordingRenderer")},
        },
    )

    report = audit(paths)

    assert report.passed
    assert report.registered_count == 1
    assert report.classifications == {"specific_native": 1}


def test_missing_and_generic_routes_are_uncovered_even_with_manifest_proofs(tmp_path: Path) -> None:
    paths = synthetic_paths(
        tmp_path,
        '  "recording": "RecordingRenderer",\n  "future-widget": "FutureRenderer"',
        'enum EmbedType: String, CaseIterable {\n    case recording\n}',
        "switch embedType {\ncase .recording:\n    GenericEmbedRenderer(data: data)\n}",
        {
            "schema_version": 1,
            "source": "frontend/packages/ui/src/data/embedRegistry.generated.ts#EMBED_RENDERER_MAP",
            "types": {
                "recording": proof_entry("RecordingRenderer", "generic_fallback"),
                "future-widget": proof_entry("FutureRenderer", "missing"),
            },
        },
    )

    report = audit(paths)

    assert not report.passed
    assert report.uncovered_count == 2
    assert {issue.embed_type: issue.classification for issue in report.issues} == {
        "future-widget": "missing",
        "recording": "generic_fallback",
    }
    assert all(
        any("does not count as native composer parity" in reason for reason in issue.reasons)
        for issue in report.issues
    )


def test_cli_returns_nonzero_when_required_proof_field_is_empty(tmp_path: Path) -> None:
    entry = proof_entry("RecordingRenderer")
    entry["visual_case"] = None
    paths = synthetic_paths(
        tmp_path,
        '  "recording": "RecordingRenderer"',
        'enum EmbedType: String, CaseIterable {\n    case recording\n}',
        "switch embedType {\ncase .recording:\n    RecordingRenderer(data: data)\n}",
        {
            "schema_version": 1,
            "source": "frontend/packages/ui/src/data/embedRegistry.generated.ts#EMBED_RENDERER_MAP",
            "types": {"recording": entry},
        },
    )

    result = main(
        [
            "--registry",
            str(paths.registry),
            "--models",
            str(paths.models),
            "--router",
            str(paths.router),
            "--pending-preview",
            str(paths.pending_previews[0]),
            "--manifest",
            str(paths.manifest),
        ]
    )

    assert result == 1
