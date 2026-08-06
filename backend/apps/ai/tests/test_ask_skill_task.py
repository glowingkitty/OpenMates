"""
Regression tests for AI ask task chat-history boundaries.

Compression summaries are server-readable context for model processing. They
must stay out of Directus chat history unless a client supplies client-encrypted
ciphertext for that history entry.
"""

from pathlib import Path


def test_chat_compression_does_not_persist_server_encrypted_summary_to_history():
    source = (Path(__file__).resolve().parents[1] / "tasks" / "ask_skill_task.py").read_text()
    compression_block = source.split("Compression succeeded:", maxsplit=1)[1]
    compression_block = compression_block.split(
        "# Update request_data.message_history with compressed version",
        maxsplit=1,
    )[0]

    assert "persist_new_chat_message" not in compression_block


def test_explicit_focus_override_preserves_canonical_activation_pipeline():
    source = (Path(__file__).resolve().parents[1] / "tasks" / "ask_skill_task.py").read_text()
    main_processor_source = (
        Path(__file__).resolve().parents[1] / "processing" / "main_processor.py"
    ).read_text()
    explicit_activation_block = main_processor_source.split(
        "# --- User-requested focus mode: bypass LLM + countdown ---",
        maxsplit=1,
    )[1].split("# === BUILD MODEL FALLBACK LIST ===", maxsplit=1)[0]

    assert "request_data.active_focus_id = requested_focus_id" not in source
    assert "preprocessing_result.enable_subchats = resolve_subchat_enablement(" not in source
    assert "user_requested_focus_only and relevant_focus_modes and not has_active_focus_mode" in explicit_activation_block
    assert "countdown=0" in explicit_activation_block
