#!/usr/bin/env python3
"""
Generate approved prerecorded assistant-response acknowledgement assets.

Runs inside the API container so ElevenLabs credentials remain Vault-backed.
Generation is explicit, resumable, language-scoped, and checks credits first.
Usage: python /app/backend/scripts/generate_assistant_acknowledgements.py --language en-US [--generate]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from types import MappingProxyType
from typing import Any

import httpx

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.apps.audio.assistant_speech.acknowledgements import ACKNOWLEDGEMENT_TEXTS  # noqa: E402
from backend.apps.audio.assistant_speech.voice_profiles import ASSISTANT_VOICE_PROVIDER_IDS  # noqa: E402
from backend.apps.audio.pricing import ASSISTANT_RESPONSE_SPEECH_MODEL  # noqa: E402
from backend.core.api.app.utils.secrets_manager import SecretsManager  # noqa: E402
from backend.shared.providers.elevenlabs.client import DEFAULT_OUTPUT_FORMAT, ElevenLabsClient  # noqa: E402


DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "frontend/apps/web_app/static/audio/assistant-acknowledgements"
MANIFEST_FILENAME = "manifest.json"
MANIFEST_SCHEMA_VERSION = 1
GERMAN_V3_PROMPT_TAGS = MappingProxyType(
    {
        "general": ("[warmly]",),
        "lookup": ("[curious]",),
        "reasoning": ("[thoughtful]", "[slow]"),
        "action": ("[focused]",),
    }
)


def build_generation_prompt(*, language: str, category: str, text: str) -> dict[str, Any]:
    """Return provider-only prompt metadata while preserving public transcript text."""

    tags = GERMAN_V3_PROMPT_TAGS.get(category, ()) if language == "de-DE" else ()
    tag_prefix = " ".join(tags)
    return {
        "generation_prompt": f"{tag_prefix} {text}" if tag_prefix else text,
        "generation_tags": tuple(tags),
    }


def build_plan(language: str, output_root: Path) -> list[dict[str, Any]]:
    language_catalog = ACKNOWLEDGEMENT_TEXTS.get(language)
    if language_catalog is None:
        raise ValueError(f"No approved acknowledgement text exists for {language}.")

    plan: list[dict[str, Any]] = []
    for profile_key in sorted(ASSISTANT_VOICE_PROVIDER_IDS):
        for category, variants in language_catalog.items():
            for variant, text in enumerate(variants, start=1):
                relative_path = Path(profile_key) / language / f"{category}-{variant}.mp3"
                plan.append(
                    {
                        "clip_id": f"{profile_key}-{language}-{category}-{variant}",
                        "voice_profile_id": profile_key,
                        "voice_profile_version": 1,
                        "language": language,
                        "request_category": category,
                        "variant": variant,
                        "text": text,
                        "relative_path": relative_path.as_posix(),
                        "output_path": output_root / relative_path,
                    }
                    | build_generation_prompt(language=language, category=category, text=text)
                )
    return plan


def _remaining_credits(subscription: dict[str, Any]) -> int | None:
    used = subscription.get("character_count")
    limit = subscription.get("character_limit")
    if not isinstance(used, int) or not isinstance(limit, int):
        return None
    return max(0, limit - used)


def _missing_permission(response: httpx.Response) -> str | None:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return None
    if not isinstance(detail, dict) or detail.get("status") != "missing_permissions":
        return None
    message = str(detail.get("message") or "")
    marker = "missing the permission "
    return message.split(marker, maxsplit=1)[1].split(maxsplit=1)[0] if marker in message else "unknown"


def _public_entry(item: dict[str, Any], *, audio_bytes: bytes, duration_seconds: float | None) -> dict[str, Any]:
    return {
        key: item[key]
        for key in (
            "clip_id",
            "voice_profile_id",
            "voice_profile_version",
            "language",
            "request_category",
            "variant",
            "text",
            "relative_path",
        )
    } | {
        "sha256": hashlib.sha256(audio_bytes).hexdigest(),
        "duration_seconds": duration_seconds,
    }


def _write_manifest(output_root: Path, entries: dict[str, dict[str, Any]]) -> None:
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "provider": "elevenlabs",
        "provider_model_id": ASSISTANT_RESPONSE_SPEECH_MODEL,
        "clips": [entries[key] for key in sorted(entries)],
    }
    manifest_path = output_root / MANIFEST_FILENAME
    temporary_path = manifest_path.with_suffix(".json.tmp")
    temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(manifest_path)


def _load_manifest_entries(output_root: Path) -> dict[str, dict[str, Any]]:
    manifest_path = output_root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        entry["clip_id"]: entry
        for entry in payload.get("clips", [])
        if isinstance(entry, dict) and isinstance(entry.get("clip_id"), str)
    }


def _reconcile_existing_assets(
    plan: list[dict[str, Any]],
    entries: dict[str, dict[str, Any]],
) -> bool:
    changed = False
    for item in plan:
        output_path: Path = item["output_path"]
        entry = entries.get(item["clip_id"])
        if not output_path.is_file():
            if entry is not None:
                entries.pop(item["clip_id"])
                changed = True
            continue
        audio_bytes = output_path.read_bytes()
        digest = hashlib.sha256(audio_bytes).hexdigest()
        if entry is None:
            entries[item["clip_id"]] = _public_entry(item, audio_bytes=audio_bytes, duration_seconds=None)
            changed = True
            continue
        if entry.get("sha256") != digest:
            raise RuntimeError(f"Existing acknowledgement asset failed checksum validation: {item['clip_id']}")
    return changed


async def run(
    *,
    language: str,
    output_root: Path,
    generate: bool,
    verify_only: bool = False,
    allow_missing_user_read: bool = False,
) -> int:
    plan = build_plan(language, output_root)
    existing_entries = _load_manifest_entries(output_root)
    repaired_manifest = _reconcile_existing_assets(plan, existing_entries)
    if repaired_manifest:
        _write_manifest(output_root, existing_entries)
    pending_plan = [item for item in plan if item["clip_id"] not in existing_entries]
    required_characters = sum(len(item["generation_prompt"]) for item in pending_plan)
    if verify_only:
        if pending_plan:
            print(
                json.dumps(
                    {
                        "status": "fail",
                        "language": language,
                        "missing_clip_count": len(pending_plan),
                    }
                )
            )
            return 1
        print(json.dumps({"status": "pass", "language": language, "clip_count": len(plan)}))
        return 0

    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    client = ElevenLabsClient(secrets_manager=secrets_manager)
    try:
        try:
            subscription = await client.get_subscription()
        except httpx.HTTPStatusError as error:
            missing_permission = _missing_permission(error.response)
            if missing_permission and generate and allow_missing_user_read:
                print(
                    json.dumps(
                        {
                            "status": "warning",
                            "warning": "quota preflight waived",
                            "missing_permission": missing_permission,
                        }
                    )
                )
                subscription = {}
            elif missing_permission:
                print(
                    json.dumps(
                        {
                            "status": "fail",
                            "error": "missing ElevenLabs API key permission",
                            "required_permission": missing_permission,
                        }
                    )
                )
                return 2
            else:
                raise
        remaining_before = _remaining_credits(subscription)
        print(
            json.dumps(
                {
                    "status": "ready" if not generate else "starting",
                    "language": language,
                    "clip_count": len(plan),
                    "pending_clip_count": len(pending_plan),
                    "required_characters": required_characters,
                    "remaining_credits": remaining_before,
                    "generation_requested": generate,
                }
            )
        )
        if not generate:
            return 0
        if remaining_before is not None and remaining_before < required_characters:
            print(json.dumps({"status": "fail", "error": "insufficient ElevenLabs credits"}))
            return 1

        output_root.mkdir(parents=True, exist_ok=True)
        generated_count = 0
        for item in pending_plan:
            output_path: Path = item["output_path"]
            output_path.parent.mkdir(parents=True, exist_ok=True)
            result = await client.text_to_speech(
                text=item["generation_prompt"],
                voice_id=ASSISTANT_VOICE_PROVIDER_IDS[item["voice_profile_id"]],
                model=ASSISTANT_RESPONSE_SPEECH_MODEL,
                output_format=DEFAULT_OUTPUT_FORMAT,
            )
            temporary_path = output_path.with_suffix(".mp3.tmp")
            temporary_path.write_bytes(result.audio_bytes)
            temporary_path.replace(output_path)
            existing_entries[item["clip_id"]] = _public_entry(
                item,
                audio_bytes=result.audio_bytes,
                duration_seconds=result.duration_seconds,
            )
            _write_manifest(output_root, existing_entries)
            generated_count += 1

        subscription_after = {} if allow_missing_user_read else await client.get_subscription()
        print(
            json.dumps(
                {
                    "status": "pass",
                    "language": language,
                    "generated_clip_count": generated_count,
                    "remaining_credits": _remaining_credits(subscription_after),
                    "manifest": str(output_root / MANIFEST_FILENAME),
                }
            )
        )
        return 0
    finally:
        await secrets_manager.aclose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", required=True, choices=sorted(ACKNOWLEDGEMENT_TEXTS))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--generate", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    parser.add_argument(
        "--allow-missing-user-read",
        action="store_true",
        help="Explicitly waive the quota preflight when a restricted key lacks user_read.",
    )
    arguments = parser.parse_args()
    if arguments.allow_missing_user_read and not arguments.generate:
        parser.error("--allow-missing-user-read requires --generate")
    return asyncio.run(
        run(
            language=arguments.language,
            output_root=arguments.output_root,
            generate=arguments.generate,
            verify_only=arguments.verify_only,
            allow_missing_user_read=arguments.allow_missing_user_read,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
