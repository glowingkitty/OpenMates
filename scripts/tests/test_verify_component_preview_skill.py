"""Guard the component-first UI verification workflow.

The canonical Claude skill and generated OpenCode/Codex mirror must stay equal.
The contract requires URL-configured bare previews and a dedicated component
spec directory before broader use-case Playwright verification.
"""

# contract-test-file: tooling

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_SKILL = REPOSITORY_ROOT / ".claude/skills/verify-component-preview/SKILL.md"
MIRRORED_SKILL = REPOSITORY_ROOT / ".agents/skills/verify-component-preview/SKILL.md"


def test_component_preview_skill_mirror_matches_canonical() -> None:
    assert MIRRORED_SKILL.read_text(encoding="utf-8") == CANONICAL_SKILL.read_text(encoding="utf-8")


def test_component_preview_skill_requires_bare_component_first() -> None:
    source = CANONICAL_SKILL.read_text(encoding="utf-8")

    required_contract = (
        "chrome=0",
        "frontend/apps/web_app/tests/components/",
        "before creating, extending, or running the broader",
        "preview-toolbar",
        "preview-status-bar",
        "missing or wrong icon",
        "playwright-account: not_required reason=isolated_component_preview",
    )
    for requirement in required_contract:
        assert requirement in source
