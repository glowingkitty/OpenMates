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
SOFTWARE_DEVELOPMENT_MATE_PATH = Path(__file__).resolve().parents[1] / "apps/ai/mates/software_development.md"


def test_code_instruction_disables_application_preview_for_runnable_web_apps() -> None:
    instruction = CODE_BLOCK_INSTRUCTION_PATH.read_text(encoding="utf-8")

    assert "Runnable web apps" in instruction
    assert "Application preview embeds are currently disabled" in instruction
    assert "Do not emit `application_preview` fences" in instruction
    assert "temporarily unavailable" in instruction


def test_stream_consumer_suppresses_deferred_application_preview_chunks() -> None:
    source = STREAM_CONSUMER_PATH.read_text(encoding="utf-8")

    assert "is_deferred_protocol_block" in source
    assert "_is_application_preview_combined_language(current_code_language)" in source
    assert "if current_code_embed_id or is_deferred_protocol_block" in source
    assert "replaced with an embed reference at close" in source


def test_stream_consumer_strips_raw_application_source_after_parent_embed() -> None:
    source = STREAM_CONSUMER_PATH.read_text(encoding="utf-8")

    assert "def _strip_generated_application_source_text" in source
    assert "def _extract_loose_application_preview_files_from_text" in source
    assert "APPLICATION_PREVIEW_DEFAULT_PACKAGE_JSON" in source
    assert "_find_application_embed_reference_start(response_text, bundle_start)" in source
    assert "payload.get(\"type\") == \"application\"" in source
    assert "_strip_generated_application_source_text(" in source


def test_mermaid_instruction_is_inactive_and_prefers_source_only() -> None:
    instruction = MERMAID_INSTRUCTION_PATH.read_text(encoding="utf-8")

    assert "Mermaid/Diagrams embed support is currently disabled" in instruction
    assert "prefer a readable ASCII/text diagram" in instruction
    assert "Only write Mermaid source when the user explicitly asks" in instruction


def test_software_development_mate_prefers_ascii_diagrams() -> None:
    prompt = SOFTWARE_DEVELOPMENT_MATE_PATH.read_text(encoding="utf-8")

    assert "prefer readable ASCII/text diagrams" in prompt
    assert "Do not use Mermaid" in prompt
    assert "unless the user explicitly asks for Mermaid syntax" in prompt
