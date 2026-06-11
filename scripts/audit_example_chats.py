#!/usr/bin/env python3
"""Audit hardcoded example chat data before it reaches the web app.

This catches deterministic rendering regressions that are easy to miss in
manual review: invalid mate categories, assistant messages that expose raw
TOON/tool payloads, missing i18n entries, and app-skill embeds that would
render with no useful preview text. It intentionally avoids judging response
quality; quality review belongs to the CLI regeneration workflow.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = REPO_ROOT / "frontend/packages/ui/src/demo_chats/data/example_chats"
EXAMPLE_I18N_DIR = REPO_ROOT / "frontend/packages/ui/src/i18n/sources/example_chats"
MATES_YML = REPO_ROOT / "frontend/packages/ui/src/i18n/sources/mates.yml"
REGISTRY_PATH = REPO_ROOT / "frontend/packages/ui/src/data/embedRegistry.generated.ts"

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


def unescape_ts_string(value: str) -> str:
    try:
        return bytes(value, "utf-8").decode("unicode_escape")
    except UnicodeDecodeError:
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


def toon_value(content: str, key: str) -> str | None:
    match = re.search(rf"(?:^|\n){re.escape(key)}:\s*\"?([^\n\"]+)\"?", content)
    return match.group(1).strip() if match else None


def has_generic_preview_content(content: str) -> bool:
    return any(toon_value(content, key) for key in GENERIC_PREVIEW_KEYS)


def audit() -> list[str]:
    issues: list[str] = []
    valid_categories = load_canonical_categories()
    registry_keys = load_registry_keys()

    for path in sorted(EXAMPLE_DIR.glob("*.ts")):
        source = path.read_text(encoding="utf-8")
        chat_id = parse_ts_string_field(source, "chat_id") or path.stem
        category = parse_ts_string_field(source, "category")
        issues.extend(audit_static_source(chat_id, source))

        if category not in valid_categories:
            issues.append(f"{chat_id}: invalid chat category {category!r}")

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

        for index, message in enumerate(parse_messages(source), start=1):
            resolved, missing_key = resolve_message_content(message.content)
            if missing_key:
                issues.append(f"{chat_id}: message {index} references missing i18n key {missing_key}")
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
            if embed_type != "app_skill_use":
                continue
            content = parse_embed_content(block)
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
