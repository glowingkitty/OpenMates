#!/usr/bin/env python3
"""Regression tests for focus-mode example-chat render contracts.

Purpose: keep the public hardcoded focus-mode examples renderable without
requiring generated frontend artifacts or private share data.
Scope: validates all checked-in focus-mode examples plus targeted contracts from
docs/specs/focus-mode-example-chat-rendering/spec.yml.
Run: python3 -m pytest scripts/tests/test_example_chat_focus_mode_contract.py.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_DIR = ROOT / "frontend/packages/ui/src/demo_chats/data/example_chats"

FRAMEWORK_EXAMPLE = "framework-store-reputation-check.ts"
EGG_PRICES_EXAMPLE = "us-egg-prices-deep-research.ts"


def load_example_audit():
    spec = importlib.util.spec_from_file_location(
        "openmates_audit_example_chats",
        ROOT / "scripts/audit_example_chats.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def example_source(file_name: str) -> str:
    return (EXAMPLE_DIR / file_name).read_text(encoding="utf-8")


def focus_mode_example_files(audit) -> list[Path]:
    return [
        path for path in sorted(EXAMPLE_DIR.glob("*.ts"))
        if audit.parse_ts_string_field(path.read_text(encoding="utf-8"), "active_focus_id")
    ]


def test_focus_mode_examples_have_activation_embeds() -> None:
    audit = load_example_audit()

    for path in focus_mode_example_files(audit):
        source = path.read_text(encoding="utf-8")
        chat_id = audit.parse_ts_string_field(source, "chat_id") or path.name
        active_focus_id = audit.parse_ts_string_field(source, "active_focus_id")

        assert active_focus_id, f"{chat_id}: missing active_focus_id"
        assert audit.has_matching_focus_activation(source, active_focus_id), (
            f"{chat_id}: active_focus_id {active_focus_id!r} has no matching focus-mode activation embed"
        )


def test_focus_mode_example_message_embed_references_resolve() -> None:
    audit = load_example_audit()

    for path in focus_mode_example_files(audit):
        source = path.read_text(encoding="utf-8")
        chat_id = audit.parse_ts_string_field(source, "chat_id") or path.name
        source_embed_ids = audit.embed_ids_in_source(source)
        source_known_refs = audit.known_embed_refs(source)

        for index, message in enumerate(audit.parse_messages(source), start=1):
            resolved, missing_key = audit.resolve_message_content(message.content)
            assert missing_key is None, f"{chat_id}: message {index} missing i18n key {missing_key}"

            missing_json_refs = sorted(audit.json_embed_refs_in_text(resolved) - source_embed_ids)
            assert not missing_json_refs, (
                f"{chat_id}: message {index} references missing JSON embed IDs: {', '.join(missing_json_refs)}"
            )

            missing_markdown_refs = sorted(audit.markdown_embed_refs_in_text(resolved) - source_known_refs)
            assert not missing_markdown_refs, (
                f"{chat_id}: message {index} references missing markdown embed refs: {', '.join(missing_markdown_refs)}"
            )


def test_framework_website_json_payload_has_runtime_embed() -> None:
    audit = load_example_audit()
    source = example_source(FRAMEWORK_EXAMPLE)
    payloads = []
    for message in audit.parse_messages(source):
        if message.role != "user":
            continue
        resolved, _ = audit.resolve_message_content(message.content)
        payloads.extend(audit.json_embed_payloads_in_text(resolved))

    website_payload = next(
        (
            payload for payload in payloads
            if payload.get("type") == "website" and payload.get("url") == "https://frame.work"
        ),
        None,
    )
    assert website_payload is not None, "Framework example missing the visible frame.work website payload"

    embed_id = website_payload.get("embed_id")
    assert isinstance(embed_id, str) and embed_id, "Framework website payload has no embed_id"

    matching_blocks = [
        block for block in audit.iter_embed_blocks(source)
        if audit.parse_ts_string_field(block, "embed_id") == embed_id
    ]
    assert len(matching_blocks) == 1, f"Framework website payload embed {embed_id!r} is not checked in exactly once"

    content = audit.parse_embed_content(matching_blocks[0])
    assert audit.parse_ts_string_field(matching_blocks[0], "type") == "web-website"
    assert audit.toon_value(content, "url") == "https://frame.work"


def test_deep_research_static_sub_chats_have_assistant_responses() -> None:
    audit = load_example_audit()
    source = example_source(EGG_PRICES_EXAMPLE)
    chat_id = audit.parse_ts_string_field(source, "chat_id") or EGG_PRICES_EXAMPLE

    assert "sub_chats:" in source, f"{chat_id}: missing static sub_chats"
    assert audit.sub_chats_have_assistant_messages(source), f"{chat_id}: static sub_chats lack assistant messages"
