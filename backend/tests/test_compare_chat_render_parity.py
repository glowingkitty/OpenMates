"""Regression tests for the chat-rendering parity comparator.

The comparator validates machine-produced web and Apple manifests used by the
cross-client chat parity harness. These tests keep the opened-chat surface from
regressing back to loaded-sidebar-only validation, which would reject valid
per-message render manifests before comparing their signatures.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPARATOR_PATH = REPO_ROOT / "scripts" / "compare_chat_render_parity.py"
spec = importlib.util.spec_from_file_location("compare_chat_render_parity", COMPARATOR_PATH)
assert spec and spec.loader
compare_chat_render_parity = importlib.util.module_from_spec(spec)
sys.modules["compare_chat_render_parity"] = compare_chat_render_parity
spec.loader.exec_module(compare_chat_render_parity)


def opened_manifest(client: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "surface": "opened-user-chats",
        "client": client,
        "environment": {"account_email_hash": "same-account"},
        "opened_chats": [
            {
                "index": 0,
                "titleText": "Parity chat",
                "message_count": 1,
                "messages": [
                    {
                        "index": 0,
                        "role": "assistant",
                        "content_hash": "abc123",
                        "text_length": 42,
                        "block_counts": {"paragraph": 1, "inline_code": 0},
                        "embed_count": 0,
                        "has_sender_name": False,
                        "has_thinking": False,
                        "is_streaming": False,
                    }
                ],
            }
        ],
    }


def test_opened_chat_manifests_do_not_require_loaded_sidebar_fields() -> None:
    failures = compare_chat_render_parity.compare_manifests(
        opened_manifest("web"),
        opened_manifest("apple"),
        minimum_overlap=1,
        strict_order=True,
    )

    assert failures == []


def test_loaded_chat_manifest_still_requires_sidebar_contract() -> None:
    manifest = {
        "schema_version": 1,
        "surface": "loaded-user-chats",
        "client": "web",
        "environment": {"account_email_hash": "same-account"},
        "sidebar": {"chat_count": 1},
        "chats": [{"titleText": "Parity chat"}],
    }

    failures = compare_chat_render_parity.validate_manifest(manifest, "web")

    assert "web: required_elements missing" in failures
