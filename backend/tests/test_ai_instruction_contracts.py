"""AI instruction contract tests.

These tests intentionally avoid importing the AI runtime. They guard prompt
contracts that are easy to regress during small instruction edits and should
remain runnable even when optional provider dependencies are absent from the
local Python environment.
"""

from pathlib import Path


CODE_BLOCK_INSTRUCTION_PATH = Path(__file__).resolve().parents[1] / "apps/ai/instructions/base_code_block_instruction.md"
STREAM_CONSUMER_PATH = Path(__file__).resolve().parents[1] / "apps/ai/tasks/stream_consumer.py"
MERMAID_INSTRUCTION_PATH = Path(__file__).resolve().parents[1] / "apps/ai/instructions/base_mermaid_code_block_instruction.md"


def test_code_instruction_requires_application_preview_for_runnable_web_apps() -> None:
    instruction = CODE_BLOCK_INSTRUCTION_PATH.read_text(encoding="utf-8")

    assert "Runnable web apps" in instruction
    assert "application_preview" in instruction
    assert "package.json" in instruction
    assert "src/main.ts" in instruction
    assert "Do not provide `localhost` links" in instruction


def test_stream_consumer_suppresses_deferred_application_preview_chunks() -> None:
    source = STREAM_CONSUMER_PATH.read_text(encoding="utf-8")

    assert "is_deferred_protocol_block" in source
    assert "_is_application_preview_combined_language(current_code_language)" in source
    assert "if current_code_embed_id or is_deferred_protocol_block" in source
    assert "replaced with an embed reference at close" in source


def test_mermaid_instruction_requires_mermaid_fences_for_diagrams() -> None:
    instruction = MERMAID_INSTRUCTION_PATH.read_text(encoding="utf-8")

    assert "When the user asks for a diagram" in instruction
    assert "```mermaid" in instruction
    assert "Do not use a generic `code`, `json`, `text`, `markdown`" in instruction
    assert "OpenMates can create a Diagrams embed" in instruction
