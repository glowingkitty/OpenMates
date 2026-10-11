"""
Regression tests for AI ask task chat-history boundaries.

Compression summaries are server-readable context for model processing. They
must stay out of Directus chat history unless a client supplies client-encrypted
ciphertext for that history entry.
"""

# contract-test-file: infrastructure

import ast
from pathlib import Path


def test_early_typing_skips_duplicate_late_key_read_and_payload():
    source = (Path(__file__).resolve().parents[1] / "tasks" / "ask_skill_task.py").read_text()
    tree = ast.parse(source)
    late_region = source.split("# Persist server provider/region on preprocessing_result", maxsplit=1)[1]
    late_region = late_region.split("# CRITICAL: Skip WebSocket events for external requests", maxsplit=1)[0]
    assert "preprocessing_result.server_provider_name = provider_name" in late_region
    assert "preprocessing_result.server_region = server_region" in late_region

    guards = [node for node in ast.walk(tree) if isinstance(node, ast.If)
              and ast.unparse(node.test) == "not typing_lifecycle.started"
              and any(isinstance(child, ast.Call)
                      and isinstance(child.func, ast.Attribute)
                      and child.func.attr == "get_chat_list_item_data"
                      for child in ast.walk(node))]
    assert len(guards) == 1
    guarded = ast.get_source_segment(source, guards[0])
    assert "encrypted_chat_key_for_typing" in guarded
    assert '"event_for_client": "ai_typing_started"' in guarded
    assert "typing_payload_data = {}" in late_region.split("if not typing_lifecycle.started:", maxsplit=1)[0]
    assert "late_payload=typing_payload_data" in source


def test_chat_compression_does_not_persist_server_encrypted_summary_to_history():
    source = (Path(__file__).resolve().parents[1] / "tasks" / "ask_skill_task.py").read_text()
    compression_block = source.split("async def _compress_for_selected_model(", maxsplit=1)[1]
    compression_block = compression_block.split("async def _async_process_ai_skill_ask_task(", maxsplit=1)[0]

    assert "set_ai_messages_history" in compression_block
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


def test_focus_mode_continuations_preserve_recovery_identity():
    ai_app_root = Path(__file__).resolve().parents[1]
    backend_root = ai_app_root.parents[1]
    main_processor_source = (ai_app_root / "processing" / "main_processor.py").read_text()
    mock_replay_source = (ai_app_root / "testing" / "mock_replay.py").read_text()
    auto_confirm_source = (ai_app_root / "tasks" / "focus_mode_auto_confirm_task.py").read_text()
    ask_task_source = (ai_app_root / "tasks" / "ask_skill_task.py").read_text()
    ask_skill_source = (ai_app_root / "skills" / "ask_skill.py").read_text()
    stream_consumer_source = (ai_app_root / "tasks" / "stream_consumer.py").read_text()
    rejection_source = (
        backend_root
        / "core/api/app/routes/handlers/websocket_handlers/focus_mode_rejected_handler.py"
    ).read_text()

    recovery_fields = (
        "recovery_inference_task_id",
        "recovery_preflight_id",
        "recovery_turn_id",
        "recovery_public_key",
        "chat_key_version",
    )

    for field in recovery_fields:
        assert main_processor_source.count(f'"{field}"') >= 2
        assert f'"{field}"' in mock_replay_source
        assert f'"{field}"' in auto_confirm_source
        assert f'"{field}"' in rejection_source

    assert "def resolved_recovery_inference_task_id" in ask_skill_source
    assert "request_data.resolved_recovery_inference_task_id()" in ask_task_source
    assert "request_data.resolved_recovery_inference_task_id()" in stream_consumer_source
    assert "request_data.resolved_recovery_inference_task_id()" in mock_replay_source
    assert "if not _contains_focus_mode_activation_embed(full_response):" in mock_replay_source
    assert (
        "original_request.recovery_task_id or original_request.recovery_inference_task_id"
        in stream_consumer_source
    )
