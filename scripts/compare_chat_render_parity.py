#!/usr/bin/env python3
"""Compare web and Apple chat-rendering parity manifests.

This Linux-safe helper validates the first cross-client parity slice: loaded user
chats in the sidebar. It intentionally compares semantic UI facts before visual
diffs so native SwiftUI can differ internally while still matching the product
contract exposed by the web oracle and Apple UI-test manifest.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEB_MANIFEST = REPO_ROOT / "artifacts/chat-rendering-parity/web-loaded-chats-manifest.json"
DEFAULT_APPLE_MANIFEST = REPO_ROOT / "artifacts/chat-rendering-parity/apple-loaded-chats-manifest.json"
LOADED_CHAT_SURFACE = "loaded-user-chats"
OPENED_CHAT_SURFACE = "opened-user-chats"
EXPECTED_SURFACES = {LOADED_CHAT_SURFACE, OPENED_CHAT_SURFACE}


def repo_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing manifest: {repo_path(path)}")
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"Manifest must be a JSON object: {repo_path(path)}")
    return data


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def normalize_title(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace(", sub-chat", "").replace(", pinned", "").split()).strip()


def chat_titles(manifest: dict[str, Any]) -> list[str]:
    chats = manifest.get("chats")
    if not isinstance(chats, list):
        return []
    titles: list[str] = []
    for chat in chats:
        if not isinstance(chat, dict):
            continue
        title = normalize_title(chat.get("titleText"))
        if title:
            titles.append(title)
    return titles


def chat_count(manifest: dict[str, Any]) -> int:
    sidebar = manifest.get("sidebar")
    if isinstance(sidebar, dict) and isinstance(sidebar.get("chat_count"), int):
        return int(sidebar["chat_count"])
    chats = manifest.get("chats")
    return len(chats) if isinstance(chats, list) else 0


def account_email_hash(manifest: dict[str, Any]) -> str | None:
    environment = manifest.get("environment")
    if not isinstance(environment, dict):
        return None
    value = environment.get("account_email_hash")
    return value if isinstance(value, str) and value else None


def validate_manifest(manifest: dict[str, Any], client: str) -> list[str]:
    failures: list[str] = []
    require(manifest.get("schema_version") == 1, f"{client}: schema_version must be 1", failures)
    require(manifest.get("surface") in EXPECTED_SURFACES, f"{client}: surface must be one of {sorted(EXPECTED_SURFACES)}", failures)
    require(manifest.get("client") == client, f"{client}: client must be {client}", failures)
    require(
        bool(account_email_hash(manifest)),
        f"{client}: environment.account_email_hash missing; regenerate the manifest with the current harness",
        failures,
    )
    require(chat_count(manifest) > 0, f"{client}: expected at least one chat row", failures)

    required = manifest.get("required_elements")
    require(isinstance(required, dict), f"{client}: required_elements missing", failures)
    if isinstance(required, dict):
        title_key = "chat_title"
        row_key = "chat_item_wrapper"
        require(bool(required.get(title_key)), f"{client}: required element {title_key} was false", failures)
        require(bool(required.get(row_key)), f"{client}: required element {row_key} was false", failures)

    titles = chat_titles(manifest)
    require(bool(titles), f"{client}: expected at least one visible chat title", failures)
    return failures


def compare_manifests(
    web: dict[str, Any],
    apple: dict[str, Any],
    minimum_overlap: int,
    strict_order: bool,
) -> list[str]:
    failures: list[str] = []
    failures.extend(validate_manifest(web, "web"))
    failures.extend(validate_manifest(apple, "apple"))
    if failures:
        return failures
    if web.get("surface") != apple.get("surface"):
        return [f"surface mismatch: web={web.get('surface')} apple={apple.get('surface')}"]
    if web.get("surface") == OPENED_CHAT_SURFACE:
        return compare_opened_manifests(web, apple, minimum_overlap, strict_order)

    web_titles = chat_titles(web)
    apple_titles = chat_titles(apple)
    overlap = [title for title in web_titles if title in set(apple_titles)]
    web_account_hash = account_email_hash(web)
    apple_account_hash = account_email_hash(apple)

    if web_account_hash and apple_account_hash:
        require(
            web_account_hash == apple_account_hash,
            "account mismatch: web and Apple manifests were generated from different test accounts",
            failures,
        )

    require(
        len(overlap) >= minimum_overlap,
        f"expected at least {minimum_overlap} overlapping chat title(s), found {len(overlap)}",
        failures,
    )

    if strict_order:
        comparable_count = min(len(web_titles), len(apple_titles))
        require(
            web_titles[:comparable_count] == apple_titles[:comparable_count],
            "strict order mismatch between web and Apple loaded chat titles",
            failures,
        )
        require(
            chat_count(web) == chat_count(apple),
            f"strict count mismatch: web={chat_count(web)} apple={chat_count(apple)}",
            failures,
        )

    return failures


def opened_chats(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    chats = manifest.get("opened_chats")
    return [chat for chat in chats if isinstance(chat, dict)] if isinstance(chats, list) else []


def message_signature(message: dict[str, Any]) -> tuple[Any, ...]:
    return (
        message.get("role"),
        message.get("content_hash"),
        message.get("text_length"),
        normalized_block_counts(message.get("block_counts")),
        bool(message.get("has_sender_name")),
        bool(message.get("has_thinking")),
        bool(message.get("is_streaming")),
    )


def normalized_block_counts(value: Any) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, dict):
        return tuple()
    normalized: dict[str, int] = {}
    for key, count in value.items():
        if key == "inline_code":
            continue
        if isinstance(key, str) and isinstance(count, int):
            normalized[key] = count
    return tuple(sorted(normalized.items()))


def compare_opened_manifests(
    web: dict[str, Any],
    apple: dict[str, Any],
    minimum_overlap: int,
    strict_order: bool,
) -> list[str]:
    failures: list[str] = []
    web_account_hash = account_email_hash(web)
    apple_account_hash = account_email_hash(apple)
    if web_account_hash and apple_account_hash:
        require(
            web_account_hash == apple_account_hash,
            "account mismatch: web and Apple manifests were generated from different test accounts",
            failures,
        )

    web_chats = opened_chats(web)
    apple_chats = opened_chats(apple)
    require(bool(web_chats), "web: expected at least one opened chat", failures)
    require(bool(apple_chats), "apple: expected at least one opened chat", failures)
    require(
        len(web_chats) >= minimum_overlap and len(apple_chats) >= minimum_overlap,
        f"expected at least {minimum_overlap} opened chat(s), found web={len(web_chats)} apple={len(apple_chats)}",
        failures,
    )
    if strict_order:
        require(
            len(web_chats) == len(apple_chats),
            f"strict opened-chat count mismatch: web={len(web_chats)} apple={len(apple_chats)}",
            failures,
        )

    comparable_count = min(len(web_chats), len(apple_chats))
    for index in range(comparable_count):
        web_chat = web_chats[index]
        apple_chat = apple_chats[index]
        web_title = normalize_title(web_chat.get("titleText"))
        apple_title = normalize_title(apple_chat.get("titleText"))
        require(
            web_title == apple_title,
            f"opened chat {index}: title mismatch web={web_title!r} apple={apple_title!r}",
            failures,
        )
        web_messages = [msg for msg in web_chat.get("messages", []) if isinstance(msg, dict)]
        apple_messages = [msg for msg in apple_chat.get("messages", []) if isinstance(msg, dict)]
        require(
            len(web_messages) == len(apple_messages),
            f"opened chat {index}: message count mismatch web={len(web_messages)} apple={len(apple_messages)}",
            failures,
        )
        for message_index in range(min(len(web_messages), len(apple_messages))):
            web_signature = message_signature(web_messages[message_index])
            apple_signature = message_signature(apple_messages[message_index])
            require(
                web_signature == apple_signature,
                f"opened chat {index} message {message_index}: render signature mismatch",
                failures,
            )
    return failures


def print_summary(web: dict[str, Any], apple: dict[str, Any] | None) -> None:
    print("Chat rendering parity summary")
    print(f"- surface: {web.get('surface')}")
    print(f"- web rows: {chat_count(web)}")
    web_account_hash = account_email_hash(web)
    if web_account_hash:
        print(f"- web account hash: {web_account_hash}")
    web_titles = chat_titles(web)
    if web_titles:
        print(f"- web first title: {web_titles[0]}")
    if apple is None:
        print("- apple rows: not provided")
        if web.get("surface") == OPENED_CHAT_SURFACE:
            print(f"- web opened chats: {len(opened_chats(web))}")
        return
    apple_titles = chat_titles(apple)
    print(f"- apple rows: {chat_count(apple)}")
    apple_account_hash = account_email_hash(apple)
    if apple_account_hash:
        print(f"- apple account hash: {apple_account_hash}")
    if apple_titles:
        print(f"- apple first title: {apple_titles[0]}")
    print(f"- overlapping titles: {len([title for title in web_titles if title in set(apple_titles)])}")
    if web.get("surface") == OPENED_CHAT_SURFACE:
        print(f"- web opened chats: {len(opened_chats(web))}")
        print(f"- apple opened chats: {len(opened_chats(apple))}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare OpenMates web/Apple loaded-chat parity manifests.")
    parser.add_argument("--web", type=Path, default=DEFAULT_WEB_MANIFEST, help="Web oracle manifest JSON path.")
    parser.add_argument("--apple", type=Path, default=None, help="Apple candidate manifest JSON path.")
    parser.add_argument(
        "--minimum-overlap",
        type=int,
        default=1,
        help="Minimum number of visible chat titles that must overlap between web and Apple.",
    )
    parser.add_argument("--strict-order", action="store_true", help="Require equal counts and matching visible title order.")
    parser.add_argument("--web-only", action="store_true", help="Only validate the web manifest.")
    args = parser.parse_args()

    web_path = args.web if args.web.is_absolute() else REPO_ROOT / args.web
    apple_path = args.apple if args.apple and args.apple.is_absolute() else (REPO_ROOT / args.apple if args.apple else DEFAULT_APPLE_MANIFEST)

    try:
        web = load_manifest(web_path)
        apple = None if args.web_only else load_manifest(apple_path)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}")
        return 2

    failures = validate_manifest(web, "web") if args.web_only else compare_manifests(web, apple, args.minimum_overlap, args.strict_order)  # type: ignore[arg-type]
    print_summary(web, apple)

    if failures:
        print("Parity comparison failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Parity comparison passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
