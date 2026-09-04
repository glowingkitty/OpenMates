#!/usr/bin/env python3
"""Audit the removed AI-memory boundary across generated product surfaces.

AI must expose no memory categories, examples, or client registry entries.
The audit also requires a retained non-AI category so broad app-memory removal
cannot satisfy the negative checks accidentally.
"""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
AI_APP_YAML = ROOT / "backend/apps/ai/app.yml"
TRAVEL_APP_YAML = ROOT / "backend/apps/travel/app.yml"
SURFACES = (
    ROOT / "frontend/packages/ui/src/data/appsMetadata.ts",
    ROOT / "frontend/packages/ui/src/components/settings/SettingsAI.svelte",
    ROOT / "frontend/packages/openmates-cli/src/client.ts",
    ROOT / "frontend/packages/ui/src/demo_chats/exampleChatData.ts",
    ROOT / "frontend/packages/ui/src/demo_chats/interestTags.ts",
    ROOT / "apple/OpenMates/Sources/Features/Settings/Views/SettingsAIFull.swift",
)
FORBIDDEN_MARKERS = (
    "ai/communication_style",
    "ai/learning_preferences",
    "memory-ai-communication-style",
    "memory-ai-learning-preferences",
    "app_settings_memories.ai",
    "AIMemoryCategory",
    "AIMemoryAppStoreCard",
)


def main() -> int:
    ai_metadata = yaml.safe_load(AI_APP_YAML.read_text(encoding="utf-8")) or {}
    travel_metadata = yaml.safe_load(TRAVEL_APP_YAML.read_text(encoding="utf-8")) or {}
    errors: list[str] = []

    if ai_metadata.get("settings_and_memories"):
        errors.append("backend/apps/ai/app.yml still defines memory categories")
    if not travel_metadata.get("settings_and_memories"):
        errors.append("non-AI app-memory control is missing from Travel metadata")

    for path in SURFACES:
        content = path.read_text(encoding="utf-8")
        for marker in FORBIDDEN_MARKERS:
            if marker in content:
                errors.append(f"{path.relative_to(ROOT)} still contains {marker}")

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1

    print("PASS: AI memories are absent and non-AI app memories remain registered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
