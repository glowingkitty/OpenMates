#!/usr/bin/env python3
"""
Regression tests for embed preview child-hydration guardrails.

The audit protects scalable chat loading by keeping parent preview components
metadata-only. Child embed hydration remains valid in fullscreen components
because that path requires an explicit user action.

Architecture: docs/specs/scalable-chat-embed-loading/spec.yml
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "scripts" / "audit_embed_preview_hydration.py"


def load_module():
    spec = importlib.util.spec_from_file_location("openmates_audit_embed_preview_hydration", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_preview_child_hydration_is_reported(tmp_path: Path) -> None:
    module = load_module()
    embeds_root = tmp_path / "embeds"
    preview = embeds_root / "videos" / "VideosSearchEmbedPreview.svelte"
    write(
        preview,
        "<script lang=\"ts\">\n"
        "  let isLoadingChildren = false;\n"
        "  async function loadChildEmbedsForPreview(childEmbedIds: string[]) {\n"
        "    await loadEmbedsWithRetry(childEmbedIds);\n"
        "  }\n"
        "</script>\n",
    )

    issues = module.audit_embed_preview_hydration(embeds_root)

    assert [issue.pattern for issue in issues] == [
        "isLoadingChildren",
        "loadChildEmbedsForPreview",
        "loadEmbedsWithRetry",
    ]


def test_parent_metadata_counts_are_allowed(tmp_path: Path) -> None:
    module = load_module()
    embeds_root = tmp_path / "embeds"
    preview = embeds_root / "events" / "EventsSearchEmbedPreview.svelte"
    write(
        preview,
        "<script lang=\"ts\">\n"
        "  const embedIds = content.embed_ids;\n"
        "  const childEmbedIds = Array.isArray(embedIds) ? embedIds : [];\n"
        "  const resultCount = childEmbedIds.length;\n"
        "</script>\n",
    )

    assert module.audit_embed_preview_hydration(embeds_root) == []


def test_fullscreen_child_hydration_is_not_scanned(tmp_path: Path) -> None:
    module = load_module()
    embeds_root = tmp_path / "embeds"
    fullscreen = embeds_root / "videos" / "VideosSearchEmbedFullscreen.svelte"
    write(
        fullscreen,
        "<script lang=\"ts\">\n"
        "  let isLoadingChildren = false;\n"
        "  async function loadChildEmbedsForPreview(childEmbedIds: string[]) {\n"
        "    await loadEmbedsWithRetry(childEmbedIds);\n"
        "  }\n"
        "</script>\n",
    )

    assert module.audit_embed_preview_hydration(embeds_root) == []
