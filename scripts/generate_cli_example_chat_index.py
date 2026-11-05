#!/usr/bin/env python3
"""Generate the native CLI example-chat index from the shared example-chat registry.

The npm CLI imports ALL_EXAMPLE_CHATS (frontend/packages/ui/src/demo_chats/
exampleChatData.ts) directly. The native Rust CLI embeds this compact,
English-translated index instead (`openmates apps examples`). --check fails
when the committed index no longer matches the registry.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "frontend/packages/ui/src/demo_chats"
REGISTRY = DEMO / "exampleChatData.ts"
LOCALE = ROOT / "frontend/packages/ui/src/i18n/locales/en.json"
OUTPUT = ROOT / "config/cli-example-chat-index.json"


def _registry_files(source: str) -> list[Path]:
    imports = dict(
        (name, path)
        for name, path in re.findall(
            r'import \{ (?:\w+ as )?(\w+) \} from "(\./data/example_chats/[^"]+)";', source
        )
    )
    block = re.search(
        r"export const ALL_EXAMPLE_CHATS: ExampleChat\[\] = \[(.*?)\]\.sort", source, re.S
    )
    if not block:
        raise ValueError("ALL_EXAMPLE_CHATS registry not found")
    names = re.findall(r"(\w+),", block.group(1))
    missing = [name for name in names if name not in imports]
    if missing:
        raise ValueError(f"Unresolved example chat imports: {missing}")
    return [DEMO / (imports[name][2:] + ".ts") for name in names]


def _field(source: str, key: str) -> str | None:
    match = re.search(rf'^  {key}: "((?:[^"\\]|\\.)*)",', source, re.M)
    return json.loads(f'"{match.group(1)}"') if match else None


def _translate(value: str | None, locale: dict) -> str | None:
    if value is None or not value.startswith("example_chats."):
        return value
    node: object = locale
    for part in value.split("."):
        if not isinstance(node, dict) or part not in node:
            return value
        node = node[part]
    if isinstance(node, str):
        return node
    if isinstance(node, dict) and isinstance(node.get("text"), str):
        return node["text"]
    return value


def _chat(path: Path, locale: dict) -> dict:
    source = path.read_text(encoding="utf-8")
    messages = re.search(r"^  messages: \[(.*?)^  \],", source, re.M | re.S)
    timestamps = [
        int(value)
        for value in re.findall(r'"?created_at"?: (\d+)', messages.group(1) if messages else "")
    ]
    metadata = re.search(r"^  metadata: \{(.*?)^  \},", source, re.M | re.S)
    meta = metadata.group(1) if metadata else ""
    order = re.search(r"^\s+order: (-?\d+),", meta, re.M)
    skills = re.search(r"app_skill_examples: \[(.*?)\]", meta, re.S)
    chat_id = _field(source, "chat_id")
    slug = _field(source, "slug")
    if not chat_id or not slug or not order:
        raise ValueError(f"Example chat is missing chat_id, slug or metadata.order: {path}")
    return {
        "order": int(order.group(1)),
        "id": chat_id,
        "slug": slug,
        "title": _translate(_field(source, "title"), locale),
        "summary": _translate(_field(source, "summary"), locale),
        "updated_at": max(timestamps) if timestamps else None,
        "category": _field(source, "category"),
        "app_skill_examples": re.findall(r'"([^"]+)"', skills.group(1)) if skills else [],
    }


def build() -> str:
    locale = json.loads(LOCALE.read_text(encoding="utf-8"))
    chats = [_chat(path, locale) for path in _registry_files(REGISTRY.read_text(encoding="utf-8"))]
    chats.sort(key=lambda chat: chat["order"])  # stable, like Array.prototype.sort
    for chat in chats:
        del chat["order"]
    return json.dumps({"schema_version": 1, "chats": chats}, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = build()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != expected:
            print(f"{OUTPUT.relative_to(ROOT)} is stale; run {Path(__file__).name}", file=sys.stderr)
            return 1
        return 0
    OUTPUT.write_text(expected, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
