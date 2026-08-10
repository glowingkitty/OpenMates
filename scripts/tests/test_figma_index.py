#!/usr/bin/env python3
"""Regression tests for the local private Figma design index.

The index keeps Figma discovery deterministic without treating designs as an
implementation parity contract. Tests cover surface extraction, descendant text
snippets, ranked search, direct links, cache freshness, and secret-safe errors.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "scripts" / "figma_index.py"


def load_module():
    spec = importlib.util.spec_from_file_location("openmates_figma_index", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sample_file() -> dict:
    return {
        "name": "Website",
        "lastModified": "2026-07-07T14:39:58Z",
        "version": "123",
        "document": {
            "id": "0:0",
            "name": "Document",
            "type": "DOCUMENT",
            "children": [
                {
                    "id": "0:1",
                    "name": "Web App",
                    "type": "CANVAS",
                    "children": [
                        {
                            "id": "10:1",
                            "name": "Workflow designs",
                            "type": "SECTION",
                            "children": [
                                {
                                    "id": "10:2",
                                    "name": "workflows/workflow/new",
                                    "type": "FRAME",
                                    "absoluteBoundingBox": {
                                        "width": 1440,
                                        "height": 1024,
                                    },
                                    "children": [
                                        {
                                            "id": "10:3",
                                            "name": "New workflow",
                                            "type": "TEXT",
                                            "characters": "  New   workflow  ",
                                        },
                                        {
                                            "id": "10:4",
                                            "name": "Layout wrapper",
                                            "type": "FRAME",
                                            "children": [
                                                {
                                                    "id": "10:5",
                                                    "name": "Choose trigger",
                                                    "type": "TEXT",
                                                    "characters": "Choose a trigger\nfor this workflow",
                                                }
                                            ],
                                        },
                                    ],
                                }
                            ],
                        },
                        {
                            "id": "20:1",
                            "name": "Dashboard",
                            "type": "FRAME",
                            "children": [
                                {
                                    "id": "20:2",
                                    "name": "Recent chats",
                                    "type": "TEXT",
                                    "characters": "Recent chats",
                                }
                            ],
                        },
                    ],
                }
            ],
        },
    }


def test_build_index_extracts_root_surfaces_and_descendant_text():
    module = load_module()

    index = module.build_index(sample_file(), file_key="file-key")

    surfaces = {surface["id"]: surface for surface in index["surfaces"]}
    assert set(surfaces) == {"10:1", "10:2", "20:1"}
    workflow = surfaces["10:2"]
    assert workflow["page"] == "Web App"
    assert workflow["path"] == ["Web App", "Workflow designs", "workflows/workflow/new"]
    assert workflow["width"] == 1440
    assert workflow["height"] == 1024
    assert workflow["text_snippets"] == [
        "New workflow",
        "Choose a trigger for this workflow",
    ]
    assert workflow["url"].endswith("?node-id=10-2")


def test_nested_layout_frames_are_not_indexed_as_separate_surfaces():
    module = load_module()

    index = module.build_index(sample_file(), file_key="file-key")

    assert "10:4" not in {surface["id"] for surface in index["surfaces"]}


def test_search_prioritizes_surface_names_over_incidental_text():
    module = load_module()
    index = module.build_index(sample_file(), file_key="file-key")

    results = module.search_index(index, "check workflows UI in Figma", limit=5)
    direct_results = module.search_index(index, "workflows", limit=5)

    assert results[0]["id"] == "10:2"
    assert results[0]["score"] > 0
    assert results[0]["score"] == direct_results[0]["score"]
    assert module.search_index(index, "recent chats", limit=1)[0]["id"] == "20:1"


def test_index_freshness_uses_generation_timestamp():
    module = load_module()
    now = datetime(2026, 7, 10, 12, tzinfo=UTC)
    index = {"generated_at": (now - timedelta(hours=23)).isoformat()}

    assert module.is_index_fresh(index, max_age_hours=24, now=now) is True
    assert module.is_index_fresh(index, max_age_hours=12, now=now) is False


def test_written_index_is_owner_readable_only(tmp_path):
    module = load_module()
    path = tmp_path / "figma-index.json"

    module.write_index({"surfaces": []}, path)

    assert path.stat().st_mode & 0o777 == 0o600


def test_api_error_does_not_expose_access_token(monkeypatch):
    module = load_module()
    token = "private-token-value"

    def fail_request(*_args, **_kwargs):
        raise HTTPError(
            url="https://api.figma.com/v1/files/file-key",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(module, "urlopen", fail_request)

    try:
        module.fetch_file("file-key", token)
    except module.FigmaIndexError as exc:
        assert "403" in str(exc)
        assert token not in str(exc)
    else:
        raise AssertionError("Expected a secret-safe FigmaIndexError")
