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
import subprocess
import sys
import tempfile
from pathlib import Path
from types import MappingProxyType
from typing import Any

import httpx

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.apps.audio.assistant_speech.acknowledgements import (  # noqa: E402
    ACKNOWLEDGEMENT_TEXTS, CHAT_START_CATEGORY, CHAT_START_TEXTS, SYSTEM_VOICE_PROFILE_ID,
)
from backend.apps.audio.assistant_speech.voice_profiles import (  # noqa: E402
    ASSISTANT_VOICE_PROVIDER_IDS, SYSTEM_VOICE_PROVIDER_ID,
)
from backend.apps.audio.pricing import ELEVEN_V4_TURBO_SPEECH_MODEL as ASSISTANT_RESPONSE_SPEECH_MODEL  # noqa: E402
from backend.core.api.app.utils.secrets_manager import SecretsManager  # noqa: E402
from backend.shared.providers.elevenlabs.client import DEFAULT_OUTPUT_FORMAT, ElevenLabsClient  # noqa: E402


DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "frontend/apps/web_app/static/audio/assistant-acknowledgements"
MANIFEST_FILENAME = "manifest.json"
MANIFEST_SCHEMA_VERSION = 1
LOCALIZED_V3_PROMPT_TAGS = MappingProxyType(
    {
        "general": ("[warmly]",),
        "lookup": ("[curious]",),
        "reasoning": ("[thoughtful]", "[slow]"),
        "action": ("[focused]",),
    }
)


def build_generation_prompt(*, language: str, category: str, text: str) -> dict[str, Any]:
    """Return provider-only prompt metadata while preserving public transcript text."""

    tags = LOCALIZED_V3_PROMPT_TAGS.get(category, ()) if language != "en-US" else ()
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
    chat_start_text = CHAT_START_TEXTS.get(language)
    if chat_start_text:
        # Neutral system voice with a leading chime: a new chat has no Mate yet.
        relative_path = Path(SYSTEM_VOICE_PROFILE_ID) / language / f"{CHAT_START_CATEGORY}-1.mp3"
        plan.append(
            {
                "clip_id": f"{SYSTEM_VOICE_PROFILE_ID}-{language}-{CHAT_START_CATEGORY}-1",
                "voice_profile_id": SYSTEM_VOICE_PROFILE_ID,
                "voice_profile_version": 1,
                "language": language,
                "request_category": CHAT_START_CATEGORY,
                "variant": 1,
                "text": chat_start_text,
                "relative_path": relative_path.as_posix(),
                "output_path": output_root / relative_path,
                "generation_prompt": chat_start_text,
                "generation_tags": (),
                "leading_chime": True,
            }
        )
    return plan


def provider_voice_id(item: dict[str, Any]) -> str:
    if item["voice_profile_id"] == SYSTEM_VOICE_PROFILE_ID:
        return SYSTEM_VOICE_PROVIDER_ID
    return ASSISTANT_VOICE_PROVIDER_IDS[item["voice_profile_id"]]


# Two soft rising notes, distinct from the local call connect/mute/end cues.
CHIME_NOTES = ((783.99, 0.09), (1046.5, 0.14))
CHIME_GAP_SECONDS = 0.12


def chime_filter_graph() -> str:
    """ffmpeg graph: chime notes, a short gap, then the voice (input index len(CHIME_NOTES))."""
    parts, labels = [], []
    for index, (_frequency, duration) in enumerate(CHIME_NOTES):
        parts.append(
            f"[{index}]volume=1.2,afade=t=in:d=0.01,afade=t=out:st={duration - 0.04:.2f}:d=0.04,"
            f"aresample=44100,aformat=channel_layouts=mono[n{index}]"
        )
        labels.append(f"[n{index}]")
    parts.append(f"anullsrc=r=44100:cl=mono,atrim=duration={CHIME_GAP_SECONDS}[gap]")
    parts.append(f"[{len(CHIME_NOTES)}]aresample=44100,aformat=channel_layouts=mono[voice]")
    parts.append("".join(labels) + f"[gap][voice]concat=n={len(CHIME_NOTES) + 2}:v=0:a=1[out]")
    return ";".join(parts)


def with_leading_chime(audio_bytes: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as directory:
        voice_path = Path(directory) / "voice.mp3"
        output_path = Path(directory) / "out.mp3"
        voice_path.write_bytes(audio_bytes)
        inputs: list[str] = []
        for frequency, duration in CHIME_NOTES:
            inputs += ["-f", "lavfi", "-i", f"sine=frequency={frequency}:duration={duration}"]
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs, "-i", str(voice_path),
             "-filter_complex", chime_filter_graph(), "-map", "[out]", "-c:a", "libmp3lame", "-b:a", "128k",
             str(output_path)],
            check=True,
        )
        return output_path.read_bytes()


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
        "provider_model_id": ASSISTANT_RESPONSE_SPEECH_MODEL,
    }


def _write_manifest(output_root: Path, entries: dict[str, dict[str, Any]]) -> None:
    manifest_path = output_root / MANIFEST_FILENAME
    # The header names the model of the original catalogue; clips generated
    # later carry their own provider_model_id.
    header_model = ASSISTANT_RESPONSE_SPEECH_MODEL
    if manifest_path.is_file():
        header_model = json.loads(manifest_path.read_text(encoding="utf-8")).get("provider_model_id", header_model)
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "provider": "elevenlabs",
        "provider_model_id": header_model,
        "clips": [entries[key] for key in sorted(entries)],
    }
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
                voice_id=provider_voice_id(item),
                model=ASSISTANT_RESPONSE_SPEECH_MODEL,
                output_format=DEFAULT_OUTPUT_FORMAT,
            )
            audio_bytes = result.audio_bytes
            duration_seconds = result.duration_seconds
            if item.get("leading_chime"):
                audio_bytes = with_leading_chime(audio_bytes)
                if duration_seconds is not None:
                    duration_seconds = round(
                        duration_seconds + sum(duration for _f, duration in CHIME_NOTES) + CHIME_GAP_SECONDS, 3,
                    )
            temporary_path = output_path.with_suffix(".mp3.tmp")
            temporary_path.write_bytes(audio_bytes)
            temporary_path.replace(output_path)
            existing_entries[item["clip_id"]] = _public_entry(
                item,
                audio_bytes=audio_bytes,
                duration_seconds=duration_seconds,
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
