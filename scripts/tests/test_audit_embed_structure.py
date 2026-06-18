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
