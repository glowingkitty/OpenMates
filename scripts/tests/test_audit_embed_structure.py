#!/usr/bin/env python3
"""
Regression tests for embed fullscreen structure guardrails.

The audit prevents fullscreen headers from accumulating multiple primary CTA
buttons. Secondary controls belong inside the content area or must be marked as
secondary/fallback/loading so mobile layouts do not stack large red actions.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "scripts" / "audit_embed_structure.py"


def load_module():
    spec = importlib.util.spec_from_file_location("openmates_audit_embed_structure", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# contract-test: tooling
def test_multiple_primary_header_ctas_are_reported(tmp_path: Path) -> None:
    module = load_module()
    fullscreen = tmp_path / "embeds" / "diagrams" / "MermaidDiagramEmbedFullscreen.svelte"
    write(
        fullscreen,
        "<UnifiedEmbedFullscreen>\n"
        "  {#snippet embedHeaderCta()}\n"
        "    <EmbedHeaderCtaButton label=\"Zoom in\" />\n"
        "    <EmbedHeaderCtaButton label=\"Zoom out\" />\n"
        "  {/snippet}\n"
        "</UnifiedEmbedFullscreen>\n",
    )

    issues = module.audit_fullscreen_primary_ctas(tmp_path / "embeds")

    assert len(issues) == 1
    assert "MermaidDiagramEmbedFullscreen.svelte" in issues[0]
    assert "2 possible primary" in issues[0]


# contract-test: tooling
def test_secondary_header_action_is_allowed(tmp_path: Path) -> None:
    module = load_module()
    fullscreen = tmp_path / "embeds" / "code" / "CodeEmbedFullscreen.svelte"
    write(
        fullscreen,
        "<UnifiedEmbedFullscreen>\n"
        "  {#snippet embedHeaderCta()}\n"
        "    <EmbedHeaderCtaButton label=\"Run\" />\n"
        "    <EmbedHeaderCtaButton label=\"Preview\" variant=\"secondary\" />\n"
        "  {/snippet}\n"
        "</UnifiedEmbedFullscreen>\n",
    )

    assert module.audit_fullscreen_primary_ctas(tmp_path / "embeds") == []


# contract-test: tooling
def test_secondary_header_action_with_dynamic_attrs_is_allowed(tmp_path: Path) -> None:
    module = load_module()
    fullscreen = tmp_path / "embeds" / "electronics" / "PcbSchematicEmbedFullscreen.svelte"
    write(
        fullscreen,
        "<UnifiedEmbedFullscreen>\n"
        "  {#snippet embedHeaderCta()}\n"
        "    <EmbedHeaderCtaButton\n"
        "      label={preparing ? $text('preparing') : $text('prepare_files')}\n"
        "      onclick={handlePrepareFiles}\n"
        "      testId=\"pcb-schematic-prepare-files\"\n"
        "    />\n"
        "    <EmbedHeaderCtaButton\n"
        "      label={showLogs ? $text('hide_logs') : $text('show_logs')}\n"
        "      onclick={() => (showLogs = !showLogs)}\n"
        "      variant=\"secondary\"\n"
        "      testId=\"pcb-schematic-show-logs\"\n"
        "    />\n"
        "  {/snippet}\n"
        "</UnifiedEmbedFullscreen>\n",
    )

    assert module.audit_fullscreen_primary_ctas(tmp_path / "embeds") == []


# contract-test: tooling
def test_mutually_exclusive_primary_states_with_same_test_id_are_allowed(tmp_path: Path) -> None:
    module = load_module()
    fullscreen = tmp_path / "embeds" / "travel" / "TravelConnectionEmbedFullscreen.svelte"
    write(
        fullscreen,
        "<UnifiedEmbedFullscreen>\n"
        "  {#snippet embedHeaderCta()}\n"
        "    {#if bookingState === 'loaded'}\n"
        "      <EmbedHeaderCtaButton testId=\"booking-cta\" label=\"Book\" />\n"
        "    {:else if bookingState === 'idle'}\n"
        "      <EmbedHeaderCtaButton testId=\"booking-cta\" label=\"Get link\" />\n"
        "    {/if}\n"
        "  {/snippet}\n"
        "</UnifiedEmbedFullscreen>\n",
    )

    assert module.audit_fullscreen_primary_ctas(tmp_path / "embeds") == []


# contract-test: tooling
def test_primary_cta_count_follows_branches_and_ignores_test_ids() -> None:
    module = load_module()
    apply = '<EmbedHeaderCtaButton testId="apply" />'
    source = '<EmbedHeaderCtaButton testId="source" />'

    assert module.count_possible_primary_header_ctas(
        f"{{#if canApply}}{apply}{{:else if hasSource}}{source}{{/if}}"
    ) == 1
    assert module.count_possible_primary_header_ctas(
        f"{{#if canApply}}{apply}{apply}{{:else}}{source}{{/if}}"
    ) == 2
    assert module.count_possible_primary_header_ctas(
        f"{{#if canApply}}{{#if ready}}{apply}{{:else}}{source}{{/if}}{{/if}}{source}"
    ) == 2
    assert module.count_possible_primary_header_ctas(
        f"{{#each sources as result}}{source}{{/each}}"
    ) == 2


# contract-test: tooling
def test_preview_base_detection_requires_unified_embed_preview(tmp_path: Path) -> None:
    module = load_module()
    preview = tmp_path / "embeds" / "fitness" / "FitnessResultEmbedPreview.svelte"
    write(preview, "<UnifiedEmbedPreview appId=\"fitness\" />\n")

    assert module.preview_uses_unified_base(preview) is True

    write(preview, "<article class=\"custom-card\">Result</article>\n")

    assert module.preview_uses_unified_base(preview) is False


# contract-test: tooling
def test_fullscreen_base_detection_allows_approved_templates(tmp_path: Path) -> None:
    module = load_module()
    fullscreen = tmp_path / "embeds" / "fitness" / "FitnessSearchEmbedFullscreen.svelte"
    write(fullscreen, "<SearchResultsTemplate appId=\"fitness\" />\n")

    assert module.fullscreen_uses_approved_base(fullscreen) is True

    write(fullscreen, "<div class=\"custom-fullscreen\">Result</div>\n")

    assert module.fullscreen_uses_approved_base(fullscreen) is False


# contract-test: tooling
def test_result_fullscreen_adapter_must_render_the_unified_shell(tmp_path: Path) -> None:
    module = load_module()
    fullscreen = tmp_path / "embeds" / "business" / "CompanyEmbedFullscreen.svelte"
    adapter = fullscreen.parents[1] / "ResultEmbedFullscreen.svelte"
    write(
        fullscreen,
        "<script>import ResultEmbedFullscreen from '../ResultEmbedFullscreen.svelte';</script>"
        "<ResultEmbedFullscreen />",
    )
    write(adapter, "<UnifiedEmbedFullscreen />")

    assert module.fullscreen_uses_approved_base(fullscreen) is True

    write(adapter, "<!-- <UnifiedEmbedFullscreen /> --><div>Result</div>")
    assert module.fullscreen_uses_approved_base(fullscreen) is False


# contract-test: tooling
def test_inline_parent_wiring_is_checked_without_an_overlay() -> None:
    module = load_module()
    for (parent_key, relative_path), (component, props, _) in module.INLINE_PARENT_CONTRACTS.items():
        source_path = module.EMBEDS_ROOT / relative_path
        source = module.svelte_source(source_path)
        assert module.missing_inline_parent_wiring(parent_key, relative_path, source) == []

        # A matching name elsewhere in the component cannot stand in for a prop.
        prop = props[0]
        broken = source.replace(prop, "unwired={", 1) + f"<p>{prop}</p>"
        missing = module.missing_inline_parent_wiring(parent_key, relative_path, broken)
        assert missing and component in missing[-1]
        assert module.missing_inline_parent_wiring(parent_key, "OtherFullscreen.svelte", source) is None


# contract-test: tooling
def test_registered_fullscreen_requires_the_shared_shell(tmp_path: Path, monkeypatch) -> None:
    module = load_module()
    fullscreen = tmp_path / "files" / "FileEmbedFullscreen.svelte"
    monkeypatch.setattr(module, "EMBEDS_ROOT", tmp_path)
    registry = module.RegistryMaps({}, {}, {}, {"file": "files/FileEmbedFullscreen.svelte"})
    write(fullscreen, "<main><header>Local fullscreen</header></main>")
    assert "does not render the shared shell" in module.audit_registered_fullscreen_shells(registry)[0]

    write(fullscreen, "<UnifiedEmbedFullscreen><EmbedHeader /></UnifiedEmbedFullscreen>")
    assert "duplicates the shared fullscreen identity" in module.audit_registered_fullscreen_shells(registry)[0]

    write(fullscreen, "<UnifiedEmbedFullscreen />")
    assert module.audit_registered_fullscreen_shells(registry) == []
