#!/usr/bin/env python3
"""Score published example chats with one Gemini request per chat.

This script is intentionally read-only for product data. It extracts the public
example-chat registry, resolves English i18n source strings, sends a separate
Google AI Studio Gemini request for each chat, and writes a JSON report under
scripts/.tmp by default. Secrets are loaded from env/.env first, then through
the existing API-container Vault path used by other repo scripts.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error, request

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPO_ROOT / ".env"
COMPOSE_FILE = REPO_ROOT / "backend/core/docker-compose.yml"
EXAMPLE_DATA_REGISTRY = REPO_ROOT / "frontend/packages/ui/src/demo_chats/exampleChatData.ts"
EXAMPLE_I18N_DIR = REPO_ROOT / "frontend/packages/ui/src/i18n/sources/example_chats"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "scripts/.tmp"
DEFAULT_MODEL = "gemini-3-flash-preview"
DEFAULT_WORKERS = 4
DEFAULT_MAX_TRANSCRIPT_CHARS = 50000
DEFAULT_MAX_EMBED_CHARS = 30000
MAX_SINGLE_EMBED_CHARS = 3000
DELETE_THRESHOLD = 4
REDO_THRESHOLD = 7


@dataclass(frozen=True)
class ExampleChatSource:
    slug: str
    export_name: str
    source_path: Path
    internal: bool


@dataclass(frozen=True)
class ExampleMessage:
    role: str
    content: str
    model_name: str | None = None


@dataclass(frozen=True)
class ExampleEmbed:
    embed_id: str
    type: str
    content: str
    parent_embed_id: str | None = None


@dataclass(frozen=True)
class ExampleChatTranscript:
    slug: str
    title: str
    summary: str
    category: str
    source_path: Path
    internal: bool
    messages: list[ExampleMessage]
    embeds: list[ExampleEmbed]
    sub_chats: list[tuple[str, list[ExampleMessage]]]


class ParseError(RuntimeError):
    pass


class GeminiAuditError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score OpenMates example-chat quality with one Gemini request per chat.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model to use.")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Concurrent Gemini requests.")
    parser.add_argument("--limit", type=int, help="Audit only the first N selected chats.")
    parser.add_argument("--slug", action="append", default=[], help="Audit only this slug. Repeatable.")
    parser.add_argument("--include-internal", action="store_true", help="Also audit internal test fixtures.")
    parser.add_argument(
        "--max-transcript-chars",
        type=int,
        default=DEFAULT_MAX_TRANSCRIPT_CHARS,
        help="Maximum transcript characters sent for each chat.",
    )
    parser.add_argument(
        "--max-embed-chars",
        type=int,
        default=DEFAULT_MAX_EMBED_CHARS,
        help="Maximum attached embed characters sent for each chat.",
    )
    parser.add_argument("--output", type=Path, help="JSON report path. Defaults to scripts/.tmp/...")
    parser.add_argument("--dry-run", action="store_true", help="Extract transcripts but do not call Gemini.")
    return parser.parse_args()


def load_gemini_api_key() -> str | None:
    for name in ("GEMINI_API_KEY", "SECRET__GOOGLE_AI_STUDIO__API_KEY"):
        value = os.environ.get(name, "").strip()
        if value and value != "IMPORTED_TO_VAULT":
            return value

    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            if key.strip() in {"GEMINI_API_KEY", "SECRET__GOOGLE_AI_STUDIO__API_KEY"}:
                cleaned = value.strip().strip('"').strip("'")
                if cleaned and cleaned != "IMPORTED_TO_VAULT":
                    return cleaned
    return load_gemini_api_key_from_vault()


def load_gemini_api_key_from_vault() -> str | None:
    if not COMPOSE_FILE.exists():
        return None
    fetch_script = (
        "import asyncio\n"
        "from backend.core.api.app.utils.secrets_manager import SecretsManager\n"
        "from backend.apps.ai.llm_providers.google_client import _get_google_ai_studio_api_key\n"
        "async def main():\n"
        "    sm = SecretsManager()\n"
        "    await sm.initialize()\n"
        "    key = await _get_google_ai_studio_api_key(sm)\n"
        "    print(key or '', end='')\n"
        "asyncio.run(main())\n"
    )
    command = ["docker", "compose"]
    if ENV_FILE.exists():
        command.extend(["--env-file", str(ENV_FILE)])
    command.extend(["-f", str(COMPOSE_FILE), "exec", "-T", "api", "python3", "-c", fetch_script])
    try:
        result = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or None


def extract_registered_sources(include_internal: bool) -> list[ExampleChatSource]:
    source = EXAMPLE_DATA_REGISTRY.read_text(encoding="utf-8")
    imports = {
        name: REPO_ROOT / "frontend/packages/ui/src/demo_chats" / f"{module_path.removeprefix('./')}.ts"
        for name, module_path in re.findall(r'import \{ (\w+) \} from "([^"]+)";', source)
    }
    public_names = extract_registry_array_names(source, "ALL_EXAMPLE_CHATS")
    internal_names = extract_registry_array_names(source, "INTERNAL_EXAMPLE_CHATS") if include_internal else []
    sources: list[ExampleChatSource] = []
    for export_name in public_names:
        source_path = imports.get(export_name)
        if source_path is None:
            raise ParseError(f"No import found for public example export {export_name}")
        sources.append(ExampleChatSource(source_path.stem, export_name, source_path, False))
    for export_name in internal_names:
        source_path = imports.get(export_name)
        if source_path is None:
            raise ParseError(f"No import found for internal example export {export_name}")
        sources.append(ExampleChatSource(source_path.stem, export_name, source_path, True))
    return sources


def extract_registry_array_names(source: str, export_name: str) -> list[str]:
    match = re.search(rf"export const {export_name}: ExampleChat\[\] = \[", source)
    if not match:
        raise ParseError(f"Could not find {export_name} registry array")
    start = match.end() - 1
    end = find_matching(source, start, "[", "]")
    body = source[start + 1 : end]
    return re.findall(r"^\s*(\w+)\s*,", body, flags=re.MULTILINE)


def load_i18n_namespace(namespace: str) -> dict[str, str]:
    path = EXAMPLE_I18N_DIR / f"{namespace}.yml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    translations: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(value.get("en"), str):
            translations[f"example_chats.{namespace}.{key}"] = value["en"]
    return translations


def parse_chat(source: ExampleChatSource) -> ExampleChatTranscript:
    raw = source.source_path.read_text(encoding="utf-8")
    obj = extract_export_object(raw, source.export_name)
    slug = extract_string_prop(obj, "slug") or source.slug
    translations: dict[str, str] = {}
    namespace = i18n_namespace_from_object(obj)
    if namespace:
        translations = load_i18n_namespace(namespace)

    title = resolve_i18n(extract_string_prop(obj, "title") or slug, translations)
    summary = resolve_i18n(extract_string_prop(obj, "summary") or "", translations)
    category = extract_string_prop(obj, "category") or ""
    messages = parse_messages_array(extract_top_level_property(obj, "messages") or "[]", translations)
    embeds = parse_embeds_array(extract_top_level_property(obj, "embeds") or "[]")
    sub_chats = parse_sub_chats(extract_top_level_property(obj, "sub_chats") or "[]", translations)
    return ExampleChatTranscript(
        slug=slug,
        title=title,
        summary=summary,
        category=category,
        source_path=source.source_path,
        internal=source.internal,
        messages=messages,
        embeds=embeds,
        sub_chats=sub_chats,
    )


def extract_export_object(source: str, export_name: str) -> str:
    match = re.search(rf"export const {export_name}: ExampleChat =", source)
    if not match:
        raise ParseError(f"Could not find export {export_name}")
    start = source.find("{", match.end())
    if start < 0:
        raise ParseError(f"Could not find object body for {export_name}")
    end = find_matching(source, start, "{", "}")
    return source[start : end + 1]


def i18n_namespace_from_object(obj: str) -> str | None:
    for value in re.findall(r'"(example_chats\.([a-z0-9_]+)\.[a-z0-9_]+)"', obj):
        return value[1]
    return None


def resolve_i18n(value: str, translations: dict[str, str]) -> str:
    return translations.get(value, value)


def parse_sub_chats(array_source: str, translations: dict[str, str]) -> list[tuple[str, list[ExampleMessage]]]:
    sub_chats: list[tuple[str, list[ExampleMessage]]] = []
    for block in top_level_object_blocks(array_source):
        title = resolve_i18n(extract_string_prop(block, "title") or "Sub-chat", translations)
        messages = parse_messages_array(extract_top_level_property(block, "messages") or "[]", translations)
        sub_chats.append((title, messages))
    return sub_chats


def parse_embeds_array(array_source: str) -> list[ExampleEmbed]:
    embeds: list[ExampleEmbed] = []
    for block in top_level_object_blocks(array_source):
        embed_id = extract_string_prop(block, "embed_id") or "unknown"
        embed_type = extract_string_prop(block, "type") or "unknown"
        content = extract_string_prop(block, "content") or ""
        parent_embed_id = extract_string_prop(block, "parent_embed_id")
        embeds.append(ExampleEmbed(embed_id=embed_id, type=embed_type, content=content, parent_embed_id=parent_embed_id))
    return embeds


def parse_messages_array(array_source: str, translations: dict[str, str]) -> list[ExampleMessage]:
    messages: list[ExampleMessage] = []
    for block in top_level_object_blocks(array_source):
        role = extract_string_prop(block, "role") or "unknown"
        content = resolve_i18n(extract_string_prop(block, "content") or "", translations)
        model_name = extract_string_prop(block, "model_name")
        messages.append(ExampleMessage(role=role, content=content, model_name=model_name))
    return messages


def top_level_object_blocks(array_source: str) -> list[str]:
    blocks: list[str] = []
    in_string: str | None = None
    escape = False
    depth = 0
    block_start: int | None = None
    for index, char in enumerate(array_source):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == in_string:
                in_string = None
            continue
        if char in {'"', "'", "`"}:
            in_string = char
            continue
        if char == "{":
            if depth == 0:
                block_start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and block_start is not None:
                blocks.append(array_source[block_start : index + 1])
                block_start = None
    return blocks


def extract_string_prop(block: str, prop: str) -> str | None:
    match = re.search(rf'(?:(?:"{prop}")|(?:\b{prop}\b))\s*:\s*"((?:\\.|[^"\\])*)"', block)
    if not match:
        return None
    return bytes(match.group(1), "utf-8").decode("unicode_escape")


def extract_top_level_property(obj: str, prop: str) -> str | None:
    in_string: str | None = None
    escape = False
    brace_depth = 0
    bracket_depth = 0
    index = 0
    while index < len(obj):
        char = obj[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == in_string:
                in_string = None
            index += 1
            continue
        if char in {'"', "'", "`"}:
            in_string = char
            index += 1
            continue
        if char == "{":
            brace_depth += 1
            index += 1
            continue
        if char == "}":
            brace_depth -= 1
            index += 1
            continue
        if char == "[":
            bracket_depth += 1
            index += 1
            continue
        if char == "]":
            bracket_depth -= 1
            index += 1
            continue
        if brace_depth == 1 and bracket_depth == 0:
            key_match = re.match(rf'\s*(?:"{prop}"|{prop})\s*:', obj[index:])
            if key_match:
                value_start = index + key_match.end()
                while value_start < len(obj) and obj[value_start].isspace():
                    value_start += 1
                opening = obj[value_start]
                if opening == "[":
                    value_end = find_matching(obj, value_start, "[", "]")
                    return obj[value_start : value_end + 1]
                if opening == "{":
                    value_end = find_matching(obj, value_start, "{", "}")
                    return obj[value_start : value_end + 1]
        index += 1
    return None


def find_matching(source: str, start: int, opening: str, closing: str) -> int:
    in_string: str | None = None
    escape = False
    depth = 0
    for index in range(start, len(source)):
        char = source[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == in_string:
                in_string = None
            continue
        if char in {'"', "'", "`"}:
            in_string = char
            continue
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index
    raise ParseError(f"Could not find matching {closing!r}")


def transcript_for_prompt(chat: ExampleChatTranscript, max_chars: int, max_embed_chars: int) -> str:
    lines = [
        f"Title: {chat.title}",
        f"Slug: {chat.slug}",
        f"Category: {chat.category}",
        f"Summary: {chat.summary}",
        "",
        "Main chat:",
    ]
    lines.extend(format_messages(chat.messages))
    for title, messages in chat.sub_chats:
        lines.append("")
        lines.append(f"Sub-chat: {title}")
        lines.extend(format_messages(messages))
    if chat.embeds:
        lines.append("")
        lines.append("Attached embeds/artifacts available in the public example UI:")
        lines.extend(format_embeds(chat.embeds, max_embed_chars))
    transcript = "\n".join(lines)
    if len(transcript) <= max_chars:
        return transcript
    head = max_chars // 2
    tail = max_chars - head
    return transcript[:head] + "\n\n[... middle truncated by audit script ...]\n\n" + transcript[-tail:]


def format_embeds(embeds: list[ExampleEmbed], max_chars: int) -> list[str]:
    lines: list[str] = []
    remaining = max_chars
    for index, embed in enumerate(embeds, start=1):
        if remaining <= 0:
            lines.append("[additional embeds truncated by audit script]")
            break
        content = embed.content.strip()
        if len(content) > MAX_SINGLE_EMBED_CHARS:
            content = content[:MAX_SINGLE_EMBED_CHARS] + "\n[embed content truncated]"
        block = [
            f"[embed {index}] type={embed.type} id={embed.embed_id} parent={embed.parent_embed_id or 'none'}",
            content or "[empty embed content]",
            "",
        ]
        rendered = "\n".join(block)
        if len(rendered) > remaining:
            lines.append(rendered[:remaining] + "\n[embed section truncated by audit script]")
            break
        lines.append(rendered)
        remaining -= len(rendered)
    return lines


def format_messages(messages: list[ExampleMessage]) -> list[str]:
    lines: list[str] = []
    for index, message in enumerate(messages, start=1):
        model = f" ({message.model_name})" if message.model_name else ""
        lines.append(f"[{index}] {message.role}{model}:")
        lines.append(message.content.strip() or "[empty]")
        lines.append("")
    return lines


def quality_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "score": {"type": "number", "description": "0 terrible, 10 amazing"},
            "recommendation": {"type": "string", "enum": ["keep", "redo", "delete"]},
            "is_complete_useful": {"type": "boolean"},
            "reason": {"type": "string"},
            "major_issues": {"type": "array", "items": {"type": "string"}},
            "best_assistant_response_summary": {"type": "string"},
        },
        "required": [
            "score",
            "recommendation",
            "is_complete_useful",
            "reason",
            "major_issues",
            "best_assistant_response_summary",
        ],
    }


def call_gemini_quality(api_key: str, model: str, chat: ExampleChatTranscript, transcript: str) -> dict[str, Any]:
    current_date = datetime.now(UTC).date().isoformat()
    system_prompt = textwrap.dedent(
        f"""
        You are auditing public OpenMates example chats for product quality.
        Today's date is {current_date}. Do not call 2026 dates hallucinated or
        future dates if they are on or before today's date.

        Judge whether the assistant responses are clearly complete, useful, and
        impressive enough to publish as an example. The transcript includes both
        messages and attached embeds/artifacts; when a message references an
        embed, inspect the attached embed content before deciding the answer is
        missing. Penalize unfinished answers, weak generic replies, language
        mismatches, broken tool/embed references, hallucinated or ungrounded
        claims, obvious placeholders, bad formatting, and responses that do not
        satisfy the user's request. Do not penalize model_name metadata by
        itself, because OpenMates may use internal model aliases. Do not reward a
        chat just because it is long or uses tools. Return strict scores:
        0-3 delete, 4-6 redo, 7-10 keep.
        """
    ).strip()
    user_message = f"Evaluate this example chat. Score from 0 (terrible) to 10 (amazing).\n\n{transcript}"
    tool = {
        "function_declarations": [
            {
                "name": "return_example_chat_quality",
                "description": "Return the quality score and recommendation for one example chat.",
                "parameters": quality_schema(),
            }
        ]
    }
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "tools": [tool],
        "tool_config": {"function_calling_config": {"mode": "ANY"}},
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=120) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise GeminiAuditError(f"Gemini API error {exc.code} for {chat.slug}: {detail}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise GeminiAuditError(f"Gemini request failed for {chat.slug}: {exc}") from exc

    parts = response_payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    for part in parts:
        function_call = part.get("functionCall") if isinstance(part, dict) else None
        if function_call and function_call.get("name") == "return_example_chat_quality":
            result = function_call.get("args") or {}
            return normalize_result(result)
    text_response = "\n".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
    if text_response:
        try:
            return normalize_result(json.loads(text_response))
        except json.JSONDecodeError as exc:
            raise GeminiAuditError(f"Gemini returned non-JSON text for {chat.slug}: {text_response[:200]}") from exc
    raise GeminiAuditError(f"Gemini response did not include a quality result for {chat.slug}")


def normalize_result(result: dict[str, Any]) -> dict[str, Any]:
    score = max(0.0, min(10.0, float(result.get("score", 0))))
    if score < DELETE_THRESHOLD:
        recommendation = "delete"
    elif score < REDO_THRESHOLD:
        recommendation = "redo"
    else:
        recommendation = "keep"
    return {
        "score": score,
        "recommendation": recommendation,
        "model_recommendation": str(result.get("recommendation") or "").lower(),
        "is_complete_useful": bool(result.get("is_complete_useful", score >= REDO_THRESHOLD)),
        "reason": str(result.get("reason") or "").strip(),
        "major_issues": [str(issue) for issue in result.get("major_issues", []) if str(issue).strip()],
        "best_assistant_response_summary": str(result.get("best_assistant_response_summary") or "").strip(),
    }


def audit_chat(api_key: str, model: str, chat: ExampleChatTranscript, max_chars: int, max_embed_chars: int) -> dict[str, Any]:
    transcript = transcript_for_prompt(chat, max_chars, max_embed_chars)
    started = time.monotonic()
    result = call_gemini_quality(api_key, model, chat, transcript)
    elapsed = time.monotonic() - started
    return {
        "slug": chat.slug,
        "title": chat.title,
        "category": chat.category,
        "source_path": str(chat.source_path.relative_to(REPO_ROOT)),
        "internal": chat.internal,
        "message_count": len(chat.messages),
        "embed_count": len(chat.embeds),
        "sub_chat_count": len(chat.sub_chats),
        "transcript_chars_sent": len(transcript),
        "elapsed_seconds": round(elapsed, 2),
        **result,
    }


def default_output_path() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_OUTPUT_DIR / f"example-chat-quality-audit-{timestamp}.json"


def main() -> int:
    args = parse_args()
    sources = extract_registered_sources(include_internal=args.include_internal)
    if args.slug:
        wanted = set(args.slug)
        sources = [source for source in sources if source.slug in wanted]
        missing = wanted - {source.slug for source in sources}
        if missing:
            print(f"Unknown example chat slug(s): {', '.join(sorted(missing))}", file=sys.stderr)
            return 2
    if args.limit is not None:
        sources = sources[: args.limit]

    chats = [parse_chat(source) for source in sources]
    output = (args.output or default_output_path()).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    print(f"Found {len(extract_registered_sources(include_internal=False))} public example chats.")
    if args.include_internal:
        print(f"Auditing {len(chats)} chats including internal fixtures.")
    else:
        print(f"Auditing {len(chats)} public chats.")

    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model": args.model,
        "public_example_chat_count": len(extract_registered_sources(include_internal=False)),
        "audited_chat_count": len(chats),
        "delete_threshold": DELETE_THRESHOLD,
        "redo_threshold": REDO_THRESHOLD,
        "dry_run": args.dry_run,
        "results": [],
    }

    if args.dry_run:
        report["results"] = [
            {
                "slug": chat.slug,
                "title": chat.title,
                "message_count": len(chat.messages),
                "embed_count": len(chat.embeds),
                "sub_chat_count": len(chat.sub_chats),
                "transcript_chars": len(transcript_for_prompt(chat, args.max_transcript_chars, args.max_embed_chars)),
            }
            for chat in chats
        ]
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote dry-run report to {output.relative_to(REPO_ROOT)}")
        return 0

    api_key = load_gemini_api_key()
    if not api_key:
        print("No Gemini API key found. Set GEMINI_API_KEY or SECRET__GOOGLE_AI_STUDIO__API_KEY.", file=sys.stderr)
        return 2

    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(audit_chat, api_key, args.model, chat, args.max_transcript_chars, args.max_embed_chars): chat
            for chat in chats
        }
        for future in concurrent.futures.as_completed(futures):
            chat = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001 - keep auditing remaining chats.
                errors.append({"slug": chat.slug, "error": str(exc)})
                print(f"ERROR {chat.slug}: {exc}", file=sys.stderr)
                continue
            results.append(result)
            print(f"{result['score']:>4.1f} {result['recommendation']:<6} {result['slug']} - {result['reason'][:120]}")

    results.sort(key=lambda item: (item["score"], item["slug"]))
    report["results"] = results
    report["errors"] = errors
    report["recommendations"] = {
        "delete": [item for item in results if item["recommendation"] == "delete"],
        "redo": [item for item in results if item["recommendation"] == "redo"],
        "keep": [item for item in results if item["recommendation"] == "keep"],
    }
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote quality report to {output.relative_to(REPO_ROOT)}")
    if errors:
        print(f"Completed with {len(errors)} audit errors.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
