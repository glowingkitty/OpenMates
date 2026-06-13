#!/usr/bin/env python3
"""Audit hardcoded example chat data before it reaches the web app.

This catches deterministic rendering regressions that are easy to miss in
manual review: invalid mate categories, assistant messages that expose raw
TOON/tool payloads, missing i18n entries, and app-skill embeds that would
render with no useful preview text. It intentionally avoids judging response
quality; quality review belongs to the CLI regeneration workflow.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = REPO_ROOT / "frontend/packages/ui/src/demo_chats/data/example_chats"
EXAMPLE_I18N_DIR = REPO_ROOT / "frontend/packages/ui/src/i18n/sources/example_chats"
MATES_YML = REPO_ROOT / "frontend/packages/ui/src/i18n/sources/mates.yml"
REGISTRY_PATH = REPO_ROOT / "frontend/packages/ui/src/data/embedRegistry.generated.ts"
SHARED_EMBED_TYPES_PATH = REPO_ROOT / "shared/config/embed_types.yml"
APP_DIR = REPO_ROOT / "backend/apps"

SPECIAL_CATEGORIES = {"openmates_official"}
GENERIC_PREVIEW_KEYS = {
    "query",
    "prompt",
    "title",
    "summary",
    "result_count",
    "error",
    "provider",
}
RAW_PAYLOAD_PATTERNS = [
    re.compile(r"^\s*-\s+id:\s*['\"]?\d", re.MULTILINE),
    re.compile(r"^\s*comments\[\d+\]", re.MULTILINE),
    re.compile(r"^\s*embed_ref:\s*", re.MULTILINE),
]
FOCUS_MODES_REQUIRING_SUB_CHATS = {"web-research"}
FOCUS_MENTION_RE = re.compile(r"(^|\s)@focus:[a-z0-9_-]+:[a-z0-9_-]+\b")
FOCUS_ACTIVATION_MARKERS = ("focus_mode_activation", "focus-mode-activation")
FOCUS_ACTIVATION_TYPE = "focus-mode-activation"
RECIPE_EMBED_TYPES = {"recipe", "nutrition-recipe"}
PUBLIC_SAFETY_PATTERNS = [
    ("vault_wrapped_aes_key", "contains a vault-wrapped encryption key"),
    ("vault:v1:", "contains a vault key reference"),
    ("aes_key:", "contains a raw AES key"),
    ("aes_nonce:", "contains a raw AES nonce"),
    ("s3_base_url:", "contains a private S3 base URL"),
    ("dev-openmates-chatfiles", "references the private dev chatfiles bucket"),
    ("chatfiles/", "references a private chatfiles object key"),
    ("s3_key:", "references a private S3 object key"),
    ("docx_s3_key:", "references a private document object key"),
    ("screenshot_s3_keys:", "references private screenshot object keys"),
]
BROKEN_PUBLIC_TEXT_PATTERNS = [
    ("Presigned URL request failed", "contains a public presigned-URL failure"),
    ("Network error fetching S3", "contains a public S3 fetch failure"),
    ("Transcript not available", "contains a missing transcript placeholder"),
    ("[Interactive Question - Invalid JSON]", "contains an invalid interactive-question placeholder"),
]
UNSAFE_ADVICE_PATTERNS = [
    ("git checkout -- .", "suggests a destructive git cleanup command"),
]


@dataclass(frozen=True)
class ExampleMessage:
    role: str
    content: str


def load_canonical_categories() -> set[str]:
    source = MATES_YML.read_text(encoding="utf-8")
    return set(re.findall(r"^([a-z0-9_]+):\n\s+context:", source, re.MULTILINE)) | SPECIAL_CATEGORIES


def load_registry_keys() -> set[str]:
    source = REGISTRY_PATH.read_text(encoding="utf-8")
    return set(re.findall(r'"(app:[^"]+)"\s*:', source))


def load_content_catalog() -> dict[str, dict[str, str]]:
    catalog: dict[str, dict[str, str]] = {}
    for path in [SHARED_EMBED_TYPES_PATH, *sorted(APP_DIR.glob("*/app.yml"))]:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for embed_type in data.get("embed_types", []):
            content_catalog = embed_type.get("content_catalog") or {}
            if not content_catalog.get("enabled"):
                continue
            app_id = embed_type.get("app_id") or path.parent.name
            content_type_id = content_catalog.get("content_type_id") or embed_type.get("id")
            catalog_id = f"{app_id}.{content_type_id}"
            source = content_catalog.get("source", "self")
            registry_key = (
                f"app:{app_id}:{embed_type.get('skill_id')}"
                if embed_type.get("category") == "app-skill-use" and source != "child"
                else (
                    embed_type.get("child_frontend_type")
                    if source == "child"
                    else embed_type.get("frontend_type") or embed_type.get("id")
                )
            )
            catalog[catalog_id] = {
                "registryKey": registry_key,
                "frontendType": (
                    embed_type.get("child_frontend_type")
                    if source == "child"
                    else embed_type.get("frontend_type") or ""
                ),
                "backendType": (
                    embed_type.get("child_type")
                    if source == "child"
                    else embed_type.get("backend_type") or ""
                ),
                "skillId": embed_type.get("skill_id") or "",
            }
    return catalog


def unescape_ts_string(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value


def parse_ts_string_field(source: str, field: str) -> str | None:
    match = re.search(rf"[\"']?{re.escape(field)}[\"']?\s*:\s*\"((?:\\.|[^\"])*)\"", source)
    return unescape_ts_string(match.group(1)) if match else None


def parse_ts_template_field(source: str, field: str) -> str | None:
    match = re.search(rf"\b{re.escape(field)}:\s*`(?P<value>[\s\S]*?)`", source)
    return match.group("value") if match else None


def parse_ts_string_array_field(source: str, field: str) -> list[str]:
    match = re.search(rf"\b{re.escape(field)}:\s*\[(?P<body>[^\]]*)\]", source)
    if not match:
        return []
    return [unescape_ts_string(value) for value in re.findall(r'"((?:\\.|[^"])*)"', match.group("body"))]


def parse_messages(source: str) -> list[ExampleMessage]:
    match = re.search(r"messages:\s*\[(?P<body>[\s\S]*?)\n\s*\],\n\s*embeds:", source)
    if not match:
        return []

    messages: list[ExampleMessage] = []
    for item in re.finditer(r"\{(?P<body>[\s\S]*?)\n\s*\}", match.group("body")):
        body = item.group("body")
        role = parse_ts_string_field(body, "role")
        content = parse_ts_string_field(body, "content")
        if role and content is not None:
            messages.append(ExampleMessage(role=role, content=content))
    return messages


def parse_i18n_english(snake: str, key: str) -> str | None:
    path = EXAMPLE_I18N_DIR / f"{snake}.yml"
    if not path.exists():
        return None

    source = path.read_text(encoding="utf-8")
    section = re.search(
        rf"^{re.escape(key)}:\n(?P<body>[\s\S]*?)(?=^[a-zA-Z0-9_]+:\n|\Z)",
        source,
        re.MULTILINE,
    )
    if not section:
        return None

    body = section.group("body")
    block = re.search(r"^\s+en:\s*\|\n(?P<text>[\s\S]*?)(?=^\s+[a-z]{2}:\s|^\s+verified_by_human:|\Z)", body, re.MULTILINE)
    if block:
        return "\n".join(line[4:] if line.startswith("    ") else line for line in block.group("text").splitlines()).strip()

    scalar = re.search(r"^\s+en:\s*\"(?P<text>(?:\\.|[^\"])*)\"\s*$", body, re.MULTILINE)
    if scalar:
        return unescape_ts_string(scalar.group("text"))

    plain_scalar = re.search(r"^\s+en:\s*(?P<text>\S.*)$", body, re.MULTILINE)
    if plain_scalar:
        return plain_scalar.group("text").strip()

    return None


def resolve_message_content(content: str) -> tuple[str, str | None]:
    if not content.startswith("example_chats."):
        return content, None

    parts = content.split(".")
    if len(parts) != 3:
        return content, None
    _, snake, key = parts
    resolved = parse_i18n_english(snake, key)
    return (resolved if resolved is not None else content), (None if resolved is not None else content)


def iter_embed_blocks(source: str) -> list[str]:
    match = re.search(r"embeds:\s*\[(?P<body>[\s\S]*?)\n\s*\],\n\s*metadata:", source)
    if not match:
        return []
    return [item.group("body") for item in re.finditer(r"\{(?P<body>[\s\S]*?)\n\s*\}", match.group("body"))]


def has_matching_focus_activation(source: str, active_focus_id: str) -> bool:
    for block in iter_embed_blocks(source):
        if parse_ts_string_field(block, "type") != FOCUS_ACTIVATION_TYPE:
            continue
        content = parse_embed_content(block)
        if toon_value(content, "focus_id") == active_focus_id:
            return True
    return False


def sub_chats_have_assistant_messages(source: str) -> bool:
    sub_chats = source.split("sub_chats:", 1)
    if len(sub_chats) != 2:
        return True
    sub_chat_count = len(re.findall(r'["\']?is_sub_chat["\']?\s*:\s*true', sub_chats[1]))
    assistant_count = len(re.findall(r'["\']?role["\']?\s*:\s*["\']assistant["\']', sub_chats[1]))
    return sub_chat_count > 0 and assistant_count >= sub_chat_count


def audit_static_source(chat_id: str, source: str) -> list[str]:
    issues: list[str] = []
    for needle, description in PUBLIC_SAFETY_PATTERNS:
        if needle in source:
            issues.append(f"{chat_id}: {description}")
    for needle, description in BROKEN_PUBLIC_TEXT_PATTERNS + UNSAFE_ADVICE_PATTERNS:
        if needle in source:
            issues.append(f"{chat_id}: {description}")
    return issues


def parse_embed_content(block: str) -> str:
    content = parse_ts_template_field(block, "content") or parse_ts_string_field(block, "content")
    return content.replace("\\n", "\n") if content else ""


def embed_ids_in_source(source: str) -> set[str]:
    ids: set[str] = set()
    for block in iter_embed_blocks(source):
        embed_id = parse_ts_string_field(block, "embed_id")
        if embed_id:
            ids.add(embed_id)
    ids.update(re.findall(r'["\']?embed_id["\']?\s*:\s*"((?:\\.|[^"])*)"', source))
    return ids


def json_embed_refs_in_text(text: str) -> set[str]:
    refs: set[str] = set()
    for match in re.finditer(r"```json\s*(?P<body>[\s\S]*?)\s*```", text):
        body = match.group("body").strip()
        if '"embed_id"' not in body:
            continue
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            continue
        embed_id = parsed.get("embed_id")
        if isinstance(embed_id, str):
            refs.add(embed_id)
    return refs


def audit_interactive_questions(chat_id: str, message_index: int, text: str) -> list[str]:
    issues: list[str] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        if lines[index].strip() != "```interactive_question":
            index += 1
            continue

        start_line = index + 1
        index += 1
        body_lines: list[str] = []
        closed = False
        while index < len(lines):
            marker = lines[index].strip()
            if marker == "```":
                closed = True
                break
            if marker.startswith("```"):
                issues.append(
                    f"{chat_id}: message {message_index} interactive_question opened at line {start_line} is not closed before {marker!r}"
                )
                closed = True
                break
            body_lines.append(lines[index])
            index += 1

        if not closed:
            issues.append(f"{chat_id}: message {message_index} interactive_question opened at line {start_line} is not closed")
            break

        try:
            json.loads("\n".join(body_lines).strip())
        except json.JSONDecodeError as error:
            issues.append(
                f"{chat_id}: message {message_index} interactive_question opened at line {start_line} has invalid JSON: {error.msg}"
            )
        index += 1
    return issues


def has_renderable_document_content(content: str) -> bool:
    content_type = toon_value(content, "type")
    if content_type not in {"document", "docs-doc"}:
        return True
    return any(marker in content for marker in ("\nhtml:", "\ncode:", "\ndocx_model:"))


def has_embed_type(source: str, expected_types: set[str]) -> bool:
    for block in iter_embed_blocks(source):
        embed_type = parse_ts_string_field(block, "type")
        content_type = toon_value(parse_embed_content(block), "type")
        if embed_type in expected_types or content_type in expected_types:
            return True
    return False


def content_catalog_accepted_types(catalog_item: dict[str, str]) -> set[str]:
    registry_key = catalog_item.get("registryKey", "")
    accepted_types = {
        value
        for value in (
            catalog_item.get("frontendType"),
            catalog_item.get("backendType"),
            registry_key.removeprefix("app:") if registry_key.startswith("app:") else registry_key,
        )
        if value
    }
    accepted_types.update({value.replace("-", "_") for value in list(accepted_types)})
    return accepted_types


def embed_block_matches_content_catalog(block: str, catalog_item: dict[str, str]) -> bool:
    registry_key = catalog_item.get("registryKey", "")
    accepted_types = content_catalog_accepted_types(catalog_item)

    expected_app_id: str | None = None
    expected_skill_id: str | None = catalog_item.get("skillId")
    if registry_key.startswith("app:"):
        _, expected_app_id, expected_skill_id = registry_key.split(":", 2)

    embed_type = parse_ts_string_field(block, "type")
    content = parse_embed_content(block)
    content_type = toon_value(content, "type")
    app_id = toon_value(content, "app_id")
    skill_id = toon_value(content, "skill_id")

    if expected_app_id and app_id == expected_app_id and skill_id == expected_skill_id:
        return True
    return embed_type in accepted_types or content_type in accepted_types


def has_matching_content_embed(source: str, catalog_item: dict[str, str]) -> bool:
    return any(
        embed_block_matches_content_catalog(block, catalog_item)
        for block in iter_embed_blocks(source)
    )


def parse_message_embed_references(source: str) -> set[str]:
    references: set[str] = set()
    for message in parse_messages(source):
        resolved, _ = resolve_message_content(message.content)
        for match in re.finditer(r"```(?:json_embed|json)\n([\s\S]*?)\n```", resolved):
            try:
                parsed = json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and isinstance(parsed.get("embed_id"), str):
                references.add(parsed["embed_id"])
        references.update(re.findall(r"\[[^\]]*\]\(embed:([^\)]+)\)", resolved))
    return references


def has_visible_content_embed_reference(source: str, catalog_item: dict[str, str]) -> bool:
    references = parse_message_embed_references(source)
    for block in iter_embed_blocks(source):
        if not embed_block_matches_content_catalog(block, catalog_item):
            continue
        embed_id = parse_ts_string_field(block, "embed_id")
        content = parse_embed_content(block)
        embed_ref = toon_value(content, "embed_ref")

        if (embed_id and embed_id in references) or (embed_ref and embed_ref in references):
            return True

    return False


def toon_value(content: str, key: str) -> str | None:
    match = re.search(rf"(?:^|\n){re.escape(key)}:\s*\"?([^\n\"]+)\"?", content)
    return match.group(1).strip() if match else None


def has_generic_preview_content(content: str) -> bool:
    return any(toon_value(content, key) for key in GENERIC_PREVIEW_KEYS)


def has_visible_mail_memory_draft(source: str) -> bool:
    user_mentions_saved_style = False
    for message in parse_messages(source):
        resolved, _ = resolve_message_content(message.content)
        lowered = resolved.lower()
        if message.role == "user" and "saved" in lowered and "style" in lowered:
            user_mentions_saved_style = True
            continue
        if message.role != "assistant":
            continue
        if (
            user_mentions_saved_style
            and ("subject:" in lowered or "subject line" in lowered)
            and ("best," in lowered or "regards," in lowered or "alex" in lowered)
        ):
            return True
    return False


def has_memory_system_artifacts(source: str) -> bool:
    has_request = False
    has_accepted_response = False
    for message in parse_messages(source):
        if message.role != "system":
            continue
        resolved, _ = resolve_message_content(message.content)
        try:
            payload = json.loads(resolved)
        except json.JSONDecodeError:
            continue
        if payload.get("type") == "app_settings_memories_request":
            has_request = True
        if (
            payload.get("type") == "app_settings_memories_response"
            and payload.get("action") == "included"
        ):
            has_accepted_response = True
    return has_request and has_accepted_response


def has_non_empty_toon_field(content: str, key: str) -> bool:
    value = toon_value(content, key)
    return bool(value and value.strip() and value.strip().lower() not in {"null", "none", "[]"})


def audit_recipe_embed(chat_id: str, block: str, content: str) -> list[str]:
    embed_id = parse_ts_string_field(block, "embed_id") or "<unknown>"
    issues: list[str] = []
    if not has_non_empty_toon_field(content, "image_url"):
        issues.append(f"{chat_id}: recipe embed {embed_id} is missing a public image_url")
    if not has_non_empty_toon_field(content, "instructions"):
        issues.append(f"{chat_id}: recipe embed {embed_id} is missing renderable instructions")
    return issues


def audit() -> list[str]:
    issues: list[str] = []
    valid_categories = load_canonical_categories()
    registry_keys = load_registry_keys()
    content_catalog = load_content_catalog()
    content_example_counts = dict.fromkeys(content_catalog, 0)

    for path in sorted(EXAMPLE_DIR.glob("*.ts")):
        source = path.read_text(encoding="utf-8")
        chat_id = parse_ts_string_field(source, "chat_id") or path.stem
        category = parse_ts_string_field(source, "category")
        source_embed_ids = embed_ids_in_source(source)
        settings_memory_examples = parse_ts_string_array_field(source, "app_settings_memory_examples")
        issues.extend(audit_static_source(chat_id, source))

        if category not in valid_categories:
            issues.append(f"{chat_id}: invalid chat category {category!r}")

        for content_key in parse_ts_string_array_field(source, "content_embed_examples"):
            catalog_item = content_catalog.get(content_key)
            if catalog_item is None:
                issues.append(f"{chat_id}: unknown content embed example {content_key!r}")
                continue
            content_example_counts[content_key] = content_example_counts.get(content_key, 0) + 1
            if not has_matching_content_embed(source, catalog_item):
                issues.append(f"{chat_id}: content embed example {content_key!r} has no matching embed")
            elif not has_visible_content_embed_reference(source, catalog_item):
                issues.append(f"{chat_id}: content embed example {content_key!r} is not referenced in any message")

        active_focus_id = parse_ts_string_field(source, "active_focus_id")
        if active_focus_id and not has_matching_focus_activation(source, active_focus_id):
            focus_examples = parse_ts_string_array_field(source, "app_focus_mode_examples")
            issues.append(
                f"{chat_id}: focus-mode example {focus_examples or [active_focus_id]} is missing a matching focus activation embed"
            )
        if active_focus_id in FOCUS_MODES_REQUIRING_SUB_CHATS and "sub_chats:" not in source:
            focus_examples = parse_ts_string_array_field(source, "app_focus_mode_examples")
            issues.append(
                f"{chat_id}: focus-mode example {focus_examples or [active_focus_id]} is missing sub_chats"
            )
        if active_focus_id in FOCUS_MODES_REQUIRING_SUB_CHATS and not sub_chats_have_assistant_messages(source):
            focus_examples = parse_ts_string_array_field(source, "app_focus_mode_examples")
            issues.append(
                f"{chat_id}: focus-mode example {focus_examples or [active_focus_id]} has sub_chats without assistant messages"
            )

        if settings_memory_examples and not has_memory_system_artifacts(source):
            issues.append(
                f"{chat_id}: memory example {settings_memory_examples} is missing memory request/accepted system messages"
            )

        for index, message in enumerate(parse_messages(source), start=1):
            resolved, missing_key = resolve_message_content(message.content)
            if missing_key:
                issues.append(f"{chat_id}: message {index} references missing i18n key {missing_key}")
            issues.extend(audit_interactive_questions(chat_id, index, resolved))
            missing_json_refs = sorted(json_embed_refs_in_text(resolved) - source_embed_ids)
            if missing_json_refs:
                issues.append(
                    f"{chat_id}: message {index} references missing JSON embed IDs: {', '.join(missing_json_refs)}"
                )
            if active_focus_id in FOCUS_MODES_REQUIRING_SUB_CHATS and message.role == "user":
                if FOCUS_MENTION_RE.search(resolved):
                    issues.append(
                        f"{chat_id}: user message {index} contains @focus directive; focus-mode examples must demonstrate auto-selection"
                    )
            if message.role == "assistant":
                for pattern in RAW_PAYLOAD_PATTERNS:
                    if pattern.search(resolved):
                        issues.append(f"{chat_id}: assistant message {index} exposes raw embed/tool payload")
                        break
                if resolved.lstrip().startswith("```json") and any(marker in resolved for marker in FOCUS_ACTIVATION_MARKERS):
                    issues.append(f"{chat_id}: assistant message {index} exposes raw focus activation JSON")
            for needle, description in PUBLIC_SAFETY_PATTERNS + BROKEN_PUBLIC_TEXT_PATTERNS + UNSAFE_ADVICE_PATTERNS:
                if needle in resolved:
                    issues.append(f"{chat_id}: message {index} {description}")

        for block in iter_embed_blocks(source):
            embed_type = parse_ts_string_field(block, "type")
            content = parse_embed_content(block)
            if embed_type in {"document", "docs-doc"} and not has_renderable_document_content(content):
                embed_id = parse_ts_string_field(block, "embed_id") or "<unknown>"
                issues.append(f"{chat_id}: document embed {embed_id} has no renderable html/code/docx_model content")
            content_type = toon_value(content, "type")
            if embed_type in RECIPE_EMBED_TYPES or content_type in RECIPE_EMBED_TYPES:
                issues.extend(audit_recipe_embed(chat_id, block, content))
            if embed_type != "app_skill_use":
                continue
            app_id = toon_value(content, "app_id")
            skill_id = toon_value(content, "skill_id")
            if not app_id or not skill_id:
                issues.append(f"{chat_id}: app_skill_use embed missing app_id or skill_id")
                continue
            registry_key = f"app:{app_id}:{skill_id}"
            if registry_key not in registry_keys and not has_generic_preview_content(content):
                issues.append(
                    f"{chat_id}: {registry_key} has no registry preview and no generic preview fields"
                )

        if "mail.writing_styles" in settings_memory_examples:
            visible_mail_memory_draft = has_visible_mail_memory_draft(source)
            if not visible_mail_memory_draft and not has_embed_type(source, {"mail-email"}):
                issues.append(f"{chat_id}: mail writing memory example is missing a mail-email embed")

    for content_key, count in sorted(content_example_counts.items()):
        if count == 0:
            issues.append(f"content catalog item {content_key!r} has no example chat")
        elif count > 1:
            issues.append(f"content catalog item {content_key!r} has {count} example chats; expected exactly one")

    return issues


def main() -> int:
    issues = audit()
    if issues:
        print("EXAMPLE CHAT AUDIT ISSUES")
        for issue in issues:
            print(f"- {issue}")
        print(f"Summary: {len(issues)} issue(s).")
        return 1

    print("Example chat audit passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
