"""The source-chat auditor must decode single-quoted converter output."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_audit():
    spec = importlib.util.spec_from_file_location("example_chat_audit_single_quotes", ROOT / "scripts/audit_example_chats.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# contract-test: tooling
def test_hosting_example_single_quoted_embeds_resolve() -> None:
    audit = load_audit()
    source = (ROOT / "frontend/packages/ui/src/demo_chats/data/example_chats/social-app-name-domain-search.ts").read_text(encoding="utf-8")
    parent_contents = [
        audit.parse_embed_content(block)
        for block in audit.iter_embed_blocks(source)
        if audit.parse_ts_string_field(block, "type") == "app_skill_use"
    ]
    assert len(parent_contents) == 4
    assert all(audit.toon_value(content, "app_id") == "hosting" for content in parent_contents)
    assert all(audit.toon_value(content, "skill_id") == "search_domains" for content in parent_contents)

    known_refs = audit.known_embed_refs(source)
    assistant = next(message for message in audit.parse_messages(source) if message.role == "assistant")
    resolved, missing_key = audit.resolve_message_content(assistant.content)
    assert missing_key is None
    assert audit.markdown_embed_refs_in_text(resolved) <= known_refs
