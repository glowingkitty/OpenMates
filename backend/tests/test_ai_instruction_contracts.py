"""AI instruction contract tests.

These tests intentionally avoid importing the AI runtime. They guard prompt
contracts that are easy to regress during small instruction edits and should
remain runnable even when optional provider dependencies are absent from the
local Python environment.
"""

from pathlib import Path


CODE_BLOCK_INSTRUCTION_PATH = Path(__file__).resolve().parents[1] / "apps/ai/instructions/base_code_block_instruction.md"


def test_code_instruction_requires_application_preview_for_runnable_web_apps() -> None:
    instruction = CODE_BLOCK_INSTRUCTION_PATH.read_text(encoding="utf-8")

    assert "Runnable web apps" in instruction
    assert "application_preview" in instruction
    assert "package.json" in instruction
    assert "src/main.ts" in instruction
    assert "Do not provide `localhost` links" in instruction
