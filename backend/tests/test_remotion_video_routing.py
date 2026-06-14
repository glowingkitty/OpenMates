"""Regression tests for routing deterministic video requests to Remotion.

These tests keep the Videos app metadata and global code-fence instructions in
sync so product-announcement/text-slide requests do not fall back to Veo.
"""

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
VIDEOS_APP = REPO_ROOT / "backend/apps/videos/app.yml"
CODE_BLOCK_INSTRUCTIONS = REPO_ROOT / "backend/apps/ai/instructions/base_code_block_instruction.md"


def _video_skill(skill_id: str) -> dict:
    config = yaml.safe_load(VIDEOS_APP.read_text())
    return next(skill for skill in config["skills"] if skill["id"] == skill_id)


def test_product_announcements_route_to_remotion_create_hint() -> None:
    create_hint = _video_skill("create")["preprocessor_hint"]

    assert "product announcements" in create_hint
    assert "text" in create_hint
    assert "```remotion:Name.tsx" in create_hint
    assert "photorealistic footage" in create_hint


def test_veo_generate_hint_excludes_deterministic_text_slide_requests() -> None:
    generate_hint = _video_skill("generate")["preprocessor_hint"]

    deterministic_terms = [
        "text slides",
        "product announcements",
        "diagrams",
        "charts",
        "UI-like motion graphics",
        "branded videos",
    ]

    for term in deterministic_terms:
        assert term in generate_hint
    assert "videos.create" in generate_hint
    assert "```remotion:Name.tsx" in generate_hint
    assert "photorealistic" in generate_hint
    assert "whenever" not in generate_hint.lower()


def test_code_block_instructions_require_explicit_remotion_fences() -> None:
    instructions = CODE_BLOCK_INSTRUCTIONS.read_text()

    assert "```remotion:ProductAnnouncement.tsx" in instructions
    assert "Do NOT use generic `tsx`" in instructions
    assert "Generic TSX remains a normal code embed" in instructions
